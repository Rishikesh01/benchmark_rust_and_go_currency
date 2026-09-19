#!/usr/bin/env python3
"""Records one perf profile per implementation and test case and renders each as a flame graph.

Runs each test once with the `full` profile's sizes, pinned like run.py, under `perf record`. The Rust binaries
are rebuilt with frame pointers (DWARF unwinding lost about half the stacks); Go has them already. The whole
process is profiled, startup and untimed passes included. Kernel frames end in `_[k]`.

Needs perf (`sudo apt install linux-tools-generic`), inferno and rustfilt (`cargo install inferno rustfilt`),
and for kernel frames: sudo sysctl kernel.perf_event_paranoid=1 kernel.kptr_restrict=0

Writes results/flame-<timestamp>/: one SVG per test, index.md linking them, meta.json.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import report
import run

FREQ = 9999  # samples/s per CPU, so even the shortest tests get 1,500+ samples; odd, so it misses timer ticks
DEFAULT_IMPLS = ["tokio", "tokio-tuned", "crossbeam", "go"]
SKIP = {"idle"}  # idle tasks only sleep; there's nothing to profile
RUST_RELEASE = run.ROOT / "rust/target/release"
FP_TARGET = run.ROOT / "rust/target/frame-pointers"


def main() -> None:
    args = parse_args()
    impls = run.pick_impls(args.impls or ",".join(DEFAULT_IMPLS))
    workloads = run.pick("workload", args.workloads, [w for w in run.WORKLOAD_PARAMS if w not in SKIP])
    threads_list = [int(t) for t in args.threads.split(",")]
    perf = find_perf()
    for tool in ("inferno-collapse-perf", "inferno-flamegraph", "rustfilt"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found: cargo install inferno rustfilt")
    paranoid = int(Path("/proc/sys/kernel/perf_event_paranoid").read_text())
    if paranoid > 2:
        sys.exit(f"perf is disabled (kernel.perf_event_paranoid={paranoid}): "
                 "sudo sysctl kernel.perf_event_paranoid=1 kernel.kptr_restrict=0")
    user_only = paranoid == 2
    if user_only or run.read_text(Path("/proc/sys/kernel/kptr_restrict")) != "0":
        print("WARNING: kernel frames will be missing or unnamed; "
              "sudo sysctl kernel.perf_event_paranoid=1 kernel.kptr_restrict=0", file=sys.stderr)

    cpus, physical_cores = run.cpu_order()
    if max(threads_list) > len(cpus):
        sys.exit(f"asked for {max(threads_list)} threads but only {len(cpus)} CPUs are available")
    if not args.no_build:
        build()

    out = Path(args.out) if args.out else run.ROOT / "results" / f"flame-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=False)
    profile = run.PROFILES["full"]
    meta = run.collect_meta("full", workloads, impls, threads_list, 0, 1, None, cpus, physical_cores, profile)
    meta.update(perf=run.tool_version([perf, "--version"]), sample_hz=FREQ, kernel_frames=not user_only,
                rustflags="-C force-frame-pointers=yes")
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    for w in meta["warnings"]:
        print(f"WARNING: {w}", file=sys.stderr)

    graphs: dict[tuple[str, int, str], str] = {}
    for threads in threads_list:
        for workload in workloads:
            for impl in run.applicable(impls, workload):
                print(f"{workload} {impl} threads={threads} ... ", end="", flush=True)
                svg = f"{workload}-{impl}-{threads}t.svg"
                note = profile_one(perf, impl, workload, threads, cpus[:threads], out / svg, user_only)
                print(note)
                if (out / svg).exists():
                    graphs[(workload, threads, impl)] = svg

    (out / "index.md").write_text(render_index(meta, workloads, impls, threads_list, graphs))
    print(f"\nflame graphs: {out / 'index.md'}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workloads", help=f"comma list from: {','.join(w for w in run.WORKLOAD_PARAMS if w not in SKIP)}")
    p.add_argument("--impls", help=f"comma list (default {','.join(DEFAULT_IMPLS)})")
    p.add_argument("--threads", default="12", help="comma list of thread counts (default 12)")
    p.add_argument("--out", help="output directory (default results/flame-<timestamp>)")
    p.add_argument("--no-build", action="store_true", help="skip cargo/go builds")
    return p.parse_args()


def build() -> None:
    print("building rust (release, frame pointers) ...", flush=True)
    rustflags = (os.environ.get("RUSTFLAGS", "") + " -C force-frame-pointers=yes").strip()
    env = {**os.environ, "RUSTFLAGS": rustflags, "CARGO_TARGET_DIR": str(FP_TARGET)}
    subprocess.run(["cargo", "build", "--release", "--quiet"], cwd=run.ROOT / "rust", env=env, check=True)
    print("building go ...", flush=True)
    subprocess.run(["go", "build", "-o", "bin/gobench", "."], cwd=run.ROOT / "go", check=True)


def find_perf() -> str:
    """A perf that runs. Ubuntu's /usr/bin/perf refuses to start without linux-tools for the exact running
    kernel, but the perf from any installed linux-tools works."""
    candidates = [shutil.which("perf"), *sorted(glob.glob("/usr/lib/linux-tools*/*/perf") + glob.glob("/usr/lib/linux-tools-*/perf"))]
    for perf in filter(None, candidates):
        if subprocess.run([perf, "--version"], capture_output=True).returncode == 0:
            return perf
    sys.exit("perf not found: sudo apt install linux-tools-generic")


def fp_binary(impl: str, workload: str) -> Path:
    """The frame-pointer build of a Rust binary; Go's binary as is."""
    binary = run.resolve_impl(impl, workload)[0]
    return FP_TARGET / "release" / binary.name if binary.is_relative_to(RUST_RELEASE) else binary


