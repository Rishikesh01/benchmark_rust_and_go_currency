#!/usr/bin/env python3
"""Summarises a results directory into summary.csv, summary.md and report.html.

Usage: python3 runner/report.py results/<run-dir>
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

CV_WARN_PCT = 5.0

WORKLOAD_ORDER = ["spsc", "spsc-cap1", "mpmc", "mpmc-cap1", "pingpong", "spawn", "cpu", "select", "select-cap1", "mutex", "idle"]
WORKLOAD_INFO = {
    "spsc": ("One sender, one receiver", "Raw message rate through a bounded channel of capacity {capacity}.", "messages/s"),
    "spsc-cap1": ("One sender, one receiver, capacity 1",
                  "The same test with a channel of capacity {capacity}, so nearly every message is a hand-off between tasks.", "messages/s"),
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


def build(out_dir: Path) -> None:
    out_dir = Path(out_dir)
    meta = json.loads((out_dir / "meta.json").read_text())
    rows = [json.loads(l) for l in (out_dir / "raw.jsonl").read_text().splitlines() if l.strip()]
    summary = summarise(rows, meta["impls"])
    write_csv(out_dir / "summary.csv", summary)
    (out_dir / "summary.md").write_text(render_markdown(meta, summary))
    (out_dir / "report.html").write_text(render_html(meta, summary))


def summarise(rows: list[dict], impl_order: list[str]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["workload"], r["size"], r["threads"], r["impl"]), []).append(r)

    summary = []
    for (workload, size, threads, impl), recs in groups.items():
        ok = [r for r in recs if r["phase"] == "measure" and r["status"] == "ok" and r["valid"]]
        bad = next((r for r in recs if r["status"] != "ok" or r.get("valid") is False), None)
        s = {
            "workload": workload,
            "size": size,
            "threads": threads,
            "impl": impl,
            "params": recs[0].get("params", {}),
            "variants": recs[0].get("variants", []),
            "runs": len(ok),
            "status": "ok" if ok else ("invalid" if bad and bad["status"] == "ok" else (bad["status"] if bad else "no data")),
            "reason": bad.get("reason") if bad else None,
        }
        if ok:
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
        summary.append(s)

    def sort_key(s):
        impl_rank = impl_order.index(s["impl"]) if s["impl"] in impl_order else len(impl_order)
        return (workload_rank(s["workload"]), s["size"], s["threads"], impl_rank)

    return sorted(summary, key=sort_key)


def workload_rank(w: str) -> int:
    return WORKLOAD_ORDER.index(w) if w in WORKLOAD_ORDER else len(WORKLOAD_ORDER)


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
    return f"{x:.0f}" if abs(x) >= 100 else f"{x:.1f}" if abs(x) >= 10 else f"{x:.2f}"


def fmt_si(v: float | None) -> str:
    if v is None:
        return "-"
    v = float(f"{v:.3g}")  # round first so 999.6K becomes 1.00M, not 1000K
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
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
    for div, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= div:
            return f"{n / div:.3g}{suffix}"
    return str(n)


def fmt_bytes(v: float | None) -> str:
    if v is None:
        return "-"
    for div, unit in ((1 << 30, "GiB"), (1 << 20, "MiB"), (1 << 10, "KiB")):
        if v >= div:
            return f"{sig3(v / div)} {unit}"
    return f"{v:.0f} B"


def describe(workload: str, params: dict) -> tuple[str, str, str]:
    title, blurb, unit = WORKLOAD_INFO.get(workload, (workload, "", "ops/s"))
    return title, blurb.format(**params) if params else blurb, unit


# ---------------------------------------------------------------- csv

CSV_FIELDS = [
    "workload", "size", "threads", "impl", "status", "runs", "ops_median", "ops_min", "ops_max", "cv_pct",
    "wall_ms_median", "lat_p50_ns", "lat_p99_ns", "lat_p999_ns", "bytes_per_task", "peak_rss_kb_median", "reason",
]


def write_csv(path: Path, summary: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(summary)


# ---------------------------------------------------------------- markdown

DISPLAY_NAMES = {"tokio": "Tokio", "tokio-tuned": "Tuned Tokio", "crossbeam": "Crossbeam", "go": "Go"}

# Test names in the summary table. {size} is the compact run size; other fields are the case parameters.
ROW_LABELS = {
    "spsc": "1 sender → 1 receiver, capacity {capacity}",
    "spsc-cap1": "1 sender → 1 receiver, capacity {capacity}",
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


def render_markdown(meta: dict, summary: list[dict]) -> str:
    impls = display_order(meta["impls"])
    specs = table_specs(summary)
    threads = sorted({s["threads"] for s in summary})
    top = threads[-1] if threads else 0

    bases = list(dict.fromkeys(impl.split("+")[0] for impl in impls))
    title = " vs ".join(DISPLAY_NAMES.get(b, b) for b in bases)
    warmups = f"{meta['warmup']} warm-up{'' if meta['warmup'] == 1 else 's'}"
    out = [
        f"# {title}",
        "",
        f"Median of {meta['reps']} runs after {warmups} (profile `{meta['profile']}`, started {meta['started_at']}). "
        f"**Bold** is the best in each row; ⚠ means the runs varied by more than {CV_WARN_PCT:.0f}%. "
        "Spread, min/max and p99.9 latency are in `summary.csv`.",
    ]
    if meta["warnings"]:
        out += ["", "⚠ Run conditions: " + " ".join(w.split(". Fix:")[0].rstrip(".") + "." for w in meta["warnings"])]

    header = ["Test"] + [display_name(i) for i in impls] + ["Unit"]
    out += ["", f"## At {top} threads", "", md_row(header), md_row(["---"] + ["---:"] * len(impls) + ["---"])]
    for label, unit, key, fmt, lower_better, by_threads in specs:
        if top in by_threads:
            out.append(md_row([label] + table_cells(impls, by_threads[top], key, fmt, lower_better) + [unit]))

    if len(threads) > 1:
        header = ["Test", "Threads"] + [display_name(i) for i in impls] + ["Unit"]
        out += ["", "## All thread counts", "", md_row(header), md_row(["---", "---:"] + ["---:"] * len(impls) + ["---"])]
        for label, unit, key, fmt, lower_better, by_threads in specs:
            for n, (t, rows) in enumerate(sorted(by_threads.items())):
                cells = table_cells(impls, rows, key, fmt, lower_better)
                out.append(md_row([label if n == 0 else "", str(t)] + cells + [unit if n == 0 else ""]))

    notes = {}
    for s in summary:
        if s["status"] != "ok":
            case = ROW_LABELS.get(s["workload"], s["workload"]).format(size=fmt_count(s["size"]), **s["params"])
            notes.setdefault((s["impl"], s["status"], s["reason"]), []).append(case)
    out += ["", "## Notes", ""]
    for (impl, status, reason), cases in notes.items():
        out.append(f"- {display_name(impl)} {status}" + (f" ({reason})" if reason else "") + ": " + "; ".join(dict.fromkeys(cases)))
    for v, help_text in (meta.get("variant_help") or {}).items():
        out.append(f"- Tokio + {v}: {help_text}")
    out += machine_lines(meta)
    return "\n".join(out) + "\n"


def display_order(impls: list[str]) -> list[str]:
    """Run order, except that tokio-tuned and tokio+VARIANT sit right after the implementation they derive from."""
    def key(item: tuple[int, str]) -> tuple[int, int]:
        i, impl = item
        parent = next((j for j, p in enumerate(impls) if impl != p and impl.startswith((p + "-", p + "+"))), i)
        return parent, i
    return [impl for _, impl in sorted(enumerate(impls), key=key)]


def display_name(impl: str) -> str:
    base, *variants = impl.split("+")
    return DISPLAY_NAMES.get(base, base) + "".join(f" + {v}" for v in variants)


def table_specs(summary: list[dict]) -> list[tuple]:
    """(label, unit, value key, formatter, lower is better, rows by thread count) for each table line."""
    specs = []
    for workload, by_size in grouped(summary).items():
        for size, by_threads in by_size.items():
            params = next(iter(by_threads.values()))[0]["params"]
            label = ROW_LABELS.get(workload, workload).format(size=fmt_count(size), **params)
            if workload == "idle":
                specs.append((label, "bytes per task, lower is better", "bytes_per_task", fmt_bytes, True, by_threads))
                continue
            specs.append((label, describe(workload, params)[2], "ops_median", fmt_si, False, by_threads))
            if workload == "pingpong":
                for key, pct in (("lat_p50_ns", "p50"), ("lat_p99_ns", "p99")):
                    specs.append((f"Ping-pong latency {pct}", "per round trip, lower is better", key, fmt_ns, True, by_threads))
    return specs


def table_cells(impls: list[str], rows: list[dict], key: str, fmt, lower_better: bool) -> list[str]:
    by_impl = {s["impl"]: s for s in rows}
    values = {i: by_impl[i][key] for i in impls if i in by_impl and by_impl[i]["status"] == "ok" and by_impl[i].get(key) is not None}
    # Compare as displayed, so values that look identical are all marked best.
    best = fmt((min if lower_better else max)(values.values())) if len(values) > 1 else None
    cells = []
    for impl in impls:
        s = by_impl.get(impl)
        if s is None:
            cells.append("—")
        elif impl not in values:
            cells.append(s["status"])
        else:
            cell = fmt(values[impl])
            if cell == best:
                cell = f"**{cell}**"
            # Spread is measured on throughput (or memory), so it is not shown on latency rows.
            if not key.startswith("lat_") and s.get("cv_pct", 0) > CV_WARN_PCT:
                cell += " ⚠"
            cells.append(cell)
    return cells


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
            "blurb": blurb,
            "unit": unit,
            "sizes": [
                {"size": size, "points": [
                    {k: s.get(k) for k in ("threads", "impl", "status", "reason", "runs", "ops_median", "ops_min",
                                            "ops_max", "cv_pct", "lat_p50_ns", "lat_p99_ns", "lat_p999_ns", "bytes_per_task",
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
