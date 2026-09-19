# Tokio vs Crossbeam vs Go: concurrency benchmark

Same workloads, parameters, channel capacities and checksums in every implementation:

- **Tokio**: defaults (`tokio::sync`, system allocator).
- **Tuned Tokio**: mimalloc, kanal channels, batched receives, `parking_lot::Mutex`, no `JoinHandle`s.
- **Tuned Tokio, Tokio channels**: tuned Tokio with Tokio's `mpsc` instead of kanal, to isolate the channel.
- **Crossbeam**: OS threads with crossbeam channels and deques.
- **Go**: goroutines, channels, `sync`.

## Threads and tasks

- **Tokio**: tasks (heap-allocated state machines) on N worker threads. A task gives up its thread only at an
  `.await`; nothing preempts it.
- **Go**: goroutines (2 KiB growable stacks) on at most N threads (`GOMAXPROCS`); preempted after 10 ms.
- **Crossbeam**: no scheduler. Every sender, receiver, worker or task is an OS thread, scheduled by the kernel.

## Results

AMD Ryzen 5 5625U (6 cores / 12 threads), `performance` governor, AC power, Rust 1.98.0, Go 1.27.0. Median of 10
runs.

- **12 threads**: pinned to 12 CPUs; Tokio has 12 worker threads, Go has `GOMAXPROCS=12`. Crossbeam runs the OS
  threads in its column on those CPUs.
