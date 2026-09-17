# Tokio vs Crossbeam vs Go: concurrency benchmark

The same workloads implemented four ways, with identical parameters, bounded channel capacities and checksums:

- **Tokio**: default Tokio choices (`tokio::sync` primitives, system allocator).
- **Tuned Tokio**: Tokio with mimalloc, kanal channels, batched receives, `parking_lot::Mutex` and spawning
  without `JoinHandle`s.
- **Crossbeam**: plain OS threads with crossbeam channels and deques.
- **Go**: goroutines, channels and `sync`.

## Results

AMD Ryzen 5 5625U laptop (6 cores / 12 threads), `performance` governor, on AC power. Medians of 10 runs at
12 threads. **Bold** marks a clear winner: its confidence interval doesn't overlap the runner-up's. Every
thread count, confidence intervals, CPU time and p99.9 latency: [`summary.md`](results/full-20260917-103559/summary.md),
[`summary.csv`](results/full-20260917-103559/summary.csv).

### MPMC channels

Every implementation uses a bounded multi-producer, multi-consumer channel: async-channel (Tokio), kanal (tuned
Tokio), crossbeam-channel and Go `chan`.

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---|
| 4 senders → 4 receivers, capacity 1024 | 9.78M | **81.1M** | 26.5M | 18.7M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 2.08M | **19.2M** | 5.14M | 6.62M | messages/s |

### Single-receiver channels

One receiver per channel. Tokio uses its MPSC channel, `tokio::sync::mpsc` (so does tuned Tokio for select); tuned
Tokio otherwise uses kanal, and Crossbeam and Go use their MPMC channels with a single receiver.

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---|
| 1 sender → 1 receiver, capacity 1024 | 13.1M | **135M** | 37.1M | 29.3M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 4.91M | **19.7M** | 7.10M | 10.5M | messages/s |
| Ping-pong | 4.31M | **7.04M** | 3.86M | 3.91M | round trips/s |
| Ping-pong latency p50 | 140 ns | **90 ns** | 280 ns | 250 ns | lower is better |
| Ping-pong latency p99 | 2.18 µs | 2.17 µs | **341 ns** | 516 ns | lower is better |
| Select over 2 channels, capacity 1024 | 20.0M | **36.9M** | 13.3M | 13.8M | messages/s |
| Select over 2 channels, capacity 1 | 5.43M | 4.91M | 5.77M | **7.09M** | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---|
| Spawn and join, 10K tasks | 3.87M | 5.87M | 28.2K | 5.32M | tasks/s |
| Spawn and join, 1M tasks | 3.56M | 5.31M | — | **5.59M** | tasks/s |
| CPU-heavy hashing | 99.0M | 99.1M | 99.7M | 90.7M | items/s |
| Lock contention, 8 workers | 8.98M | **74.8M** | 29.4M | 25.8M | increments/s |
| Memory per idle task, 10K tasks | 408 B | **261 B** | 9.92 KiB | 2.79 KiB | lower is better |
| Memory per idle task, 1M tasks | 385 B | **258 B** | — | 2.69 KiB | lower is better |

— : Crossbeam uses one OS thread per task and is capped at 20,000 threads.

## Why

**Buffered channels (capacity 1024).** Crossbeam's bounded channel is a lock-free preallocated array whose
threads spin briefly before parking, so most operations never reach the kernel. Go's channel takes a lock on
every send and receive. Tokio's bounded `mpsc` takes a semaphore permit per message and wakes tasks through the
scheduler, which costs more per message than either. Tuned Tokio's consumer takes up to 256 already-queued
messages per wake-up instead of one, so most messages never go back through the scheduler. kanal adds a queue
behind its own lock with no permit semaphore, and hands values straight to a waiting receiver.

**Capacity 1.** Nearly every message is a hand-off. Go puts the goroutine it wakes into the current processor's
run-next slot, so sender and receiver keep swapping on one thread; that is why Go's throughput here is flat from
1 to 12 threads (10.5M–11.1M). Crossbeam's sender and receiver are separate OS threads: with 2 or more CPUs every
hand-off crosses CPUs, and on a single CPU every hop is a kernel context switch (110K–150K messages/s). Tuned
Tokio still leads on 1 → 1 and 4 → 4 because kanal passes values directly to a waiting receiver and the drain
loop picks up whatever else is already queued.

