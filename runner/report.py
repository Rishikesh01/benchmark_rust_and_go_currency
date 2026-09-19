#!/usr/bin/env python3
"""Summarises a results directory into summary.csv, summary.md and report.html.

Usage: python3 runner/report.py results/<run-dir>
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from math import comb
from pathlib import Path

CV_WARN_PCT = 5.0

WORKLOAD_ORDER = ["spsc", "spsc-cap1", "mpsc", "mpsc-cap1", "mpmc", "mpmc-cap1", "pingpong", "spawn", "cpu", "select", "select-cap1", "mutex", "idle"]
WORKLOAD_INFO = {
    "spsc": ("One sender, one receiver", "Raw message rate through a bounded channel of capacity {capacity}.", "messages/s"),
    "spsc-cap1": ("One sender, one receiver, capacity 1",
                  "The same test with a channel of capacity {capacity}, so nearly every message is a hand-off between tasks.", "messages/s"),
    "mpsc": ("Many senders, one receiver", "{producers} senders and one receiver sharing a bounded channel of capacity {capacity}.", "messages/s"),
    "mpsc-cap1": ("Many senders, one receiver, capacity 1",
                  "{producers} senders and one receiver sharing a channel of capacity {capacity}.", "messages/s"),
    "mpmc": ("Many senders, many receivers", "{producers} senders and {consumers} receivers sharing one bounded channel of capacity {capacity}.", "messages/s"),
    "mpmc-cap1": ("Many senders, many receivers, capacity 1",
                  "{producers} senders and {consumers} receivers sharing one channel of capacity {capacity}.", "messages/s"),
    "pingpong": ("Ping-pong", "Two tasks pass one token back and forth over capacity-1 channels; measures wake-up cost.", "round trips/s"),
    "spawn": ("Spawn and join", "Start tasks that each return a number, then wait for all of them.", "tasks/s"),
    "cpu": ("CPU-heavy parallel work", "Hash items with splitmix64 ({rounds} rounds each), split into {tasks} chunks.", "items/s"),
    "select": ("Select", "One consumer waits on two channels of capacity {capacity} at once until both close.", "messages/s"),
    "select-cap1": ("Select, capacity 1", "The same select test with both channels at capacity {capacity}.", "messages/s"),
    "mutex": ("Lock contention", "{workers} workers increment one shared counter under a mutex.", "increments/s"),
    "idle": ("Memory per idle task", "Resident memory added per task parked on a channel or semaphore.", "bytes/task"),
}


def load(out_dir: Path) -> tuple[dict, list[dict]]:
    """A results directory's meta.json and the summary of its raw.jsonl."""
    out_dir = Path(out_dir)
    meta = json.loads((out_dir / "meta.json").read_text())
    rows = [json.loads(l) for l in (out_dir / "raw.jsonl").read_text().splitlines() if l.strip()]
    return meta, summarise(rows, meta["impls"], meta["reps"])


def build(out_dir: Path) -> None:
    out_dir = Path(out_dir)
    meta, summary = load(out_dir)
    write_csv(out_dir / "summary.csv", summary)
    (out_dir / "summary.md").write_text(render_markdown(meta, summary))
    (out_dir / "report.html").write_text(render_html(meta, summary))


def resolve_unverified(rows: list[dict]) -> None:
    """Settle runs the runner couldn't verify (cpu checksums without numpy) by majority across implementations.

    The checksum reported by more than half of the implementations in a case is accepted; runs with any other
    checksum are invalid. Without a majority, every run in the case is invalid.
    """
    cases: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["status"] == "ok" and r.get("valid") is None:
            cases.setdefault((r["workload"], r["size"], json.dumps(r.get("params"), sort_keys=True)), []).append(r)
    for recs in cases.values():
        impls_by_checksum: dict[int, set[str]] = {}
        for r in recs:
            impls_by_checksum.setdefault(r["checksum"], set()).add(r["impl"])
        checksum, impls = max(impls_by_checksum.items(), key=lambda item: len(item[1]))
        majority = len(impls) > len({r["impl"] for r in recs}) / 2
        for r in recs:
            r["valid"] = majority and r["checksum"] == checksum
            if not r["valid"]:
                r["reason"] = "checksum disagrees with the other implementations"


