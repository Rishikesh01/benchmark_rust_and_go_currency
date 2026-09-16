# Tokio vs Crossbeam vs Go: concurrency benchmark

Eight workloads, each written the normal way in Tokio, Crossbeam and Go, doing the same work and producing
the same checksum. The three channel tests also run with a capacity-1 channel. A separately written tuned
Tokio version shows how far Tokio gets with common tweaks. One Python runner builds, pins, runs, verifies and
reports on all of them the same way.

```
rust/
  common/                CLI flags, JSON output, CPU kernel, RSS + percentile helpers
  tokio-bench/           Tokio, default choices
  tokio-tuned-bench/     Tokio, tuned (separate code, see "Tuned Tokio")
  tokio-variants-bench/  Tokio with single tweaks switched on, used to choose the tuned version
  crossbeam-bench/       Crossbeam (OS threads)
go/                      Go (harness.go mirrors rust/common)
runner/
  run.py                 build → run → verify → report
  report.py              summary.csv, summary.md, report.html from a results dir
results/<profile>-<timestamp>/
```

## Results

From [`results/full-20260916-231803`](results/full-20260916-231803/summary.md): AMD Ryzen 5 5625U laptop
(6 cores / 12 threads), 3 warm-ups + 10 measured runs, medians. The CPU governor was `powersave` and the load
average was 3.3 at the start, so some cells are noisy (marked ⚠ in `summary.md`). Tables for 1, 2 and 6 threads,
spread and latency percentiles are in `summary.md`; charts are in `report.html`.

At 12 threads:

| Test case | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---|
| `spsc` | 12.8M | **129M** | 36.4M | 28.5M | messages/s |
| `spsc-cap1` | 4.52M | **18.2M** | 6.64M | 9.92M | messages/s |
| `mpmc` | 9.46M | **67.7M** | 24.1M | 15.3M | messages/s |
| `mpmc-cap1` | 1.95M | **18.1M** | 4.83M | 6.20M | messages/s |
| `pingpong` | 4.37M | **7.53M** | 3.94M | 4.00M | round trips/s |
| `spawn`, 1M tasks | 2.59M | 5.21M | skipped | **5.55M** | tasks/s |
| `cpu` | 115M | 117M | 115M | 107M | items/s |
| `select` | 20.3M | **40.7M** | 13.2M | 13.8M | messages/s |
| `select-cap1` | 5.78M | 5.15M | 3.32M | **7.17M** | messages/s |
| `mutex` | 9.47M | 82.6M | 81.6M | 27.0M | increments/s |
| `idle`, 1M tasks | 384 B | **256 B** | skipped | 2.69 KiB | memory per task |

- **Tuned Tokio** is clearly fastest on 7 of the 11 cases, ties on `cpu` and `mutex`, and is behind Go on `spawn`
  and `select-cap1`. The big gains are on channels: 10× default Tokio on `spsc` and 7× on `mpmc`.
- **Default Tokio** is the slowest on every channel test from 2 threads up, and its async `tokio::sync::Mutex` is
  about 3× slower than Go's `sync.Mutex` and about 9× slower than `parking_lot`.
- **Capacity 1** costs everyone. Among the untuned implementations Go copes best: it leads on every capacity-1
  case from 2 threads up and is fastest overall on `select-cap1`, where tuned Tokio's batching can't help.
- **Crossbeam on 1 CPU** drops to 109K–154K messages/s on capacity-1 channels and ping-pong, because each message
  needs an OS thread switch. With 2 or more CPUs it has the best ping-pong tail: p99 about 300 ns, against about
  430 ns for Go and about 2.2 µs for both Tokio versions. Tuned Tokio has the best median, 90 ns.
