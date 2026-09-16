# Tokio vs Crossbeam vs Go: concurrency benchmark

Eight workloads, each written the normal way in all three tools, doing the same
work and producing the same checksum. One Python runner builds, pins, runs,
verifies and reports on all of them the same way.

```
rust/
  common/            CLI flags, JSON output, CPU kernel, RSS + percentile helpers
  tokio-bench/       Tokio implementations
  crossbeam-bench/   Crossbeam implementations (OS threads)
go/                  Go implementations (harness.go mirrors rust/common)
runner/
  run.py             build → run → verify → report
  report.py          summary.csv, summary.md, report.html from a results dir
results/<profile>-<timestamp>/
```

## Running

Requires Rust (stable), Go 1.22+, Python 3.10+, `lscpu` and `taskset` (util-linux). Linux only
(`/proc/self/status` is used for memory).

```sh
python3 runner/run.py                        # smoke profile: tiny sizes, about 1 minute
python3 runner/run.py --profile full         # real numbers: 3 warm-ups + 10 runs, roughly 15 minutes (estimated)
python3 runner/run.py --profile full --workloads cpu,mutex --threads 1,6
python3 runner/report.py results/full-...    # rebuild reports from an existing raw.jsonl
```

Other flags: `--impls tokio,go`, `--reps N`, `--warmup N`, `--seed N`, `--timeout S`,
`--no-build`, `--out DIR`.

Each binary also runs on its own and prints one JSON line:

```sh
rust/target/release/tokio-bench --workload spsc --threads 4 --size 1000000
go/bin/gobench                  --workload spsc --threads 4 --size 1000000
```

### Before a `full` run
- Plug in the charger and close heavy programs; the runner warns about battery power, load average > 1, or a
  non-`performance` governor.
- Set the governor: `echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor`
- The `idle` test at 1M tasks needs about 3 GB free for Go.

## Workloads

| Workload | Measures | Tokio | Crossbeam | Go |
|---|---|---|---|---|
| `spsc` | channel throughput, 1 sender → 1 receiver, capacity 1024 | `sync::mpsc` | `channel::bounded` | `chan` |
| `mpmc` | 4 senders → 4 receivers on one channel | `async-channel` ¹ | `channel::bounded` | `chan` |
| `pingpong` | wake-up cost: one token bounced between two tasks, p50/p99/p99.9 round trip | `mpsc(1)` | `bounded(1)` | `chan` cap 1 ² |
| `spawn` | start N tasks that return a value, join all | `tokio::spawn` | scoped OS threads ³ | goroutines + `WaitGroup` |
| `cpu` | parallel splitmix64 hashing, 256 chunks | tasks on runtime | `deque` work-stealing pool | goroutines |
| `select` | one consumer selecting over two channels until both close | `tokio::select!` | `select!` + `never()` | `select` + nil channel |
| `mutex` | 8 workers incrementing one counter | `sync::Mutex` | `parking_lot::Mutex` | `sync.Mutex` |
| `idle` | resident memory per parked task (10k / 100k / 1M) | `Semaphore` wait | blocked OS thread ³ | blocked goroutine |

1. Tokio's own mpsc has a single receiver.
2. Capacity 1 everywhere, because Tokio channels can't be zero-capacity.
3. Crossbeam has no lightweight tasks. Above 20,000 threads the binary reports `skipped`.

## How the numbers are kept comparable

- **Same CPUs:** every run is a fresh process under `taskset` with exactly N logical CPUs, picked one per
  physical core before any SMT sibling. `worker_threads`, the Crossbeam pool size and `GOMAXPROCS` are all N.
  Workloads with a fixed number of workers (e.g. 4+4 in `mpmc`) still get only N CPUs.
- **Same order effects:** warm-up runs first, then measured runs. The order of the three implementations is
  shuffled every round, and the seed is saved in `meta.json`.
- **Checked results:** a run only counts if its checksum matches the closed-form expected value. The `cpu`
  test has no closed form, so all implementations must agree with each other. A wrong checksum drops that
  implementation for the configuration.
- **Timed section:** only the workload is timed, not runtime or process startup. Crossbeam's long-lived
  workers wait at a barrier, and the first worker to start reads the clock, so OS thread creation is excluded
  just as Tokio's pre-built worker pool is. `spawn` and `idle` time thread creation on purpose.
- **Build settings:** Rust uses `--release` with `lto = "fat"` and `codegen-units = 1`. Go uses a default
  `go build`. Default allocators on both sides.
- **Reporting:** medians, with coefficient of variation (±%) and min–max. Cells with CV above 5% are marked ⚠.

## Caveats

- Tokio vs Crossbeam is an async runtime vs a set of thread tools. The results show what each costs when used
  normally, not raw library speed.
- `cpu` also measures compiler code generation (LLVM vs Go's compiler), not only scheduling.
- Tokio's docs recommend rayon or `spawn_blocking` for CPU-heavy work; `cpu` shows the cost of using the async
  runtime anyway.
- Go numbers include its garbage collector.
- `idle` counts resident memory only. Kernel thread structures aren't included, which flatters OS threads.
- Latency is sampled every 16th round trip, and reading the clock (~20 ns) is inside each sample for all three.
- Laptop CPUs throttle when hot, so compare runs taken under similar conditions.

## Outputs

| File | Contents |
|---|---|
| `meta.json` | machine, toolchains, crate versions, governor, warnings, seed |
| `raw.jsonl` | every run, including warm-ups, skips and failures |
| `summary.csv` | one row per workload × size × threads × implementation |
| `summary.md` | tables, best value in bold |
| `report.html` | self-contained charts (hover for details, table view under each chart) |

## Adding a workload

1. Implement it in `tokio-bench`, `crossbeam-bench` and `go/main.go`, printing `Report`/`okReport`.
2. Add its parameters to `WORKLOAD_PARAMS`, its sizes to both `PROFILES`, and its checksum to `expected_checksum`
   in `runner/run.py`.
3. Add a title, description and unit to `WORKLOAD_INFO` in `runner/report.py`.