**Ping-pong.** Tokio (its LIFO slot) and Go (run-next) both run the just-woken task next on the same thread, yet
Tokio's median round trip is half of Go's even on one thread (141 vs 280 ns). The likely reason is that resuming
a Tokio task is a call into its state machine, while Go switches goroutine stacks. Tokio's p99 of about 2.2 µs
appears only with 2 or more worker threads and is the same with kanal or `mpsc`, which points to cross-worker
scheduling rather than the channel. Crossbeam's two threads spin before sleeping, which keeps its tail tight once
each has its own CPU.

**Select.** `tokio::select!` polls both receivers inside one task. Go's `select` locks every channel involved on
each iteration, and crossbeam's `select!` tries each channel and registers with all of them when none is ready.
Batching with `recv_many` nearly doubles tuned Tokio's result at capacity 1024. At capacity 1 there is nothing to
batch, so it only adds work, and Go's same-thread hand-offs win.

**Spawn.** Go reuses dead goroutines and their stacks, so spawning is cheap in a warm process. Default Tokio keeps
every task allocated until its `JoinHandle` is awaited: with 1M tasks its peak memory is 254 MB, against 18 MB for
tuned Tokio and 24 MB for Go. Tuned Tokio drops the handles, so each task frees itself when it finishes, and it
allocates through mimalloc. Crossbeam creates an OS thread per task (a `clone` system call plus a stack mapping),
which is 140–210× slower.

**CPU-heavy work.** Nothing blocks, so the scheduler barely matters and Tokio and Crossbeam tie. On one thread Go
is about 4% slower; with no scheduling involved, that is code generation. The gap roughly doubles at 6 and 12
threads. Turning off Go's asynchronous preemption didn't change it, and the cause wasn't isolated.

**Lock contention.** Tokio's async `Mutex` is FIFO-fair: every contended lock waits in a queue and is woken through
the scheduler, which is expensive when the critical section is one increment. `std::sync::Mutex` spins briefly and
then waits on a futex, and Go's `sync.Mutex` spins and then parks the goroutine, so the two land close together.
`parking_lot`'s mutex lets a running thread take a just-released lock and forces a fair hand-off only about every
0.5 ms, trading fairness for throughput.

**Memory per idle task.** Each Tokio task is one 256-byte allocation. Tokio aligns the task header to 128 bytes, so
Rust's system allocator goes through glibc's `posix_memalign`, which costs about 130 B extra per task here (385 B
resident); mimalloc serves the same request with no overhead (258 B). A goroutine starts with at least a 2 KiB
stack plus its descriptor (2.69 KiB). An OS thread keeps its touched stack pages and thread bookkeeping resident,
about 10 KiB, not counting kernel memory.

## Implementations

| Workload | Tokio | Tuned Tokio | Crossbeam | Go |
|---|---|---|---|---|
| `spsc`, `mpmc` | `mpsc` / `async-channel` ¹ | kanal + drain up to 256 per wake-up | `channel::bounded` | `chan` |
| `pingpong` | `mpsc(1)` | kanal `bounded(1)` | `bounded(1)` | `chan` cap 1 |
| `spawn` | `tokio::spawn` + `JoinHandle` | `tokio::spawn`, results in a shared slice | scoped OS threads | goroutines + `WaitGroup` |
| `cpu` | tasks on the runtime | same | work-stealing `deque` pool | goroutines |
| `select` | `tokio::select!` | `select!` + `recv_many(256)` | `select!` | `select` |
| `mutex` | `tokio::sync::Mutex` | `parking_lot::Mutex` | `std::sync::Mutex` ² | `sync.Mutex` |
| `idle` | task waiting on a `Semaphore` | same | blocked OS thread | blocked goroutine |
| allocator | system | mimalloc | system | Go runtime |

1. Tokio has no MPMC channel.
2. Crossbeam has no mutex.

