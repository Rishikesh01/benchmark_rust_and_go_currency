#!/usr/bin/env python3
"""Builds and runs the Tokio / Crossbeam / Go benchmark suite.

Every run is a fresh process pinned with `taskset` to exactly `threads` logical
CPUs (one per physical core before any SMT sibling). Implementation order is
shuffled every round so thermal drift doesn't always hit the same one. Each
result is checked against its expected checksum and appended to
<out>/raw.jsonl as it arrives; report.py turns that into tables and charts.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import re
import resource
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import report

ROOT = Path(__file__).resolve().parent.parent
BINARIES = {
    "tokio": ROOT / "rust/target/release/tokio-bench",
    "crossbeam": ROOT / "rust/target/release/crossbeam-bench",
    "go": ROOT / "go/bin/gobench",
    "tokio-tuned": ROOT / "rust/target/release/tokio-tuned-bench",
}
DEFAULT_IMPLS = ["tokio", "crossbeam", "go"]

# Screening builds for single Tokio tweaks, used as `--impls tokio+batch,tokio+mimalloc+kanal,...`.
# They run rust/tokio-variants-bench (separate from tokio-bench and tokio-tuned-bench), and must
# match VARIANTS in its lib.rs. None = every workload.
TOKIO_VARIANTS_BINARY = ROOT / "rust/target/release/tokio-variants-bench"
TOKIO_VARIANTS_MIMALLOC_BINARY = ROOT / "rust/target/release/tokio-variants-bench-mimalloc"
TOKIO_VARIANTS = {
    "mimalloc": (None, "mimalloc global allocator"),
    "batch": ({"spsc", "mpmc", "select"}, "receive up to 256 queued messages per wake-up"),
    "unconstrained": ({"spsc", "select", "pingpong", "mutex"}, "tasks opt out of Tokio's co-operative yield budget"),
    "kanal": ({"spsc", "mpmc", "pingpong"}, "kanal async channels instead of tokio/async-channel"),
    "flume": ({"spsc", "mpmc", "pingpong"}, "flume async channels instead of tokio/async-channel"),
    "join": ({"spsc", "pingpong"}, "both sides as futures in one task via join! (no parallelism)"),
    "no-handles": ({"spawn"}, "no JoinHandles; tasks write results into a shared slice, like the Go version"),
    "biased": ({"select"}, "select! polls branches in a fixed order instead of randomly"),
    "std-mutex": ({"mutex"}, "std::sync::Mutex, never held across .await"),
    "parking-lot": ({"mutex"}, "parking_lot::Mutex, never held across .await"),
}

U64 = 1 << 64

# Test cases and the parameters passed identically to every implementation. Channel capacity is the
# same for all implementations in a case; the -cap1 cases repeat a channel test with capacity 1.
WORKLOAD_PARAMS = {
    "spsc": {"capacity": 1024},
    "spsc-cap1": {"capacity": 1},
    "mpmc": {"capacity": 1024, "producers": 4, "consumers": 4},
    "mpmc-cap1": {"capacity": 1, "producers": 4, "consumers": 4},
    # A prime stride, so samples can't line up with Tokio's co-op budget of 128 polls.
    "pingpong": {"sample-every": 17},
    "spawn": {},
    "cpu": {"tasks": 256, "rounds": 32},
    "select": {"capacity": 1024},
    "select-cap1": {"capacity": 1},
    "mutex": {"workers": 8},
    "idle": {"settle-ms": 200},
}

# Cases that run another workload's code with different parameters.
CASE_WORKLOAD = {"spsc-cap1": "spsc", "mpmc-cap1": "mpmc", "select-cap1": "select"}


def program_workload(case: str) -> str:
    """The --workload a binary runs for a test case."""
    return CASE_WORKLOAD.get(case, case)


PROFILES = {
    # Seconds-per-run sizes to prove everything works end to end.
    "smoke": {
        "warmup": 1,
        "reps": 3,
        "threads": [1, 2, 6, 12],
        "sizes": {
            "spsc": [200_000],
            "spsc-cap1": [20_000],
            "mpmc": [200_000],
            "mpmc-cap1": [20_000],
            "pingpong": [20_000],
            "spawn": [10_000, 100_000],
            "cpu": [500_000],
            "select": [200_000],
            "select-cap1": [20_000],
            "mutex": [200_000],
            "idle": [10_000, 100_000],
        },
    },
    # Sized for roughly 0.2-2 s per run on a 6-core laptop CPU.
    "full": {
        "warmup": 3,
        "reps": 10,
        "threads": [1, 2, 6, 12],
        "sizes": {
            "spsc": [10_000_000],
            # Capacity 1 can need a thread switch per message (Crossbeam: ~130K msgs/s on 1 CPU).
            "spsc-cap1": [1_000_000],
            "mpmc": [10_000_000],
            "mpmc-cap1": [1_000_000],
            "pingpong": [1_000_000],
            "spawn": [10_000, 1_000_000],
            "cpu": [16_000_000],
            "select": [10_000_000],
            "select-cap1": [1_000_000],
            "mutex": [10_000_000],
            "idle": [10_000, 100_000, 1_000_000],
        },
    },
}

# Memory per idle task barely depends on worker count: run it at the largest thread count only.
MAX_THREADS_ONLY = {"idle"}

# Conservative resident memory per idle task, used to skip idle sizes that would exhaust RAM.
IDLE_BYTES_PER_TASK_ESTIMATE = {"go": 3_000, "crossbeam": 12_000}
IDLE_BYTES_PER_TASK_DEFAULT = 600  # Tokio builds


# Before each config, wait up to QUIET_WAIT_S for other processes to use under QUIET_CPU_PCT of all CPUs.
# Configs that start noisier than that are listed in the report's notes.
QUIET_CPU_PCT = 10.0
QUIET_WAIT_S = 10.0

# Each run gets an environment variable of random length, so stack/environment layout effects
# average out instead of favouring one implementation (Mytkowicz et al., "Producing wrong data").
ENV_PAD_MAX = 4096


def idle_bytes_estimate(impl: str) -> int:
    return IDLE_BYTES_PER_TASK_ESTIMATE.get(impl.split("+")[0], IDLE_BYTES_PER_TASK_DEFAULT)


def main() -> None:
    args = parse_args()
    profile = PROFILES[args.profile]
    workloads = pick("workload", args.workloads, list(WORKLOAD_PARAMS))
    impls = pick_impls(args.impls)
    threads_list = [int(t) for t in args.threads.split(",")] if args.threads else profile["threads"]
    if len(set(threads_list)) != len(threads_list) or min(threads_list) < 1:
        sys.exit(f"thread counts must be distinct and >= 1: {threads_list}")
    warmup = profile["warmup"] if args.warmup is None else args.warmup
    reps = profile["reps"] if args.reps is None else args.reps
    seed = args.seed if args.seed is not None else random.randrange(1 << 32)

    cpus, physical_cores = cpu_order()
    if max(threads_list) > len(cpus):
        sys.exit(f"asked for {max(threads_list)} threads but only {len(cpus)} CPUs are available")

    if not args.no_build:
        build()
    for impl in impls:
        for workload in workloads:
            resolved = resolve_impl(impl, workload)
            if resolved and not resolved[0].exists():
                sys.exit(f"missing binary {resolved[0]} (run without --no-build)")

    out = Path(args.out) if args.out else ROOT / "results" / f"{args.profile}-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=False)

    meta = collect_meta(args.profile, workloads, impls, threads_list, warmup, reps, seed, cpus, physical_cores, profile)
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    for w in meta["warnings"]:
        print(f"WARNING: {w}", file=sys.stderr)

    configs = []
    for workload in workloads:
        for size in profile["sizes"][workload]:
            for threads in [max(threads_list)] if workload in MAX_THREADS_ONLY else threads_list:
                configs.append((workload, size, threads))

    rng = random.Random(seed)
    with open(out / "raw.jsonl", "a") as raw:
        for n, (workload, size, threads) in enumerate(configs, 1):
            pinned = cpus[:threads]
            print(f"[{n:>2}/{len(configs)}] {workload} size={size:,} threads={threads} cpus={fmt_cpus(pinned)} ", end="", flush=True)
            here = applicable(impls, workload)
            if workload == "idle":
                mem_available = meminfo_kb("MemAvailable") * 1024
                too_big = [i for i in here if size * idle_bytes_estimate(i) > mem_available * 0.8]
                for impl in too_big:
                    rec = base_record(impl, workload, size, threads, pinned)
                    # A deliberate skip, not a failure (and Crossbeam would skip anyway above its thread cap).
                    rec.update(status="skipped", reason="runner: not enough free memory", phase="measure", valid=None)
                    raw.write(json.dumps(rec) + "\n")
                if too_big:
                    print(f"(not enough free memory for {', '.join(too_big)}) ", end="")
                here = [i for i in here if i not in too_big]
            if not here:
                print("-> no implementation applies")
                continue
            conditions = wait_for_quiet()
            if conditions["quiet_wait_s"] or (conditions["background_cpu_pct"] or 0) > QUIET_CPU_PCT:
                print(f"(background CPU {conditions['background_cpu_pct']}%, waited {conditions['quiet_wait_s']}s) ", end="", flush=True)
            results = run_config(workload, size, threads, pinned, here, warmup, reps, rng, raw, args.timeout, conditions)
            cells = [progress_cell(impl, results[impl], workload) for impl in here]
            for i in range(0, len(cells), 3):
                print(("\n       " if i == 0 else "       ") + "   ".join(cells[i:i + 3]))

    report.build(out)
    print(f"\nraw results : {out / 'raw.jsonl'}")
    print(f"summary     : {out / 'summary.md'}")
    print(f"csv         : {out / 'summary.csv'}")
    print(f"charts      : {out / 'report.html'}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", choices=PROFILES, default="smoke")
    p.add_argument("--workloads", help=f"comma list from: {','.join(WORKLOAD_PARAMS)}")
    p.add_argument("--impls", help=f"comma list from {','.join(BINARIES)} (default {','.join(DEFAULT_IMPLS)}); "
                   f"screening builds as tokio+VARIANT[+VARIANT], variants: {','.join(TOKIO_VARIANTS)}")
    p.add_argument("--threads", help="comma list of thread counts, e.g. 1,2,6,12")
    p.add_argument("--warmup", type=int, help="warm-up runs per implementation (overrides profile)")
    p.add_argument("--reps", type=int, help="measured runs per implementation (overrides profile)")
    p.add_argument("--timeout", type=int, default=300, help="per-run timeout in seconds")
    p.add_argument("--seed", type=int, help="seed for the run-order shuffle")
    p.add_argument("--out", help="output directory (default results/<profile>-<timestamp>)")
    p.add_argument("--no-build", action="store_true", help="skip cargo/go builds")
    return p.parse_args()


def pick(kind: str, requested: str | None, available: list[str]) -> list[str]:
    if not requested:
        return available
    chosen = [x.strip() for x in requested.split(",") if x.strip()]
    unknown = [x for x in chosen if x not in available]
    if unknown:
        sys.exit(f"unknown {kind}: {', '.join(unknown)} (choose from {', '.join(available)})")
    return chosen


def pick_impls(requested: str | None) -> list[str]:
    impls = [x.strip() for x in requested.split(",") if x.strip()] if requested else list(DEFAULT_IMPLS)
    if len(set(impls)) != len(impls):
        sys.exit(f"duplicate implementations in --impls: {impls}")
    for impl in impls:
        base, *variants = impl.split("+")
        if base not in BINARIES:
            sys.exit(f"unknown impl {impl!r} (choose from {', '.join(BINARIES)})")
        if variants and base != "tokio":
            sys.exit(f"only tokio has variants: {impl!r}")
        for v in variants:
            if v not in TOKIO_VARIANTS:
                sys.exit(f"unknown tokio variant {v!r} (choose from {', '.join(TOKIO_VARIANTS)})")
    if len(impls) > 8:
        sys.exit("at most 8 implementations per run (the chart palette has 8 colors)")
    return impls


def resolve_impl(impl: str, case: str) -> tuple[Path, list[str]] | None:
    """Binary and --variant list for an impl spec, or None if it doesn't apply to this case."""
    base, *variants = impl.split("+")
    if not variants:
        return BINARIES[base], []
    for v in variants:
        workloads = TOKIO_VARIANTS[v][0]
        if workloads is not None and program_workload(case) not in workloads:
            return None
    binary = TOKIO_VARIANTS_MIMALLOC_BINARY if "mimalloc" in variants else TOKIO_VARIANTS_BINARY
    return binary, [v for v in variants if v != "mimalloc"]


