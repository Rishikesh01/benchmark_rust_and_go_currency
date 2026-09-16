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

WORKLOAD_ORDER = ["spsc", "mpmc", "pingpong", "spawn", "cpu", "select", "mutex", "idle"]
WORKLOAD_INFO = {
    "spsc": ("One sender, one receiver", "Raw message rate through a bounded channel.", "messages/s"),
    "mpmc": ("Many senders, many receivers", "{producers} senders and {consumers} receivers sharing one bounded channel.", "messages/s"),
    "pingpong": ("Ping-pong", "Two tasks pass one token back and forth over capacity-1 channels; measures wake-up cost.", "round trips/s"),
    "spawn": ("Spawn and join", "Start tasks that each return a number, then wait for all of them.", "tasks/s"),
    "cpu": ("CPU-heavy parallel work", "Hash items with splitmix64 ({rounds} rounds each), split into {tasks} chunks.", "items/s"),
    "select": ("Select", "One consumer waits on two channels at once until both close.", "messages/s"),
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

def fmt_si(v: float | None) -> str:
    if v is None:
        return "-"
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:.3g}{suffix}"
    return f"{v:.3g}"


def fmt_ns(v: float | None) -> str:
    if v is None:
        return "-"
    for div, unit in ((1e9, "s"), (1e6, "ms"), (1e3, "µs")):
        if v >= div:
            return f"{v / div:.3g} {unit}"
    return f"{v:.0f} ns"


def fmt_bytes(v: float | None) -> str:
    if v is None:
        return "-"
    for div, unit in ((1 << 30, "GiB"), (1 << 20, "MiB"), (1 << 10, "KiB")):
        if v >= div:
            return f"{v / div:.3g} {unit}"
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

def render_markdown(meta: dict, summary: list[dict]) -> str:
    out = [f"# Concurrency benchmark: {' vs '.join(meta['impls'])}", ""]
    out += machine_lines(meta)
    if meta.get("variant_help"):
        out += ["", "**Tokio variants**", ""] + [f"- `{v}`: {help}" for v, help in meta["variant_help"].items()]
    if meta["warnings"]:
        out += ["", "**Warnings**", ""] + [f"- ⚠ {w}" for w in meta["warnings"]]
    out += [
        "",
        f"Each cell is the median of {meta['reps']} measured runs (after {meta['warmup']} warm-up{'' if meta['warmup'] == 1 else 's'}), "
        f"with the coefficient of variation. **Bold** is the best in the row; ⚠ marks CV above {CV_WARN_PCT:.0f}%. "
        "Every run is a separate process pinned to `threads` CPUs with taskset.",
    ]

    for workload, by_size in grouped(summary).items():
        params = next(iter(next(iter(by_size.values())).values()))[0]["params"]
        title, blurb, unit = describe(workload, params)
        present = {s["impl"] for by_threads in by_size.values() for rows in by_threads.values() for s in rows}
        impls = [i for i in meta["impls"] if i in present]
        out += ["", f"## {title} (`{workload}`)", "", blurb]
        for size, by_threads in by_size.items():
            if workload == "idle":
                out += ["", f"Tasks: {size:,}. Lower is better.", ""]
                out += table(impls, by_threads, "Threads", lambda s: s.get("bytes_per_task"), fmt_bytes, lower_better=True)
                continue
            out += ["", f"Size: {size:,}. Unit: {unit}, higher is better.", ""]
            out += table(impls, by_threads, "Threads", lambda s: s.get("ops_median"), fmt_si, lower_better=False)
            if workload == "pingpong":
                for key, label in (("lat_p50_ns", "p50"), ("lat_p99_ns", "p99"), ("lat_p999_ns", "p99.9")):
                    out += ["", f"Round-trip latency {label} (lower is better):", ""]
                    out += table(impls, by_threads, "Threads", lambda s, k=key: s.get(k), fmt_ns, lower_better=True, show_cv=False)

    problems = [s for s in summary if s["status"] != "ok"]
    if problems:
        out += ["", "## Skipped or failed", "", "| Workload | Size | Threads | Impl | Status | Reason |", "|---|---:|---:|---|---|---|"]
        out += [f"| {s['workload']} | {s['size']:,} | {s['threads']} | {s['impl']} | {s['status']} | {s['reason'] or ''} |" for s in problems]
    return "\n".join(out) + "\n"


def grouped(summary: list[dict]) -> dict:
    """workload -> size -> threads -> [summary rows]"""
    g: dict = {}
    for s in summary:
        g.setdefault(s["workload"], {}).setdefault(s["size"], {}).setdefault(s["threads"], []).append(s)
    return g


def table(impls, by_threads, first_col, value, fmt, lower_better, show_cv=True) -> list[str]:
    lines = [f"| {first_col} | " + " | ".join(impls) + " |", "|---:|" + "---:|" * len(impls)]
    for threads, rows in by_threads.items():
        by_impl = {s["impl"]: s for s in rows}
        values = {i: value(by_impl[i]) for i in impls if i in by_impl and by_impl[i]["status"] == "ok" and value(by_impl[i]) is not None}
        best = (min if lower_better else max)(values.values()) if len(values) > 1 else None
        cells = []
        for impl in impls:
            s = by_impl.get(impl)
            if s is None:
                cells.append("-")
            elif impl not in values:
                cells.append(s["status"])
            else:
                cell = fmt(values[impl])
                if values[impl] == best:
                    cell = f"**{cell}**"
                if show_cv:
                    cell += f" ±{s['cv_pct']:.1f}%" + (" ⚠" if s["cv_pct"] > CV_WARN_PCT else "")
                cells.append(cell)
        lines.append(f"| {threads} | " + " | ".join(cells) + " |")
    return lines


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