def summarise(rows: list[dict], impl_order: list[str], reps: int) -> list[dict]:
    resolve_unverified(rows)
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["workload"], r["size"], r["threads"], r["impl"]), []).append(r)

    summary = []
    for (workload, size, threads, impl), recs in groups.items():
        ok = [r for r in recs if r["phase"] == "measure" and r["status"] == "ok" and r["valid"]]
        bad = next((r for r in recs if r["status"] != "ok" or r.get("valid") is False), None)
        if any(r.get("valid") is False for r in recs):
            status = "invalid"  # one wrong checksum discredits every run of this implementation here
        elif not ok:
            status = bad["status"] if bad else "no data"
        elif len(ok) < reps:
            status = "partial"  # some measured runs failed; the median covers only the ones that succeeded
        else:
            status = "ok"
        s = {
            "workload": workload,
            "size": size,
            "threads": threads,
            "impl": impl,
            "params": recs[0].get("params", {}),
            "variants": recs[0].get("variants", []),
            "runs": len(ok),
            "expected_runs": reps,
            "status": status,
            "reason": bad.get("reason") if bad else None,
        }
        if ok and status != "invalid":
            ops = [r["ops_per_sec"] for r in ok]
            s.update(
                ops_median=statistics.median(ops),
                ops_min=min(ops),
                ops_max=max(ops),
                cv_pct=cv_pct(ops),
                wall_ms_median=statistics.median(r["wall_ns"] for r in ok) / 1e6,
                peak_rss_kb_median=median_of(ok, "peak_rss_kb"),
                lat_p50_ns=median_of(ok, "lat_p50_ns"),
                lat_p99_ns=median_of(ok, "lat_p99_ns"),
                lat_p999_ns=median_of(ok, "lat_p999_ns"),
                bytes_per_task=median_of(ok, "bytes_per_task"),
            )
            if workload == "idle":
                s["cv_pct"] = cv_pct([r["bytes_per_task"] for r in ok])
            for prefix, key in CI_FIELDS.items():
                s[f"{prefix}_ci"] = median_ci([r[key] for r in ok if r.get(key) is not None])
            conditions = [r["background_cpu_pct"] for r in ok if r.get("background_cpu_pct") is not None]
            s["background_cpu_pct_max"] = max(conditions) if conditions else None
            temps = [r["cpu_temp_c"] for r in ok if r.get("cpu_temp_c") is not None]
            s["cpu_temp_c_max"] = max(temps) if temps else None
            # Whole-process CPU time (user + sys), recorded by run.py since the CPU-time change.
            timed = [r for r in ok if r.get("cpu_user_s") is not None]
            if timed:
                cpu = [r["cpu_user_s"] + r["cpu_sys_s"] for r in timed]
                s["cpu_s_median"] = statistics.median(cpu)
                s["ops_per_cpu_s"] = statistics.median(r["ops"] / c for r, c in zip(timed, cpu) if c > 0)
        summary.append(s)

    def sort_key(s):
        impl_rank = impl_order.index(s["impl"]) if s["impl"] in impl_order else len(impl_order)
        return (workload_rank(s["workload"]), s["size"], s["threads"], impl_rank)

    return sorted(summary, key=sort_key)


def workload_rank(w: str) -> int:
    return WORKLOAD_ORDER.index(w) if w in WORKLOAD_ORDER else len(WORKLOAD_ORDER)


# Per-run fields that get a confidence interval for their median: summary prefix -> raw.jsonl key.
CI_FIELDS = {"ops": "ops_per_sec", "bytes": "bytes_per_task", "lat_p50": "lat_p50_ns", "lat_p99": "lat_p99_ns"}
# Table value key -> CI prefix.
CI_OF = {"ops_median": "ops", "bytes_per_task": "bytes", "lat_p50_ns": "lat_p50", "lat_p99_ns": "lat_p99"}