def applicable(impls: list[str], workload: str) -> list[str]:
    return [impl for impl in impls if resolve_impl(impl, workload) is not None]


def build() -> None:
    print("building rust (release, lto=fat) ...", flush=True)
    subprocess.run(["cargo", "build", "--release", "--quiet"], cwd=ROOT / "rust", check=True)
    print("building go ...", flush=True)
    subprocess.run(["go", "build", "-o", "bin/gobench", "."], cwd=ROOT / "go", check=True)


def cpu_order() -> tuple[list[int], int | None]:
    """Usable logical CPUs, ordered so the first N cover N distinct physical cores, and the physical core count."""
    allowed = os.sched_getaffinity(0)
    try:
        out = subprocess.run(["lscpu", "-p=CPU,CORE,SOCKET"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return sorted(allowed), None
    rank: dict[tuple[str, str], int] = {}
    keyed = []
    for line in out.splitlines():
        if not line or line.startswith("#"):
            continue
        cpu, core, socket = line.split(",")
        if int(cpu) not in allowed:
            continue
        r = rank.get((socket, core), 0)
        rank[(socket, core)] = r + 1
        keyed.append((r, int(socket or 0), int(core or 0), int(cpu)))
    return [cpu for *_, cpu in sorted(keyed)], len(rank)


def cpu_busy_pct(interval: float = 0.5) -> float | None:
    """Share of all CPU time that was busy (not idle or iowait) over `interval`, from /proc/stat."""
    def snapshot() -> tuple[int, int]:
        fields = [int(x) for x in (read_text(Path("/proc/stat")) or "").splitlines()[0].split()[1:9]]
        return sum(fields), fields[3] + fields[4]  # user..steal (guest is counted in user); idle + iowait

    try:
        total0, idle0 = snapshot()
        time.sleep(interval)
        total1, idle1 = snapshot()
    except (IndexError, ValueError):
        return None
    total = total1 - total0
    return 100.0 * (total - (idle1 - idle0)) / total if total > 0 else None


def cpu_temp_c() -> float | None:
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        if read_text(hwmon / "name") in ("k10temp", "zenpower", "coretemp", "cpu_thermal"):
            milli = read_text(hwmon / "temp1_input")
            return round(int(milli) / 1000, 1) if milli and milli.isdigit() else None
    return None


def wait_for_quiet() -> dict:
    """Wait briefly for other processes to go quiet; return the conditions this config starts under."""
    started = time.monotonic()
    busy = cpu_busy_pct()
    while busy is not None and busy > QUIET_CPU_PCT and time.monotonic() - started < QUIET_WAIT_S:
        time.sleep(1.0)
        busy = cpu_busy_pct()
    waited = time.monotonic() - started
    return {
        "background_cpu_pct": None if busy is None else round(busy, 1),
        "quiet_wait_s": round(waited, 1) if waited > 1.0 else 0.0,
        "cpu_temp_c": cpu_temp_c(),
    }


def run_config(workload, size, threads, cpus, impls, warmup, reps, rng, raw, timeout, conditions) -> dict[str, list[dict]]:
    active = list(impls)
    measured: dict[str, list[dict]] = {impl: [] for impl in impls}
    for round_no in range(warmup + reps):
        phase = "warmup" if round_no < warmup else "measure"
        order = active[:]
        rng.shuffle(order)
        for impl in order:
            rec = run_one(impl, workload, size, threads, cpus, timeout, rng.randrange(ENV_PAD_MAX + 1))
            rec["phase"] = phase
            rec["round"] = round_no
            rec.update(conditions)
            verify(rec)
            raw.write(json.dumps(rec) + "\n")
            raw.flush()
            measured[impl].append(rec)
            mark = "." if rec["status"] == "ok" and rec["valid"] is not False else "s" if rec["status"] == "skipped" else "x"
            print(mark, end="", flush=True)
            # Skipped, failed or wrong-checksum implementations are not re-run for this config.
            if rec["status"] != "ok" or rec["valid"] is False:
                active.remove(impl)
    return measured


def base_record(impl, workload, size, threads, cpus) -> dict:
    return {
        "impl": impl,
        "workload": workload,
        "program_workload": program_workload(workload),
        "size": size,
        "threads": threads,
        "cpus": cpus,
        "params": WORKLOAD_PARAMS[workload],
    }


def run_one(impl, workload, size, threads, cpus, timeout, env_pad) -> dict:
    binary, variants = resolve_impl(impl, workload)
    cmd = [str(binary), "--workload", program_workload(workload), "--threads", str(threads), "--size", str(size)]
    for key, value in WORKLOAD_PARAMS[workload].items():
        cmd += [f"--{key}", str(value)]
    if variants:
        cmd += ["--variant", ",".join(variants)]
    if shutil.which("taskset"):
        cmd = ["taskset", "-c", ",".join(map(str, cpus))] + cmd
    env = {k: v for k, v in os.environ.items() if k != "GOMAXPROCS"}
    env["BENCH_ENV_PAD"] = "x" * env_pad

    rec = base_record(impl, workload, size, threads, cpus)
    rec["binary"] = binary.name
    rec["variants"] = variants
    rec["env_pad"] = env_pad
    # CPU time of the whole child process (startup included). Runs are sequential, so the delta is this run.
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {**rec, "status": "error", "reason": f"timeout after {timeout}s"}
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    rec["cpu_user_s"] = round(after.ru_utime - before.ru_utime, 4)
    rec["cpu_sys_s"] = round(after.ru_stime - before.ru_stime, 4)
    rec["voluntary_ctx_switches"] = after.ru_nvcsw - before.ru_nvcsw
    rec["involuntary_ctx_switches"] = after.ru_nivcsw - before.ru_nivcsw
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    if proc.returncode != 0 or not lines:
        tail = (proc.stderr.strip() or proc.stdout.strip())[-300:]
        return {**rec, "status": "error", "reason": f"exit {proc.returncode}: {tail}"}
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {**rec, "status": "error", "reason": f"bad output: {lines[-1][:200]}"}
    # The runner's fields overwrite the binary's below, so first make sure the binary ran what was asked.
    reported = (result.get("workload"), result.get("threads"), result.get("size"))
    if reported != (program_workload(workload), threads, size):
        return {**rec, "status": "error", "reason": f"binary reported workload/threads/size {reported}"}
    echoed = result.get("params") or {}
    mismatched = {k: echoed.get(k) for k, v in WORKLOAD_PARAMS[workload].items() if echoed.get(k) != v}
    if mismatched:
        return {**rec, "status": "error", "reason": f"binary ran with different parameters: {mismatched}"}
    # rec's "params" (what was requested) overwrites the binary's; keep what it reported alongside.
    return {**result, "reported_params": echoed, **rec}


def cpu_checksum(size: int, tasks: int, rounds: int) -> int | None:
    """Wrapping sum of splitmix64 applied `rounds` times to 0..size-1, if numpy is available.

    Chunking doesn't change a wrapping sum, so `tasks` is irrelevant here; it is kept for the cache key.
    """
    key = (size, tasks, rounds)
    if key in _CPU_CHECKSUMS:
        return _CPU_CHECKSUMS[key]
    try:
        import numpy as np
    except ImportError:
        return None
    total = 0
    with np.errstate(over="ignore"):
        for lo in range(0, size, 1 << 20):
            z = np.arange(lo, min(size, lo + (1 << 20)), dtype=np.uint64)
            for _ in range(rounds):
                z = z + np.uint64(0x9E3779B97F4A7C15)
                z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
                z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
                z = z ^ (z >> np.uint64(31))
            total = (total + int(z.sum(dtype=np.uint64))) % U64
    _CPU_CHECKSUMS[key] = total
    return total


_CPU_CHECKSUMS: dict[tuple[int, int, int], int] = {}


def expected_checksum(workload: str, size: int, params: dict) -> int | None:
    def triangle(k: int) -> int:  # sum of 0..k-1
        return (k * (k - 1) // 2) % U64

    match workload:
        case "spsc" | "spawn":
            return triangle(size)
        case "mpmc":
            return triangle(size // params["producers"] * params["producers"])
        case "pingpong":
            return (2 * size) % U64
        case "select":
            return triangle(size // 2 * 2)
        case "mutex":
            return size // params["workers"] * params["workers"]
        case "idle":
            return size
        case "cpu":
            # No closed form; computed with numpy, or None when numpy is missing.
            return cpu_checksum(size, params["tasks"], params["rounds"])
    return None


def verify(rec: dict) -> None:
    if rec["status"] != "ok":
        rec["valid"] = None
        return
    expected = expected_checksum(program_workload(rec["workload"]), rec["size"], rec["params"])
    if expected is None:
        # Can't compute it here (cpu without numpy). Leave the run unverified; report.py accepts the checksum
        # most implementations agree on and rejects the rest, instead of trusting whichever ran first.
        rec["valid"] = None
        return
    rec["expected_checksum"] = expected
    rec["valid"] = rec["checksum"] == expected
    if not rec["valid"]:
        rec["reason"] = f"checksum {rec['checksum']} != {expected}"
        print(f"\n  !! {rec['impl']} {rec['workload']}: {rec['reason']}", file=sys.stderr)


def progress_cell(impl: str, recs: list[dict], workload: str) -> str:
    ok = [r for r in recs if r["phase"] == "measure" and r["status"] == "ok" and r["valid"] is not False]
    if not ok:
        bad = next((r for r in recs if r["status"] != "ok" or r["valid"] is False), None)
        return f"{impl} {bad['status'] if bad else 'no data'}"
    if workload == "idle":
        return f"{impl} {report.fmt_bytes(statistics.median(r['bytes_per_task'] for r in ok))}/task"
    values = [r["ops_per_sec"] for r in ok]
    cv = report.cv_pct(values)
    return f"{impl} {report.fmt_si(statistics.median(values))}/s ±{cv:.1f}%"


def fmt_cpus(cpus: list[int]) -> str:
    return ",".join(map(str, cpus))


def collect_meta(profile_name, workloads, impls, threads_list, warmup, reps, seed, cpus, physical_cores, profile) -> dict:
    warnings = []
    cpu_root = Path("/sys/devices/system/cpu")
    governors = sorted({read_text(p) for p in cpu_root.glob("cpu[0-9]*/cpufreq/scaling_governor")} - {None})
    epps = sorted({read_text(p) for p in cpu_root.glob("cpu[0-9]*/cpufreq/energy_performance_preference")} - {None})
    if governors and governors != ["performance"]:
        warnings.append(
            f"CPU governor is '{', '.join(governors)}', not 'performance', so frequency scaling adds noise. "
            "Fix: echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
        )

    on_ac = None
    for supply in Path("/sys/class/power_supply").glob("*"):
        kind = read_text(supply / "type")
        if kind == "Mains":
            on_ac = read_text(supply / "online") == "1"
        elif kind == "Battery" and supply.name.startswith("BAT") and on_ac is None:
            # Some laptops expose no Mains supply; a discharging system battery means no charger.
            status = read_text(supply / "status")
            if status is not None:
                on_ac = status != "Discharging"
    if on_ac is False:
        warnings.append("Running on battery; plug in the charger for stable CPU frequency.")

    load1 = os.getloadavg()[0]
    if load1 > 1.0:
        warnings.append(f"1-minute load average was {load1:.2f} at start; other programs compete for CPU.")

    if not shutil.which("taskset"):
        warnings.append("taskset not found; runs are NOT pinned to a CPU subset, so thread counts are not comparable.")
    if not shutil.which("lscpu"):
        warnings.append("lscpu not found; CPUs are used in numeric order, which may pin two threads to one physical core.")

    lock = read_text(ROOT / "rust/Cargo.lock") or ""
    crate_names = "tokio|crossbeam|crossbeam-channel|crossbeam-deque|async-channel|parking_lot|kanal|flume|mimalloc"
    crates = dict(re.findall(rf'name = "({crate_names})"\nversion = "([^"]+)"', lock))

    commit = git_output(["rev-parse", "HEAD"])
    dirty = bool(git_output(["status", "--porcelain", "--untracked-files=no"]))
    if dirty:
        warnings.append("Working tree has uncommitted changes; git_commit in meta.json does not fully describe the code.")

    return {
        "profile": profile_name,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "workloads": workloads,
        "impls": impls,
        "threads": threads_list,
        "sizes": {w: profile["sizes"][w] for w in workloads},
        "params": {w: WORKLOAD_PARAMS[w] for w in workloads},
        "warmup": warmup,
        "reps": reps,
        "seed": seed,
        "cpu_order": cpus,
        "physical_cores": physical_cores,
        "cpu_model": lscpu_field("Model name"),
        "logical_cpus": len(cpus),
        "kernel": platform.release(),
        "governors": governors,
        "energy_performance_preference": epps,
        "on_ac_power": on_ac,
        "load_avg_1m": round(load1, 2),
        "cpu_temp_c_at_start": cpu_temp_c(),
        "quiet_cpu_pct": QUIET_CPU_PCT,
        "mem_total_kb": meminfo_kb("MemTotal"),
        "mem_available_kb": meminfo_kb("MemAvailable"),
        "rustc": tool_version(["rustc", "--version"]),
        "go": tool_version(["go", "version"]),
        "crates": crates,
        "git_commit": commit,
        "git_dirty": dirty,
        "variant_help": variant_help(impls),
        "warnings": warnings,
    }


def variant_help(impls: list[str]) -> dict[str, str]:
    used = {v for impl in impls for v in impl.split("+")[1:]}
    return {v: TOKIO_VARIANTS[v][1] for v in TOKIO_VARIANTS if v in used}


def git_output(args: list[str]) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def meminfo_kb(field: str) -> int:
    for line in (read_text(Path("/proc/meminfo")) or "").splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1])
    return 0


def lscpu_field(name: str) -> str | None:
    try:
        out = subprocess.run(["lscpu"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in out.splitlines():
        if line.startswith(name + ":"):
            return line.split(":", 1)[1].strip()
    return None


def tool_version(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


if __name__ == "__main__":
    main()