Channel capacity is identical everywhere: 1024 for `spsc`, `mpmc` and `select`; 1 for their `-cap1` variants
and for `pingpong` (Tokio channels can't have capacity 0).

`rust/tokio-variants-bench` switches single Tokio tweaks on for comparison, e.g.
`--impls tokio,tokio+kanal,tokio+mimalloc+batch`. Its generic wrappers add per-message overhead, so its absolute
numbers are lower than `tokio-tuned`'s.

## Method

- Each run is a fresh process pinned with `taskset` to N logical CPUs, one per physical core before any SMT
  sibling. Tokio worker threads, Crossbeam's pool and `GOMAXPROCS` are all N.
- 3 warm-up runs, then 10 measured runs; implementation order is shuffled every round.
- Only the workload is timed. `spawn` runs one untimed pass first so the timed pass isn't paying for cold
  thread stacks and page faults.
- A run counts only if its checksum is correct (the `cpu` checksum is computed independently with numpy) and the
  binary echoes the exact parameters it was given.
- Reported value: median with a distribution-free confidence interval. CPU time, context switches, background
  CPU load and CPU temperature are recorded for every run.

## Compared with established practice

Sources: crossbeam-channel [benchmarks](https://github.com/crossbeam-rs/crossbeam/tree/master/crossbeam-channel/benchmarks),
the [kanal suite](https://github.com/fereidani/rust-channel-benchmarks), Tokio's
[benches](https://github.com/tokio-rs/tokio/tree/master/benches), Go's
[runtime/chan_test.go](https://github.com/golang/go/blob/master/src/runtime/chan_test.go) and
[benchstat](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat), [Savina](https://github.com/shamsimam/savina),
[Georges et al. 2007](https://dri.es/files/oopsla07-georges.pdf),
[pyperf](https://pyperf.readthedocs.io/en/latest/system.html), [wrk2](https://github.com/giltene/wrk2).

| Practice | Here |
|---|---|
| Fresh process per measurement, interleaved/shuffled order | yes |
| Thread-count sweep, CPU pinning | yes |
| Received values and parameters checked | yes (checksums, echoed parameters) |
| Warm-up inside the measured process (Criterion, kanal suite) | partly: `spawn` only; other runs are long enough |
| Median with confidence interval, no winner when intervals overlap | yes |
| CPU time and peak memory alongside throughput | yes |
| Capacities 0 / 1 / N / unbounded | partly: 1 and 1024 (Tokio has no capacity 0) |
| Several payload sizes (kanal, Tokio `sync_mpsc`) | no: `u64` only |
| Work per message or outside the lock (Go `ChanProdConsWork`, `MutexWork`) | no: empty critical sections, which exaggerate hand-off and spinning effects |
| 20 runs per cell (benchstat) | no: 10 |
| `performance` governor, turbo/SMT off, isolated CPUs | partly: `performance` governor; turbo and SMT on, CPUs not isolated |
| Open-loop latency with a latency histogram (wrk2/HdrHistogram) | no: ping-pong is closed-loop |
| Scheduler cases such as chained spawn, yield, remote spawn (Tokio benches) | no |
| Systematic concurrency testing (loom, shuttle, `go test -race`) | no |

## Caveats

- Tuned Tokio uses third-party crates; Crossbeam and Go got no equivalent tuning.
- kanal's receive future isn't safe to cancel (a message can be lost), so it can't be used inside `select!` or
  with timeouts.
- The mutex critical section is one increment, which exaggerates differences between lock designs.
- Ping-pong is closed-loop: its latency is round-trip time at saturation, not latency under a given load.
- CPU-heavy results depend on compiler code generation, and the laptop reached 84 °C during the run.
- Idle memory is resident memory only; kernel structures for OS threads aren't counted.

## Running

Requires Linux, Rust, Go 1.22+, Python 3.10+, `taskset` and `lscpu`; numpy is optional.

```sh
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
python3 runner/run.py --profile full --impls tokio,crossbeam,go,tokio-tuned   # about 20 minutes
python3 runner/run.py                                                         # smoke test, about 1 minute
python3 runner/report.py results/<run>                                        # rebuild the reports
```

Flags: `--workloads`, `--threads`, `--reps`, `--warmup`, `--seed`, `--no-build`, `--out`.

Each run writes `results/<profile>-<timestamp>/` containing `raw.jsonl` (every run), `summary.csv`,
`summary.md` and `report.html` (charts; open locally).

```
rust/common/                shared CLI, JSON output, checksums
rust/tokio-bench/           Tokio
rust/tokio-tuned-bench/     tuned Tokio
rust/tokio-variants-bench/  single-tweak Tokio builds
rust/crossbeam-bench/       Crossbeam
go/                         Go
runner/                     run.py, report.py
```