def profile_one(perf, impl, workload, threads, cpus, svg: Path, user_only: bool) -> str:
    """Profiles the largest `full` size the implementation runs and writes the flame graph; returns a status note."""
    binary = fp_binary(impl, workload)
    if not binary.exists():
        return f"failed: missing {binary} (run without --no-build)"
    env = {k: v for k, v in os.environ.items() if k != "GOMAXPROCS"}
    for size in sorted(run.PROFILES["full"]["sizes"][workload], reverse=True):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "perf.data"
            cmd = [perf, "record", "-F", str(FREQ), "--call-graph", "fp", "-o", str(data)]
            cmd += ["--all-user"] if user_only else []
            cmd += ["--", *run.bench_command(impl, workload, size, threads, cpus, binary)]
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            lines = [l for l in proc.stdout.splitlines() if l.strip()]
            try:
                result = json.loads(lines[-1])
            except (IndexError, json.JSONDecodeError):
                result = {}
            if proc.returncode != 0 or result.get("status") not in ("ok", "skipped"):
                return f"failed: {(proc.stderr.strip() or proc.stdout.strip())[-300:]}"
            if result["status"] == "skipped":
                continue
            samples = int(m[1]) if (m := re.search(r"\((\d+) samples\)", proc.stderr)) else 0
            label = report.ROW_LABELS[workload].format(size=report.fmt_count(size), **run.WORKLOAD_PARAMS[workload])
            render(perf, data, svg, f"{report.display_name(impl)}: {label}",
                   f"{threads} threads, size {report.fmt_count(size)}, {samples:,} samples")
            return f"{samples:,} samples"
    return "skipped"


def render(perf, data: Path, svg: Path, title: str, subtitle: str) -> None:
    """perf script | rustfilt | inferno-collapse-perf | inferno-flamegraph. Frame widths are CPU cycles."""
    script = subprocess.Popen([perf, "script", "-i", str(data)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    demangle = subprocess.Popen(["rustfilt"], stdin=script.stdout, stdout=subprocess.PIPE)
    script.stdout.close()
    collapse = subprocess.Popen(["inferno-collapse-perf", "--kernel"], stdin=demangle.stdout, stdout=subprocess.PIPE)
    demangle.stdout.close()
    with open(svg, "w") as f:
        subprocess.run(["inferno-flamegraph", "--hash", "--countname", "cycles", "--title", title, "--subtitle", subtitle],
                       stdin=collapse.stdout, stdout=f, check=True)
    collapse.stdout.close()
    if script.wait() or demangle.wait() or collapse.wait():
        raise RuntimeError(f"perf script, rustfilt or inferno-collapse-perf failed for {data}")


def render_index(meta, workloads, impls, threads_list, graphs) -> str:
    commit = (meta["git_commit"] or "unknown")[:7] + (" (uncommitted changes)" if meta["git_dirty"] else "")
    lines = [
        "# Flame graphs",
        "",
        f"One `perf record` at {FREQ} Hz per test, `full` sizes, recorded {meta['started_at'][:10]} at commit {commit}. "
        "Whole process, startup and untimed passes included. Frame width is CPU cycles; kernel frames end in `_[k]`. "
        "Rust is built with frame pointers for complete stacks.",
    ]
    for threads in threads_list:
        lines += ["", f"## {threads} threads", "",
                  "| Test | " + " | ".join(report.display_name(i) for i in impls) + " |",
                  "|---|" + "---|" * len(impls)]
        for workload in workloads:
            # Spawn's size differs between implementations (Crossbeam can't start 1M threads); each SVG names its own.
            label = "Spawn and join" if workload == "spawn" else report.ROW_LABELS[workload].format(**run.WORKLOAD_PARAMS[workload])
            cells = [f"[svg]({graphs[(workload, threads, i)]})" if (workload, threads, i) in graphs else "—" for i in impls]
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