def median_ci(values: list[float], confidence: float = 0.95) -> tuple[float, float, float] | None:
    """Distribution-free confidence interval for the median from order statistics.

    Returns (low, high, coverage). The interval [x(j), x(n-j+1)] covers the true median with probability
    1 - 2 * P(Binomial(n, 1/2) <= j-1); j is the largest value keeping that at or above `confidence`.
    With fewer than 6 runs no interval reaches 95%, so it falls back to [min, max] and reports its coverage.
    """
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return None
    if n == 1:
        return xs[0], xs[0], 0.0
    j, tail = 1, 2.0 ** -n  # tail = P(X <= j-1)
    while j < n // 2:
        next_tail = tail + comb(n, j) / 2 ** n
        if next_tail > (1 - confidence) / 2:
            break
        j, tail = j + 1, next_tail
    return xs[j - 1], xs[n - j], 1 - 2 * tail


def median_of(recs: list[dict], key: str):
    values = [r[key] for r in recs if r.get(key) is not None]
    return statistics.median(values) if values else None


def cv_pct(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    return statistics.stdev(values) / mean * 100 if mean else 0.0


# ---------------------------------------------------------------- formatting

def sig3(x: float) -> str:
    """Three significant digits, keeping trailing zeros (4.00, 27.0, 115)."""
    x = float(f"{x:.3g}")
    if x == 0:
        return "0"
    return f"{x:.0f}" if abs(x) >= 100 else f"{x:.1f}" if abs(x) >= 10 else f"{x:.2f}"


def fmt_si(v: float | None) -> str:
    if v is None:
        return "-"
    v = float(f"{v:.3g}")  # round first so 999.6K becomes 1.00M, not 1000K
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{sig3(v / div)}{suffix}"
    return sig3(v)


def fmt_ns(v: float | None) -> str:
    if v is None:
        return "-"
    v = float(f"{v:.3g}")
    for div, unit in ((1e9, "s"), (1e6, "ms"), (1e3, "µs")):
        if v >= div:
            return f"{sig3(v / div)} {unit}"
    return f"{v:.0f} ns"


def fmt_count(n: int) -> str:
    """Compact run size for labels: 10K, 100K, 1M."""
    n = float(f"{n:.3g}")
    for div, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= div:
            return f"{n / div:.3g}{suffix}"
    return f"{n:.0f}"


def fmt_bytes(v: float | None) -> str:
    if v is None:
        return "-"
    units = ((1 << 30, "GiB"), (1 << 20, "MiB"), (1 << 10, "KiB"), (1, "B"))
    for i, (div, unit) in enumerate(units):
        if v >= div or div == 1:
            # Round after scaling (binary units), and step up a unit if rounding reaches 1000.
            if i > 0 and float(f"{v / div:.3g}") >= 1000:
                div, unit = units[i - 1]
            return f"{v:.0f} B" if div == 1 else f"{sig3(v / div)} {unit}"
    return "-"


def describe(workload: str, params: dict) -> tuple[str, str, str]:
    title, blurb, unit = WORKLOAD_INFO.get(workload, (workload, "", "ops/s"))
    return title, blurb.format(**params) if params else blurb, unit


# ---------------------------------------------------------------- csv

CSV_FIELDS = [
    "workload", "size", "threads", "impl", "status", "runs", "expected_runs", "ops_median", "ops_min", "ops_max",
    "cv_pct", "ops_ci_low", "ops_ci_high", "wall_ms_median", "cpu_s_median", "ops_per_cpu_s", "lat_p50_ns", "lat_p99_ns", "lat_p999_ns",
    "bytes_per_task", "peak_rss_kb_median", "reason",
]


def write_csv(path: Path, summary: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for s in summary:
            ci = s.get("ops_ci")
            w.writerow({**s, "ops_ci_low": ci[0] if ci else None, "ops_ci_high": ci[1] if ci else None})


# ---------------------------------------------------------------- markdown

DISPLAY_NAMES = {"tokio": "Tokio", "tokio-tuned": "Tuned Tokio", "tokio-tuned-tokio-channels": "Tuned Tokio, Tokio channels",
                 "crossbeam": "Crossbeam", "go": "Go"}

# Test names in the summary table. {size} is the compact run size; other fields are the case parameters.
ROW_LABELS = {
    "spsc": "1 sender → 1 receiver, capacity {capacity}",
    "spsc-cap1": "1 sender → 1 receiver, capacity {capacity}",
    "mpsc": "{producers} senders → 1 receiver, capacity {capacity}",
    "mpsc-cap1": "{producers} senders → 1 receiver, capacity {capacity}",
    "mpmc": "{producers} senders → {consumers} receivers, capacity {capacity}",
    "mpmc-cap1": "{producers} senders → {consumers} receivers, capacity {capacity}",
    "pingpong": "Ping-pong",
    "spawn": "Spawn and join, {size} tasks",
    "cpu": "CPU-heavy hashing",
    "select": "Select over 2 channels, capacity {capacity}",
    "select-cap1": "Select over 2 channels, capacity {capacity}",
    "mutex": "Lock contention, {workers} workers",
    "idle": "Memory per idle task, {size} tasks",
}


# Result tables, in order: (title, note, workloads). Channel tests are split by channel type so each table compares
# like with like; the last section (None) takes every other workload.
TABLE_SECTIONS = [
    ("MPMC channels",
     "Every implementation uses a bounded multi-producer, multi-consumer channel: async-channel (Tokio), "
     "kanal (tuned Tokio), crossbeam-channel and Go `chan`.",
     {"mpmc", "mpmc-cap1"}),
    ("Single-receiver channels",
     "One receiver per channel. Tokio uses its MPSC channel, `tokio::sync::mpsc` (so does tuned Tokio for select); "
     "tuned Tokio otherwise uses kanal, and Crossbeam and Go use their MPMC channels with a single receiver. "
     "Tuned Tokio, Tokio channels is tuned Tokio with `tokio::sync::mpsc` instead of kanal.",
     {"spsc", "spsc-cap1", "mpsc", "mpsc-cap1", "pingpong", "select", "select-cap1"}),
    ("Tasks, CPU, locks and memory", "", None),
]


def concurrency(workload: str, params: dict, size: int, threads: int) -> tuple[str, str]:
    """(Tokio tasks or Go goroutines, Crossbeam OS threads) doing a test's work, not counting the one that starts
    the test and waits for it."""
    if workload == "cpu":
        return fmt_count(params["tasks"]), str(threads)
    if workload in ("spawn", "idle"):
        return fmt_count(size), fmt_count(size)
    n = {"spsc": 2, "spsc-cap1": 2, "pingpong": 2, "select": 3, "select-cap1": 3}.get(workload)
    if workload in ("mpmc", "mpmc-cap1"):
        n = params["producers"] + params["consumers"]
    elif workload in ("mpsc", "mpsc-cap1"):
        n = params["producers"] + 1
    elif workload == "mutex":
        n = params["workers"]
    return (str(n), str(n)) if n is not None else ("", "")


def concurrency_blurb(workload: str, params: dict) -> str:
    """One sentence for the HTML report saying what runs the test."""
    if workload == "cpu":
        return (f"Runs as {params['tasks']} Tokio tasks or goroutines; Crossbeam uses one OS thread per pinned CPU, "
                f"sharing the {params['tasks']} chunks.")
    if workload in ("spawn", "idle"):
        return "One Tokio task, goroutine or Crossbeam OS thread per item."
    n = concurrency(workload, params, 0, 0)[0]
    return f"Runs as {n} Tokio tasks, {n} goroutines or {n} Crossbeam OS threads." if n else ""


def count_columns(impls: list[str]) -> list[str]:
    """Headers of the task and OS-thread count columns that apply to these implementations."""
    bases = {impl.split("+")[0] for impl in impls}
    task_owners = (["Tokio"] if any(b.startswith("tokio") for b in bases) else []) + (["Go"] if "go" in bases else [])
    cols = []
    if task_owners:
        cols.append("/".join(task_owners) + " tasks")
    if "crossbeam" in bases:
        cols.append("Crossbeam threads")
    return cols


def count_cells(impls: list[str], spec: tuple, threads: int) -> list[str]:
    workload, by_threads = spec[0], spec[-1]
    first = next(iter(by_threads.values()))[0]
    tasks, os_threads = concurrency(workload, first["params"], first["size"], threads)
    if any(r["impl"] == "crossbeam" and r["status"] not in SHOWN_STATUSES for r in by_threads.get(threads, [])):
        os_threads = "—"
    cols = count_columns(impls)
    return ([tasks] if any(c.endswith("tasks") for c in cols) else []) + (
        [os_threads] if "Crossbeam threads" in cols else [])


def section_impls(impls: list[str], section: list[tuple]) -> list[str]:
    """Implementations with a result anywhere in a table section; the others would be a column of dashes."""
    present = {r["impl"] for spec in section for rows in spec[-1].values() for r in rows}
    return [i for i in impls if i in present]


def sectioned(specs: list[tuple]) -> list[tuple[str, str, list[tuple]]]:
    """Split table specs into TABLE_SECTIONS, dropping empty sections."""
    named = set().union(*(w for _, _, w in TABLE_SECTIONS if w))
    out = []
    for title, note, workloads in TABLE_SECTIONS:
        chosen = [spec for spec in specs if (spec[0] in workloads if workloads else spec[0] not in named)]
        if chosen:
            out.append((title, note, chosen))
    return out


def render_markdown(meta: dict, summary: list[dict]) -> str:
    impls = display_order(meta["impls"])
    specs = table_specs(summary)
    threads = sorted({s["threads"] for s in summary})
    top = threads[-1] if threads else 0

    bases = list(dict.fromkeys(impl.split("+")[0] for impl in impls))
    title = " vs ".join(DISPLAY_NAMES.get(b, b) for b in bases)
    warmups = f"{meta['warmup']} warm-up{'' if meta['warmup'] == 1 else 's'}"
    coverage = (median_ci(list(range(meta["reps"]))) or (0, 0, 0))[2]
    out = [
        f"# {title}",
        "",
        f"Median of {meta['reps']} runs after {warmups} (profile `{meta['profile']}`, started {meta['started_at']}). "
        f"**Bold** marks a clear best: its {coverage:.0%} confidence interval for the median doesn't overlap the "
        "next best's. No bold means no clear winner. "
        f"⚠ means the runs varied by more than {CV_WARN_PCT:.0f}%; (n/{meta['reps']}) means only n runs succeeded. "
        "Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.",
    ]
    out += [
        "",
        "Threads = N: pinned to N CPUs; Tokio has N worker threads, Go has `GOMAXPROCS=N`. Crossbeam runs the OS "
        "threads in its column on those CPUs. Throughput is the whole test's total, not per thread or task. Latency "
        "is per round trip, memory per idle task.",
    ]
    if meta.get("physical_cores"):
        p = meta["physical_cores"]
        out += ["", f"Up to {p} threads, each thread has its own physical core; above {p}, threads share cores (SMT)."]
    if meta["warnings"]:
        out += ["", "⚠ Run conditions: " + " ".join(w.split(". Fix:")[0].rstrip(".") + "." for w in meta["warnings"])]

    out += ["", f"## At {top} threads"]
    for title, note, section in sectioned(specs):
        rows = [spec for spec in section if top in spec[-1]]
        if not rows:
            continue
        out += ["", f"### {title}", ""] + ([note, ""] if note else [])
        cols = section_impls(impls, section)
        counts = count_columns(cols)
        out += [md_row(["Test"] + counts + [display_name(i) for i in cols] + ["Unit"]),
                md_row(["---"] + ["---:"] * (len(counts) + len(cols)) + ["---"])]
        for spec in rows:
            _, label, unit, key, fmt, lower_better, by_threads = spec
            out.append(md_row([label] + count_cells(cols, spec, top)
                              + table_cells(cols, by_threads[top], key, fmt, lower_better) + [unit]))

    if len(threads) > 1:
        out += ["", "## All thread counts"]
        for title, _, section in sectioned(specs):
            cols = section_impls(impls, section)
            counts = count_columns(cols)
            out += ["", f"### {title}", "",
                    md_row(["Test", "Threads"] + counts + [display_name(i) for i in cols] + ["Unit"]),
                    md_row(["---", "---:"] + ["---:"] * (len(counts) + len(cols)) + ["---"])]
            for spec in section:
                _, label, unit, key, fmt, lower_better, by_threads = spec
                for n, (t, rows) in enumerate(sorted(by_threads.items())):
                    cells = count_cells(cols, spec, t) + table_cells(cols, rows, key, fmt, lower_better)
                    out.append(md_row([label if n == 0 else "", str(t)] + cells + [unit if n == 0 else ""]))

    notes = {}
    for s in summary:
        if s["status"] != "ok":
            case = ROW_LABELS.get(s["workload"], s["workload"]).format(size=fmt_count(s["size"]), **s["params"])
            if s["status"] == "partial":
                case += f" at {s['threads']} threads ({s['runs']}/{s['expected_runs']} runs)"
            notes.setdefault((s["impl"], s["status"], s["reason"]), []).append(case)
    out += ["", "## Notes", ""]
    for (impl, status, reason), cases in notes.items():
        out.append(f"- {display_name(impl)} {status}" + (f" ({reason})" if reason else "") + ": " + "; ".join(dict.fromkeys(cases)))
    quiet = meta.get("quiet_cpu_pct")
    noisy_starts = {}
    for s in summary:
        if quiet is not None and (s.get("background_cpu_pct_max") or 0) > quiet:
            case = ROW_LABELS.get(s["workload"], s["workload"]).format(size=fmt_count(s["size"]), **s["params"])
            key = f"{case} at {s['threads']} threads"
            noisy_starts[key] = max(noisy_starts.get(key, 0), s["background_cpu_pct_max"])
    if noisy_starts:
        out.append(f"- Other processes used more than {quiet:.0f}% of CPU when these started: "
                   + "; ".join(f"{k} ({v:.0f}%)" for k, v in noisy_starts.items()))
    temps = [s["cpu_temp_c_max"] for s in summary if s.get("cpu_temp_c_max") is not None]
    if temps:
        out.append(f"- CPU temperature before each config: {min(temps):.0f}–{max(temps):.0f} °C")
    for v, help_text in (meta.get("variant_help") or {}).items():
        out.append(f"- Tokio + {v}: {help_text}")
    out += machine_lines(meta)
    return "\n".join(out) + "\n"


def display_order(impls: list[str]) -> list[str]:
    """Run order, except that tokio-tuned and tokio+VARIANT sit right after the implementation they derive from."""
    def key(item: tuple[int, str]) -> tuple[int, int, int]:
        i, impl = item
        parent = next((j for j, p in enumerate(impls) if impl != p and impl.startswith((p + "-", p + "+"))), None)
        return (i, 0, 0) if parent is None else (parent, 1, i)
    return [impl for _, impl in sorted(enumerate(impls), key=key)]


def display_name(impl: str) -> str:
    base, *variants = impl.split("+")
    return DISPLAY_NAMES.get(base, base) + "".join(f" + {v}" for v in variants)


def table_specs(summary: list[dict]) -> list[tuple]:
    """(workload, label, unit, value key, formatter, lower is better, rows by thread count) for each table line."""
    specs = []
    for workload, by_size in grouped(summary).items():
        for size, by_threads in by_size.items():
            params = next(iter(by_threads.values()))[0]["params"]
            label = ROW_LABELS.get(workload, workload).format(size=fmt_count(size), **params)
            if workload == "idle":
                specs.append((workload, label, "bytes per task, lower is better", "bytes_per_task", fmt_bytes, True, by_threads))
                continue
            specs.append((workload, label, describe(workload, params)[2], "ops_median", fmt_si, False, by_threads))
            if workload == "pingpong":
                for key, pct in (("lat_p50_ns", "p50"), ("lat_p99_ns", "p99")):
                    specs.append((workload, f"Ping-pong latency {pct}", "per round trip, lower is better", key, fmt_ns, True, by_threads))
    return specs


SHOWN_STATUSES = {"ok", "partial"}


def table_cells(impls: list[str], rows: list[dict], key: str, fmt, lower_better: bool) -> list[str]:
    by_impl = {s["impl"]: s for s in rows}
    values = {i: by_impl[i][key] for i in impls
              if i in by_impl and by_impl[i]["status"] in SHOWN_STATUSES and by_impl[i].get(key) is not None}
    best = clear_best(values, by_impl, key, fmt, lower_better)
    cells = []
    for impl in impls:
        s = by_impl.get(impl)
        if s is None:
            cells.append("—")
        elif impl not in values:
            cells.append("—" if s["status"] in SHOWN_STATUSES else s["status"])
        else:
            cell = fmt(values[impl])
            if impl == best:
                cell = f"**{cell}**"
            # Spread is measured on throughput (or memory), so it is not shown on latency rows.
            if not key.startswith("lat_") and s.get("cv_pct", 0) > CV_WARN_PCT:
                cell += " ⚠"
            if s["status"] == "partial":
                cell += f" ({s['runs']}/{s['expected_runs']})"
            cells.append(cell)
    return cells


def clear_best(values: dict[str, float], by_impl: dict[str, dict], key: str, fmt, lower_better: bool) -> str | None:
    """The implementation that is clearly best, or None when there is no clear winner.

    Clear means: it displays differently from the runner-up, and the confidence intervals of their
    medians don't overlap. Cells without an interval (older results) only need the first condition.
    """
    if len(values) < 2:
        return None
    ranked = sorted(values, key=values.get, reverse=not lower_better)
    first, second = ranked[0], ranked[1]
    if fmt(values[first]) == fmt(values[second]):
        return None
    ci_first = by_impl[first].get(f"{CI_OF.get(key)}_ci")
    ci_second = by_impl[second].get(f"{CI_OF.get(key)}_ci")
    if ci_first and ci_second:
        separated = ci_first[1] < ci_second[0] if lower_better else ci_first[0] > ci_second[1]
        if not separated:
            return None
    return first


def md_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def grouped(summary: list[dict]) -> dict:
    """workload -> size -> threads -> [summary rows]"""
    g: dict = {}
    for s in summary:
        g.setdefault(s["workload"], {}).setdefault(s["size"], {}).setdefault(s["threads"], []).append(s)
    return g


def machine_lines(meta: dict) -> list[str]:
    crates = ", ".join(f"{k} {v}" for k, v in sorted(meta.get("crates", {}).items()))
    return [
        f"- **Run:** profile `{meta['profile']}`, started {meta['started_at']}, seed {meta['seed']}",
        f"- **CPU:** {meta.get('cpu_model')} ({meta['logical_cpus']} logical CPUs), governor {', '.join(meta['governors']) or 'unknown'}",
        f"- **Pinning order:** {','.join(map(str, meta['cpu_order']))}",
        f"- **Kernel:** {meta['kernel']} · **Memory:** {meta['mem_total_kb'] // 1024:,} MiB total, {meta['mem_available_kb'] // 1024:,} MiB free at start",
        f"- **Toolchains:** {meta.get('rustc')} · {meta.get('go')}",
        f"- **Crates:** {crates}",
    ]


# ---------------------------------------------------------------- html

def render_html(meta: dict, summary: list[dict]) -> str:
    sections = []
    for workload, by_size in grouped(summary).items():
        params = next(iter(next(iter(by_size.values())).values()))[0]["params"]
        title, blurb, unit = describe(workload, params)
        sections.append({
            "workload": workload,
            "title": title,
            "blurb": " ".join(x for x in (blurb, concurrency_blurb(workload, params)) if x),
            "unit": unit,
            "sizes": [
                {"size": size, "points": [
                    {k: s.get(k) for k in ("threads", "impl", "status", "reason", "runs", "ops_median", "ops_min",
                                            "ops_max", "cv_pct", "lat_p50_ns", "lat_p99_ns", "lat_p999_ns", "bytes_per_task", "expected_runs",
                                            "ops_ci", "bytes_ci",
                                            "variants")}
                    for rows in by_threads.values() for s in rows
                ]}
                for size, by_threads in by_size.items()
            ],
        })
    data = {
        "meta": meta,
        "impls": meta["impls"],
        "cvWarn": CV_WARN_PCT,
        "sections": sections,
    }
    payload = json.dumps(data).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("/*__DATA__*/null", payload)


HTML_TEMPLATE = (Path(__file__).resolve().parent / "report_template.html").read_text()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(Path(sys.argv[1]))
    print(f"wrote summary.csv, summary.md, report.html in {sys.argv[1]}")