- **Spawning:** Go leads at 6 and 12 threads; tuned Tokio leads on 1 and 2 threads (6.64M and 6.19M tasks/s,
  against Go's 1.43M and 5.30M). Crossbeam's OS threads manage about 29K/s at 10k tasks.
- **CPU-heavy work** is within 10% everywhere (Go about 7% behind); tuning doesn't matter because the hot loop
  never allocates.
- **Memory per idle task** at 10k tasks: tuned Tokio 225 B, default Tokio 393 B, Go 2.75 KiB, Crossbeam OS threads
  9.84 KiB (excluding kernel memory).

## Running

Requires Rust (stable), Go 1.22+, Python 3.10+, `lscpu` and `taskset` (util-linux). Linux only
(`/proc/self/status` is used for memory).

```sh
python3 runner/run.py                        # smoke profile: tiny sizes, about 1 minute
python3 runner/run.py --profile full         # real numbers: 3 warm-ups + 10 runs
python3 runner/run.py --profile full --impls tokio,crossbeam,go,tokio-tuned   # about 20 minutes
python3 runner/run.py --profile full --workloads cpu,mutex --threads 1,6
python3 runner/report.py results/full-...    # rebuild reports from an existing raw.jsonl
```

`--impls` accepts `tokio`, `crossbeam`, `go` (the default set) and `tokio-tuned`, plus screening builds
written as `tokio+VARIANT[+VARIANT]`, e.g. `tokio+kanal,tokio+mimalloc+batch`. Other flags: `--reps N`,
`--warmup N`, `--seed N`, `--timeout S`, `--no-build`, `--out DIR`.

Each binary also runs on its own and prints one JSON line:

```sh
rust/target/release/tokio-bench       --workload spsc --threads 4 --size 1000000
rust/target/release/tokio-tuned-bench --workload spsc --threads 4 --size 1000000 --capacity 1
go/bin/gobench                        --workload spsc --threads 4 --size 1000000
```

### Before a `full` run
- Plug in the charger and close heavy programs; the runner warns about battery power, load average > 1, or a
  non-`performance` governor.
- Set the governor: `echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor`
- The `idle` test at 1M tasks needs about 3 GB free for Go.

## Workloads

| Workload | Measures | Tokio | Crossbeam | Go |
|---|---|---|---|---|
| `spsc` | channel throughput, 1 sender → 1 receiver | `sync::mpsc` | `channel::bounded` | `chan` |
| `mpmc` | 4 senders → 4 receivers on one channel | `async-channel` ¹ | `channel::bounded` | `chan` |
| `pingpong` | wake-up cost: one token bounced between two tasks, p50/p99/p99.9 round trip | `mpsc(1)` | `bounded(1)` | `chan` cap 1 |
| `spawn` | start N tasks that return a value, join all | `tokio::spawn` | scoped OS threads ² | goroutines + `WaitGroup` |
| `cpu` | parallel splitmix64 hashing, 256 chunks | tasks on runtime | `deque` work-stealing pool | goroutines |
| `select` | one consumer selecting over two channels until both close | `tokio::select!` | `select!` + `never()` | `select` + nil channel |
| `mutex` | 8 workers incrementing one counter | `sync::Mutex` | `parking_lot::Mutex` | `sync.Mutex` |
| `idle` | resident memory per parked task (10k / 100k / 1M) | `Semaphore` wait | blocked OS thread ² | blocked goroutine |

1. Tokio's own mpsc has a single receiver.
2. Crossbeam has no lightweight tasks. Above 20,000 threads the binary reports `skipped`.

### Channel capacity

Every implementation, including `tokio-tuned`, uses the same capacity in each test case:

| Test case | Capacity |
|---|---|
| `spsc`, `mpmc`, `select` (each of the two channels) | 1024 |
| `spsc-cap1`, `mpmc-cap1`, `select-cap1` | 1 |
| `pingpong` (both directions) | 1 |

Capacity 1 rather than 0 because Tokio channels can't be zero-capacity. At capacity 1 nearly every message is
a hand-off between tasks, so these cases measure wake-up cost rather than batching. They use 1M messages
instead of 10M because Crossbeam on 1 CPU manages only about 130K messages/s there.

## Tuned Tokio

`rust/tokio-tuned-bench` is a separate program with the same parameters, capacities and checksums as
`tokio-bench`. Only the Tokio-side choices differ:

| Test | `tokio` | `tokio-tuned` |
|---|---|---|
| all | system malloc | mimalloc |
| `spsc`, `mpmc` | `tokio::sync::mpsc` / `async-channel`, one message per receive | kanal, then up to 256 already-queued messages per wake-up |
| `pingpong` | `tokio::sync::mpsc` | kanal |
| `spawn` | a `JoinHandle` per task | tasks write into a shared slice, one `Notify` at the end (like Go's `WaitGroup`) |
| `select` | `recv()` | `recv_many(256)` |
| `mutex` | `tokio::sync::Mutex` | `parking_lot::Mutex`, never held across `.await` |
| `cpu`, `idle` | — | unchanged apart from the allocator |

### How the tweaks were chosen

Each tweak was first measured on its own with `tokio-variants-bench` (3 runs at 1, 2 and 12 threads; data
in `results/tuning-screen-a`, `-b`, `-c`) and kept only if it helped. Speed-ups at 12 threads, against default
Tokio in the same screening run:

| Tweak | Effect | Kept |
|---|---|---|
| kanal channels | spsc 3.2×, mpmc 3.5×, pingpong 1.4× | yes |
| drain queued messages (`batch`) | spsc 2.0×, select 1.7×, mpmc ≈1× on its own | yes |
| kanal + batch together | spsc 6.0×, mpmc 5.3× | yes |
| mimalloc | spawn 1.9×, idle memory −33%, other tests within noise | yes, everywhere |
| no `JoinHandle`s | spawn 0.8× alone, 1.2× on top of mimalloc | yes, with mimalloc |
| `parking_lot::Mutex` | mutex 9.3× | yes |
| `std::sync::Mutex` | mutex 3.4× (fastest on 1 thread, slower than parking_lot from 2) | no |
| flume channels | spsc 1.1×, mpmc 0.8×, pingpong ≈1× | no |
| `unconstrained` (no co-op budget) | spsc 1.2×, pingpong and select slightly slower | no |
| both sides in one task with `join!` | spsc 1.7×, pingpong 0.6×, and no parallelism | no |
| `biased` `select!` | select 0.6× | no |

Kanal's gain is not bought with spinning. Measured by CPU time at 12 threads, kanal + batch + mimalloc moved
61M messages per CPU-second on `spsc`, against 6M for default Tokio and 17M for Crossbeam.

The screening runs were made before the variant code moved into its own crate, so their `raw.jsonl` names
the binary `tokio-bench(-mimalloc)`; the code is the same.

## How the numbers are kept comparable

- **Same CPUs:** every run is a fresh process under `taskset` with exactly N logical CPUs, picked one per
  physical core before any SMT sibling. `worker_threads`, the Crossbeam pool size and `GOMAXPROCS` are all N.
  Workloads with a fixed number of workers (e.g. 4+4 in `mpmc`) still get only N CPUs.
- **Same order effects:** warm-up runs first, then measured runs. The order of the implementations is
  shuffled every round, and the seed is saved in `meta.json`.
- **Checked results:** a run only counts if its checksum matches the closed-form expected value. The `cpu`
  test has no closed form, so all implementations must agree with each other. A wrong checksum drops that
  implementation for the configuration.
- **Timed section:** only the workload is timed, not runtime or process startup. Crossbeam's long-lived
  workers wait at a barrier, and the first worker to start reads the clock, so OS thread creation is excluded
  just as Tokio's pre-built worker pool is. `spawn` and `idle` time thread creation on purpose.
- **Build settings:** Rust uses `--release` with `lto = "fat"` and `codegen-units = 1`. Go uses a default
  `go build`. Default allocators everywhere except `tokio-tuned` (mimalloc).
- **Reporting:** medians, with coefficient of variation (±%) and min–max. Cells with CV above 5% are marked ⚠.

## Caveats

- Tokio vs Crossbeam is an async runtime vs a set of thread tools. The results show what each costs when used
  normally, not raw library speed.
- `tokio-tuned` leans on third-party crates (kanal, mimalloc, parking_lot). Crossbeam and Go were not given the
  same tuning pass.
- `cpu` also measures compiler code generation (LLVM vs Go's compiler), not only scheduling.
- Tokio's docs recommend rayon or `spawn_blocking` for CPU-heavy work; `cpu` shows the cost of using the async
  runtime anyway.
- Go numbers include its garbage collector.
- `idle` counts resident memory only. Kernel thread structures aren't included, which flatters OS threads.
- Latency is sampled every 16th round trip, and reading the clock (~20 ns) is inside each sample for everyone.
- Laptop CPUs throttle when hot, so compare runs taken under similar conditions.

## Outputs

| File | Contents |
|---|---|
| `meta.json` | machine, toolchains, crate versions, governor, warnings, seed |
| `raw.jsonl` | every run, including warm-ups, skips and failures |
| `summary.csv` | one row per test case × size × threads × implementation |
| `summary.md` | tables, best value in bold |
| `report.html` | self-contained charts (hover for details, table view under each chart); download and open it locally, GitHub shows HTML as source |

## Adding a workload

1. Implement it in `tokio-bench`, `tokio-tuned-bench`, `crossbeam-bench` and `go/main.go`, printing
   `Report`/`okReport`.
2. Add its parameters to `WORKLOAD_PARAMS`, its sizes to both `PROFILES`, and its checksum to `expected_checksum`
   in `runner/run.py`. A new parameter set for an existing workload also needs an entry in `CASE_WORKLOAD`.
3. Add a title, description and unit to `WORKLOAD_INFO` in `runner/report.py`.