- Throughput is the whole test's total, not per thread or task. Latency is per round trip, memory per idle task.
- **Bold**: clear winner (confidence intervals don't overlap).

Every thread count, confidence intervals and CPU time: [`summary.md`](results/full-20260919-132216/summary.md),
[`summary.csv`](results/full-20260919-132216/summary.csv).
Flame graphs of every test at 12 threads, click to zoom:
[rishikesh01.github.io/…/flame-20260919-135158](https://rishikesh01.github.io/benchmark_rust_and_go_currency/results/flame-20260919-135158/).

### MPMC channels

async-channel (Tokio), kanal (tuned Tokio), crossbeam-channel, Go `chan`.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---:|---:|---|
| 4 senders → 4 receivers, capacity 1024 | 8 | 8 | 9.22M | **77.5M** | 30.5M | 18.8M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 8 | 8 | 2.12M | **19.1M** | 5.20M | 6.61M | messages/s |

### Single-receiver channels

Tokio `mpsc`; tuned Tokio kanal (`mpsc` for select); tuned Tokio, Tokio channels `mpsc`; Crossbeam and Go use their
MPMC channels.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 sender → 1 receiver, capacity 1024 | 2 | 2 | 12.8M | 23.5M | **133M** | 36.3M | 29.3M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 2 | 2 | 5.42M | 5.27M | **21.3M** | 7.15M | 11.3M | messages/s |
| 4 senders → 1 receiver, capacity 1024 | 5 | 5 | 8.59M | 6.81M | **99.4M** | 39.1M | 26.4M | messages/s |
| 4 senders → 1 receiver, capacity 1 | 5 | 5 | 4.87M | 5.01M | **19.5M** | 5.78M | 10.1M | messages/s |
| Ping-pong | 2 | 2 | 4.10M | 4.56M | **7.49M** | 3.82M | 3.86M | round trips/s |
| Ping-pong latency p50 | 2 | 2 | 150 ns | 131 ns | **81 ns** | 280 ns | 251 ns | lower is better |
| Ping-pong latency p99 | 2 | 2 | 2.18 µs | 2.16 µs | 2.13 µs | **301 ns** | 416 ns | lower is better |
| Select over 2 channels, capacity 1024 | 3 | 3 | 20.4M | — | **37.8M** | 13.5M | 14.0M | messages/s |
| Select over 2 channels, capacity 1 | 3 | 3 | 5.77M | — | 5.21M | 6.81M | 7.15M | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---:|---:|---|
| Spawn and join, 10K tasks | 10K | 10K | 3.86M | 5.93M | 29.7K | 5.53M | tasks/s |
| Spawn and join, 1M tasks | 1M | — | 3.96M | 5.42M | — | **5.91M** | tasks/s |
| CPU-heavy hashing | 256 | 12 | 116M | 115M | 115M | 109M | items/s |
| Lock contention, 8 workers | 8 | 8 | 9.74M | **83.5M** | 32.2M | 27.1M | increments/s |
| Memory per idle task, 10K tasks | 10K | 10K | 411 B | **367 B** | 9.92 KiB | 2.81 KiB | lower is better |
| Memory per idle task, 1M tasks | 1M | — | 385 B | **258 B** | — | 2.69 KiB | lower is better |

— : not run. Crossbeam is capped at 20,000 threads. Tuned Tokio, Tokio channels runs only the tests where tuned Tokio
uses kanal and Tokio has a channel.

## Why

- **Buffered channels:** Crossbeam's channel is a lock-free ring buffer. Go locks on every send and receive.
  Tokio's `mpsc` takes and returns a semaphore permit per message. kanal uses a spin lock, no semaphore, and hands
  values straight to a waiting receiver.
- **Channel vs the rest of the tuning:** tuned Tokio, Tokio channels keeps the drain loop (up to 256 queued messages
  per wake-up; any limit from 16 to 1024 performs the same) and mimalloc, but uses `mpsc`. Against default Tokio it's
  1.1–1.9× on buffered 1 → 1, 0.8–1.2× on buffered 4 → 1 and no faster at capacity 1. kanal makes it 3.6–15.5×
  faster (1.6× on ping-pong).
- **Tuned Tokio 1 → 1** is about as fast on 1 thread as on 12 (142M vs 133M, ~1.3 cores): Tokio's LIFO slot
  runs the woken task on the same worker, so producer and consumer mostly share one thread.
- **Tokio `mpsc` as designed (4 → 1):** no faster than with one sender (8.59M vs 12.8M for 1 → 1 at 12
  threads); kanal is 4–12× faster.
- **Capacity 1:** Go runs the woken goroutine next on the same thread, so it's flat from 1 to 12 threads
  (10.8M–11.5M). Crossbeam on 1 CPU pays a kernel context switch per hop (57K–154K/s). Tuned Tokio's lead is all
  kanal: with `mpsc`, the same tuning is no faster than default Tokio.
- **Ping-pong:** Tokio's median is about half of Go's (141 vs 270 ns on 1 thread): resuming a task is a function
  call, Go switches stacks. Tokio's ~2.2 µs p99 appears only with 2+ workers, likely from waking idle workers.
- **Select:** `recv_many` batching gives Tokio 1.5–2× at capacity 1024 and costs 5–10% at capacity 1, where Go is
  fastest with 2+ threads.
- **Spawn:** Go reuses finished goroutines. Default Tokio keeps each finished task until its `JoinHandle` is
  dropped: 1M tasks peak at 254–255 MiB, vs 17 MiB (tuned Tokio) and 24 MiB (Go) at 12 threads. On 1 thread all
  1M tasks queue before any runs (291 MiB tuned Tokio, 203 MiB Go). Crossbeam's thread per task is 127–217× slower.
- **CPU-heavy:** Tokio and Crossbeam tie. Go is ~5% slower (~8% on 6 threads); turning off async preemption didn't
  change it.
- **Lock contention:** Tokio's `Mutex` is FIFO-fair and hands the lock to the next task through the scheduler.
  `std::sync::Mutex` and Go's `sync.Mutex` spin briefly, then sleep. `parking_lot` lets a running thread grab a
  released lock (fair hand-off every 0–1 ms). In tuned Tokio it blocks the worker thread, which is fine because
  it's never held across an `.await`.
- **Idle memory:** a Tokio task is one 256 B allocation aligned to 128 B; glibc's `posix_memalign` makes it 384 B,
  mimalloc 258 B. A goroutine is a 2 KiB stack plus descriptor and wait record (2.69 KiB). An OS thread is ~10 KiB
  resident, not counting kernel memory.

## Implementations

| Workload | Tokio | Tuned Tokio | Crossbeam | Go |
|---|---|---|---|---|
| `spsc`, `mpsc`, `mpmc` | `mpsc` / `async-channel` ¹ | kanal + drain up to 256 per wake-up | `channel::bounded` | `chan` |
| `pingpong` | `mpsc(1)` | kanal `bounded(1)` | `bounded(1)` | `chan` cap 1 |
| `spawn` | `tokio::spawn` + `JoinHandle` | `tokio::spawn`, results in a shared slice | scoped OS threads | goroutines + `WaitGroup` |
| `cpu` | tasks on the runtime | same | work-stealing `deque` pool | goroutines |
| `select` | `tokio::select!` | `select!` + `recv_many(256)` | `select!` | `select` |
| `mutex` | `tokio::sync::Mutex` | `parking_lot::Mutex` | `std::sync::Mutex` ² | `sync.Mutex` |
| `idle` | task waiting on a `Semaphore` | same | blocked OS thread | blocked goroutine |
| allocator | system | mimalloc | system | Go runtime |

1. Tokio has no MPMC channel (`broadcast` sends every message to every receiver).
2. Crossbeam has no mutex.

Capacity: 1024 for `spsc`, `mpsc`, `mpmc`, `select`; 1 for the `-cap1` cases and `pingpong` (Tokio can't do 0).

`rust/tokio-tuned-bench` also builds `tokio-tuned-tokio-channels-bench`: tuned Tokio's `spsc`, `mpsc` and `pingpong`
with `mpsc` instead of kanal.

`rust/tokio-variants-bench` turns on single Tokio tweaks (`--impls tokio,tokio+kanal,tokio+kanal+batch`). Its
generic wrappers make it slower than `tokio-tuned`.

## Method

- Fresh process per run, pinned with `taskset` to N CPUs, physical cores first.
- 3 warm-ups, then 10 measured runs; order shuffled every round.
- Only the workload is timed; `spawn` does one untimed pass first.
- A run counts only with a correct checksum (`cpu` checked independently with numpy) and echoed parameters.
- Median with a distribution-free confidence interval. CPU time, context switches, background load and CPU
  temperature are recorded per run.

## Compared with established practice

Sources: crossbeam-channel [benchmarks](https://github.com/crossbeam-rs/crossbeam/tree/master/crossbeam-channel/benchmarks),
[kanal suite](https://github.com/fereidani/rust-channel-benchmarks),
Tokio [benches](https://github.com/tokio-rs/tokio/tree/master/benches),
Go [chan_test.go](https://github.com/golang/go/blob/master/src/runtime/chan_test.go),
[benchstat](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat), [Savina](https://github.com/shamsimam/savina),
[Georges et al. 2007](https://dri.es/files/oopsla07-georges.pdf),
[pyperf](https://pyperf.readthedocs.io/en/latest/system.html), [wrk2](https://github.com/giltene/wrk2).

| Practice | Here |
|---|---|
| Fresh process per measurement, shuffled order | yes |
| Thread-count sweep, CPU pinning | yes |
| Received values and parameters checked | yes |
| Warm-up inside the measured process | `spawn` only |
| Median with confidence interval | yes |
| CPU time and peak memory alongside throughput | yes |
| Capacities 0 / 1 / N / unbounded | 1 and 1024 only |
| Several payload sizes | no, `u64` only |
| Work per message or outside the lock | no, empty critical sections |
| 20 runs per cell (benchstat) | no, 10 |
| `performance` governor, turbo/SMT off, isolated CPUs | governor only |
| Open-loop latency histogram (wrk2) | no, ping-pong is closed-loop |
| Scheduler cases: chained spawn, yield, remote spawn | no |
| Concurrency testing (loom, shuttle, `go test -race`) | no |

## Caveats

- Only Tokio was tuned.
- kanal's receive future isn't cancel-safe, so it can't be used in `select!` or with timeouts.
- One-increment critical sections exaggerate lock differences.
- Ping-pong latency is measured at saturation.
- CPU results depend on code generation; the laptop reached 84 °C.
- Idle memory excludes kernel memory for OS threads.

## Running

Requires Linux, Rust 1.98+, Go 1.27+, Python 3.10+, `taskset` and `lscpu`; numpy is optional.

```sh
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
python3 runner/run.py --profile full --impls tokio,crossbeam,go,tokio-tuned-tokio-channels,tokio-tuned  # about 30 minutes
python3 runner/run.py                                                                                   # smoke test, about 1 minute
python3 runner/report.py results/<run>                                                                  # rebuild the reports
python3 runner/flamegraph.py --results results/<run>                                                    # flame graphs, about 2 minutes
```

Flags: `--workloads`, `--threads`, `--reps`, `--warmup`, `--seed`, `--no-build`, `--out`.

Each run writes `results/<profile>-<timestamp>/`: `raw.jsonl`, `summary.csv`, `summary.md`, `report.html`.

`flamegraph.py` writes `results/flame-<timestamp>/`: one SVG per test and an `index.md` table of the run's medians,
each linked to its graph. It needs perf, `cargo install inferno rustfilt` and `sudo sysctl
kernel.perf_event_paranoid=1 kernel.kptr_restrict=0`. Rust is rebuilt with frame pointers because DWARF unwinding
lost about half the stacks. In spot checks that build ran within 10% of the benchmark build, except Crossbeam 1 → 1
(30% slower) and 4 → 4 (15% faster).

```
rust/common/                shared CLI, JSON output, checksums
rust/tokio-bench/           Tokio
rust/tokio-tuned-bench/     tuned Tokio, and tuned Tokio with Tokio channels
rust/tokio-variants-bench/  single-tweak Tokio builds
rust/crossbeam-bench/       Crossbeam
go/                         Go
runner/                     run.py, report.py, flamegraph.py
```
