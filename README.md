# Tokio vs Crossbeam vs Go: concurrency benchmark

Same workloads, parameters, channel capacities and checksums, implemented four ways:

- **Tokio**: defaults (`tokio::sync`, system allocator).
- **Tuned Tokio**: mimalloc, kanal channels, batched receives, `parking_lot::Mutex`, no `JoinHandle`s.
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

Every thread count, confidence intervals and CPU time: [`summary.md`](results/full-20260918-210446/summary.md),
[`summary.csv`](results/full-20260918-210446/summary.csv).
Flame graphs of every test at 12 threads: [`index.md`](results/flame-20260919-123439/index.md).

### MPMC channels

async-channel (Tokio), kanal (tuned Tokio), crossbeam-channel, Go `chan`.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---:|---:|---|
| 4 senders → 4 receivers, capacity 1024 | 8 | 8 | 9.80M | **81.3M** | 28.0M | 18.8M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 8 | 8 | 1.99M | **18.8M** | 5.17M | 6.61M | messages/s |

### Single-receiver channels

Tokio `mpsc`; tuned Tokio kanal (`mpsc` for select); Crossbeam and Go use their MPMC channels.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 sender → 1 receiver, capacity 1024 | 2 | 2 | 13.4M | **136M** | 36.8M | 29.4M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 2 | 2 | 5.29M | **20.5M** | 7.21M | 11.2M | messages/s |
| 4 senders → 1 receiver, capacity 1024 | 5 | 5 | 8.76M | **102M** | 40.0M | 26.6M | messages/s |
| 4 senders → 1 receiver, capacity 1 | 5 | 5 | 5.23M | **19.7M** | 5.78M | 10.1M | messages/s |
| Ping-pong | 2 | 2 | 4.10M | **7.33M** | 4.18M | 3.89M | round trips/s |
| Ping-pong latency p50 | 2 | 2 | 150 ns | **86 ns** | 281 ns | 250 ns | lower is better |
| Ping-pong latency p99 | 2 | 2 | 2.18 µs | 2.13 µs | **301 ns** | 451 ns | lower is better |
| Select over 2 channels, capacity 1024 | 3 | 3 | 20.6M | **41.5M** | 13.4M | 13.9M | messages/s |
| Select over 2 channels, capacity 1 | 3 | 3 | 5.81M | 5.37M | 6.33M | **7.25M** | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---:|---:|---|
| Spawn and join, 10K tasks | 10K | 10K | 3.93M | **6.08M** | 29.2K | 5.37M | tasks/s |
| Spawn and join, 1M tasks | 1M | — | 3.85M | 5.42M | — | **5.90M** | tasks/s |
| CPU-heavy hashing | 256 | 12 | 114M | **116M** | 115M | 109M | items/s |
| Lock contention, 8 workers | 8 | 8 | 9.71M | **84.1M** | 32.6M | 27.1M | increments/s |
| Memory per idle task, 10K tasks | 10K | 10K | 460 B | **233 B** | 9.93 KiB | 2.78 KiB | lower is better |
| Memory per idle task, 1M tasks | 1M | — | 385 B | **257 B** | — | 2.69 KiB | lower is better |

— : not run (Crossbeam is capped at 20,000 threads).

## Why

- **Buffered channels:** Crossbeam's channel is a lock-free ring buffer. Go locks on every send and receive.
  Tokio's `mpsc` takes and returns a semaphore permit per message. kanal uses a spin lock, no semaphore, and hands
  values straight to a waiting receiver.
- **Drain loop (tuned Tokio):** up to 256 queued messages per wake-up via `try_recv`. About 2× on kanal 1 → 1 with
  2+ threads, +25–45% elsewhere. Any limit from 16 to 1024 performs the same, so 256 is arbitrary. Cause not
  isolated: context switches, CPU time and per-message channel work are unchanged.
- **Tuned Tokio 1 → 1** is about as fast on 1 thread as on 12 (143M vs 136M, ~1.3 cores): Tokio's LIFO slot
  runs the woken task on the same worker, so producer and consumer mostly share one thread.
- **Tokio `mpsc` as designed (4 → 1):** no faster than with one sender (8.76M vs 13.4M for 1 → 1 at 12
  threads); kanal is 4–12× faster.
- **Capacity 1:** Go runs the woken goroutine next on the same thread, so it's flat from 1 to 12 threads
  (10.9M–11.5M). Crossbeam on 1 CPU pays a kernel context switch per hop (110K–154K/s). Tuned Tokio's lead comes
  from kanal (3× on 1 → 1, 5–10× on 4 → 4); the drain loop adds ≤7%.
- **Ping-pong:** Tokio's median is about half of Go's (141 vs 270 ns on 1 thread): resuming a task is a function
  call, Go switches stacks. Tokio's ~2.2 µs p99 appears only with 2+ workers, likely from waking idle workers.
- **Select:** `recv_many` batching gives Tokio 1.5–1.8× at capacity 1024 and costs 3–8% at capacity 1, where Go
  wins.
- **Spawn:** Go reuses finished goroutines. Default Tokio keeps each finished task until its `JoinHandle` is
  dropped: 1M tasks peak at 254–255 MiB, vs 17 MiB (tuned Tokio) and 24 MiB (Go) at 12 threads. On 1 thread all
  1M tasks queue before any runs (291 MiB tuned Tokio, 203 MiB Go). Crossbeam's thread per task is 135–210× slower.
- **CPU-heavy:** Tokio and Crossbeam tie. Go is ~6% slower on 1 thread, ~10% on 6 and ~5% on 12; turning off
  async preemption didn't change it.
- **Lock contention:** Tokio's `Mutex` is FIFO-fair and hands the lock to the next task through the scheduler.
  `std::sync::Mutex` and Go's `sync.Mutex` spin briefly, then sleep. `parking_lot` lets a running thread grab a
  released lock (fair hand-off every 0–1 ms). In tuned Tokio it blocks the worker thread, which is fine because
  it's never held across an `.await`.
- **Idle memory:** a Tokio task is one 256 B allocation aligned to 128 B; glibc's `posix_memalign` makes it 384 B,
  mimalloc 257 B. A goroutine is a 2 KiB stack plus descriptor and wait record (2.69 KiB). An OS thread is ~10 KiB
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
python3 runner/run.py --profile full --impls tokio,crossbeam,go,tokio-tuned   # about 20 minutes
python3 runner/run.py                                                         # smoke test, about 1 minute
python3 runner/report.py results/<run>                                        # rebuild the reports
python3 runner/flamegraph.py                                                  # flame graphs, about 2 minutes
```

Flags: `--workloads`, `--threads`, `--reps`, `--warmup`, `--seed`, `--no-build`, `--out`.

Each run writes `results/<profile>-<timestamp>/`: `raw.jsonl`, `summary.csv`, `summary.md`, `report.html`.

`flamegraph.py` writes `results/flame-<timestamp>/`: one SVG per test and an `index.md`. It needs perf,
`cargo install inferno rustfilt` and `sudo sysctl kernel.perf_event_paranoid=1 kernel.kptr_restrict=0`. Rust is
rebuilt with frame pointers because DWARF unwinding lost about half the stacks. In spot checks that build ran
within 10% of the benchmark build, except Crossbeam 1 → 1 (30% slower) and 4 → 4 (15% faster).

```
rust/common/                shared CLI, JSON output, checksums
rust/tokio-bench/           Tokio
rust/tokio-tuned-bench/     tuned Tokio
rust/tokio-variants-bench/  single-tweak Tokio builds
rust/crossbeam-bench/       Crossbeam
go/                         Go
runner/                     run.py, report.py, flamegraph.py
```
