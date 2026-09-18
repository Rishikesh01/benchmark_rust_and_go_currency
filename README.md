# Tokio vs Crossbeam vs Go: concurrency benchmark

The same workloads implemented four ways, with identical parameters, bounded channel capacities and checksums:

- **Tokio**: default Tokio choices (`tokio::sync` primitives, system allocator).
- **Tuned Tokio**: Tokio with mimalloc, kanal channels, batched receives, `parking_lot::Mutex` and spawning
  without `JoinHandle`s.
- **Crossbeam**: plain OS threads with crossbeam channels and deques.
- **Go**: goroutines, channels and `sync`.

## Threads and tasks

Crossbeam has no scheduler: everything that runs concurrently is an OS thread, and the kernel decides which one
runs. Tokio and Go run many lightweight tasks on a few OS threads and switch between them without the kernel.

- **Tokio** (both builds): a multi-threaded runtime with N worker threads. Each unit of work is a task started with
  `tokio::spawn`: a heap-allocated state machine, not a thread. A worker runs a task until it reaches an `.await`
  that isn't ready (or Tokio's co-operative budget runs out), then switches to another task. Nothing preempts a
  task, so one that never waits keeps its worker until it finishes. Idle workers steal tasks from other workers'
  queues. No other threads are involved here: the workers also run the timer, and the main thread only waits in
  `block_on`.
- **Go**: each unit of work is a goroutine with its own stack, 2 KiB to start, that grows when needed. The runtime
  runs goroutines on OS threads, at most N (`GOMAXPROCS`) of them running Go code at once, and switches between
  goroutines in user space; the kernel is involved only when a thread runs out of work and sleeps, or is woken. A
  thread that runs out of goroutines steals half of another thread's queue. Unlike Tokio, the runtime preempts a
  goroutine that runs for more than 10 ms.
- **Crossbeam**: every sender, receiver, worker and spawned task is its own OS thread. A thread that has to wait
  spins briefly, yields its CPU a few times, then sleeps on a futex until another thread wakes it.

The thread count in the results is N: each run is pinned to N logical CPUs, Tokio gets N worker threads and Go
gets `GOMAXPROCS=N`. Crossbeam's thread count comes from the workload instead, and those threads share the N CPUs;
only `cpu` sizes its pool to N.

| Workload | Tokio tasks, Go goroutines | Crossbeam OS threads |
|---|---|---|
| `spsc`, `pingpong` | 2 | 2 |
| `select` | 3 (2 senders, 1 receiver) | 3 |
| `mpmc` | 8 (4 senders, 4 receivers) | 8 |
| `mutex` | 8 | 8 |
| `cpu` | 256, one per chunk | N, sharing the 256 chunks through work-stealing deques |
| `spawn` | 10K or 1M | 10K (1M is skipped) |
| `idle` | 10K, 100K or 1M | 10K (larger counts are skipped) |

With fewer CPUs than threads, Crossbeam's threads take turns through the kernel while Tokio and Go switch tasks
inside one thread; the 1-thread results for capacity 1 and ping-pong show the difference.

## Results

AMD Ryzen 5 5625U laptop (6 cores / 12 threads), `performance` governor, on AC power. Rust 1.98.0
(`rustc 1.98.0 (88d9e12ae 2026-08-18)`, release build) and Go 1.27.0 (`go1.27.0 linux/amd64`). Medians of 10
runs at 12 threads. **Bold** marks a clear winner: its confidence interval doesn't overlap the runner-up's.
Every thread count, confidence intervals, CPU time and p99.9 latency:
[`summary.md`](results/full-20260918-190906/summary.md),
[`summary.csv`](results/full-20260918-190906/summary.csv).

### MPMC channels

Every implementation uses a bounded multi-producer, multi-consumer channel: async-channel (Tokio), kanal (tuned
Tokio), crossbeam-channel and Go `chan`.

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---|
| 4 senders → 4 receivers, capacity 1024 | 9.32M | **78.5M** | 24.3M | 17.6M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 1.74M | **17.4M** | 4.62M | 5.89M | messages/s |

### Single-receiver channels

One receiver per channel. Tokio uses its MPSC channel, `tokio::sync::mpsc` (so does tuned Tokio for select); tuned
Tokio otherwise uses kanal, and Crossbeam and Go use their MPMC channels with a single receiver.

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---|
| 1 sender → 1 receiver, capacity 1024 | 13.2M | **129M** | 33.9M | 28.0M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 4.63M | **17.3M** | 6.70M | 10.4M | messages/s |
| Ping-pong | 3.85M | **6.25M** | 3.81M | 3.58M | round trips/s |
| Ping-pong latency p50 | 151 ns | **100 ns** | 281 ns | 275 ns | lower is better |
| Ping-pong latency p99 | 2.48 µs | 2.46 µs | **350 ns** | 581 ns | lower is better |
| Select over 2 channels, capacity 1024 | 19.8M | **37.8M** | 13.3M | 13.8M | messages/s |
| Select over 2 channels, capacity 1 | 5.00M | 4.58M | 5.88M | **6.74M** | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---|
| Spawn and join, 10K tasks | 3.59M | 5.90M | 26.0K | 5.39M | tasks/s |
| Spawn and join, 1M tasks | 3.39M | 4.91M | — | **5.32M** | tasks/s |
| CPU-heavy hashing | 99.5M | 96.0M | 94.6M | 90.6M | items/s |
| Lock contention, 8 workers | 8.49M | **75.1M** | 28.4M | 24.8M | increments/s |
| Memory per idle task, 10K tasks | 410 B | **281 B** | 9.92 KiB | 2.78 KiB | lower is better |
| Memory per idle task, 1M tasks | 384 B | **257 B** | — | 2.69 KiB | lower is better |

— : Crossbeam uses one OS thread per task and is capped at 20,000 threads.

## Why

**Buffered channels (capacity 1024).** Crossbeam's bounded channel is a preallocated ring buffer whose slots are
claimed with atomic compare-and-swap, without a lock. A thread that finds it full or empty spins briefly and
yields its CPU a few times before it sleeps, so an operation that finds room or a message never enters the kernel.
Go's channel takes a lock on every send and receive. Tokio's bounded `mpsc` takes a semaphore permit for every
message, the receiver hands each one back through a lock inside the semaphore, and a side that has to wait is
woken through the scheduler; that costs more per message than either. kanal is a queue behind its own spin lock
with no permit semaphore, and it hands values straight to a waiting receiver.

Tuned Tokio's consumers also take up to 256 already-queued messages with `try_recv` after each awaited receive. In
the variants build this about doubles kanal's 1 → 1 throughput with 2 or more threads (`tokio+kanal` vs
`tokio+kanal+batch`) and adds 25–45% on 4 → 4 and on one thread. The limit of 256 has no special meaning: a sweep
from 1 to 1024 (changing `BATCH` in `tokio-tuned-bench`) gave the same throughput for any limit from 16 up, and
since kanal's `recv` doesn't yield while messages are queued, the limit doesn't make a consumer give up its worker
either. Why the loop helps isn't clear. It isn't fewer trips through the scheduler: a plain receive loop also
takes queued messages without yielding (kanal's `recv` returns at once when the queue isn't empty), and on 1 → 1
context switches and CPU time are about the same with and without the loop. It isn't less channel work either: a
new kanal receive future that finds a message takes the same lock and pops the same queue as `try_recv`, without
allocating or registering a waker.

Tuned Tokio's 1 → 1 is also about as fast on 1 thread as on 12 (135M vs 129M) and uses about 1.3 cores' worth of
CPU time. That fits Tokio's LIFO slot: a task woken by a worker runs next on that worker and can't be stolen from
the slot, so producer and consumer mostly take turns on one thread, filling and then draining the buffer. The slot
is used for at most 3 hand-offs in a row; after that the woken task goes to the worker's normal queue, where an
idle worker can steal it, so the pair sometimes moves or briefly runs on two threads. Crossbeam's two threads each
keep a core busy and pass every message between cores.

**Capacity 1.** Nearly every message is a hand-off. Go puts the goroutine it wakes into the waking thread's
run-next slot. Another thread can take it from there only after a 3 µs back-off, and at capacity 1 the waker
blocks well before that, so sender and receiver keep swapping on one thread; that is why Go's throughput here is
flat from 1 to 12 threads (10.3M–11.2M). Crossbeam's sender and receiver are separate OS threads: with 2 or more
CPUs every hand-off crosses CPUs, and on a single CPU every hop is a kernel context switch (107K–153K messages/s).
Tuned Tokio still leads on 1 → 1 and 4 → 4 because kanal passes values directly to a waiting receiver, with no
permit semaphore in between. The drain loop adds little here: in the variants build kanal alone gives about 3× on
1 → 1 and 5–10× on 4 → 4, and the loop adds at most 7% on top.

**Ping-pong.** Tokio (its LIFO slot) and Go (run-next) both run the just-woken task next on the same thread, yet
Tokio's median round trip is about half of Go's even on one thread (141 vs 271 ns). The likely reason is that
resuming a Tokio task is a function call into its state machine on the worker's own stack, while Go parks the
current goroutine, runs its scheduler and switches to the woken goroutine's stack. Tokio's p99 of 2.3–2.5 µs
appears only with 2 or more worker threads and is the same with kanal or `mpsc`, which points to Tokio waking idle
workers rather than to the channel: after 3 hand-offs through the LIFO slot, the woken task goes to the stealable
queue and a sleeping worker is woken, a system call inside the round trip. Crossbeam's two threads spin and yield
before sleeping, which keeps its tail tight once each has its own CPU.

**Select.** `tokio::select!` polls the receivers inside one task. Go's `select` locks every channel involved on
each iteration, and crossbeam's `select!` tries each channel and registers with all of them when none is ready. In
the variants build, batching with `recv_many` raises Tokio's select throughput 1.5–1.8× at capacity 1024: one call
takes every queued message up to the limit and returns their permits to the semaphore in one step. At capacity 1
there is nothing to batch, so it only adds work (3–8% slower), and Go's same-thread hand-offs win.

**Spawn.** Go reuses finished goroutines for new ones, often with their stacks still attached (each garbage
collection frees the stacks of those on the shared free list, and a new stack then comes from a cache), so
spawning is cheap in a warm process. Default Tokio keeps every finished task allocated until its `JoinHandle` is
dropped, and the benchmark keeps all handles until it awaits them in order: with 1M tasks its peak memory is
254–255 MiB at every thread count, against 19 MiB for tuned Tokio and 24 MiB for Go at 12 threads. Tuned Tokio
keeps no handles, so each task frees itself when it finishes, and it allocates through mimalloc. That only helps
while the workers keep up: on one thread tasks pile up behind the spawning loop (`tokio::spawn` never yields, so
all 1M are queued before any runs), and the peaks are 291 MiB for tuned Tokio and 194 MiB for Go. Crossbeam
creates an OS thread per task (a `clone` system call and a stack for each), which is 140–230× slower.

**CPU-heavy work.** Nothing blocks, so the scheduler barely matters and Tokio and Crossbeam tie. On one thread Go
is about 4% slower; with no scheduling involved, that is code generation. The gap grows to about 10% at 6 threads.
Turning off Go's asynchronous preemption didn't change it, and the cause wasn't isolated. At 12 threads every
implementation varied by 8–11% between runs, so there is no clear order.

**Lock contention.** Tokio's async `Mutex` is FIFO-fair: an unlock hands the lock to the oldest waiting task and
wakes it through the scheduler, and the lock stays reserved until that task runs, which is expensive when the
critical section is one increment. `std::sync::Mutex` spins briefly (not at all once threads are already waiting)
and then waits on a futex, and Go's `sync.Mutex` spins briefly while other threads are running Go code and then
parks the goroutine, so the two land close together. `parking_lot`'s mutex lets a running thread take a
just-released lock and forces a fair hand-off only after a random 0–1 ms interval, trading fairness for
throughput. Tuned Tokio's `parking_lot` lock blocks the whole worker thread while it waits, not just the task;
that works because the lock is held only for the increment, never across an `.await`.

**Memory per idle task.** Each Tokio task here is one 256-byte allocation, aligned to 128 bytes. Rust's system
allocator hands any alignment above 16 to glibc's `posix_memalign`, which takes 384 B for it, against 272 B for a
plain 256-byte `malloc`, matching the 384 B per task measured; mimalloc serves the same request with no overhead
(257 B). A goroutine starts with a 2 KiB stack plus its descriptor and, while it waits on a channel, a small wait
record (2.69 KiB). An OS thread keeps its touched stack pages and thread bookkeeping resident, about 10 KiB, not
counting kernel memory.

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

1. Tokio has no MPMC channel where each message goes to one receiver (its `broadcast` channel gives every
   message to every receiver).
2. Crossbeam has no mutex.

Channel capacity is identical everywhere: 1024 for `spsc`, `mpmc` and `select`; 1 for their `-cap1` variants
and for `pingpong` (Tokio channels can't have capacity 0).

`rust/tokio-variants-bench` switches single Tokio tweaks on for comparison, e.g.
`--impls tokio,tokio+kanal,tokio+mimalloc+batch`. Its generic wrappers add per-message overhead, so its absolute
numbers are lower than `tokio-tuned`'s.

## Method

- Each run is a fresh process pinned with `taskset` to N logical CPUs, one per physical core before any SMT
  sibling. Tokio worker threads, `GOMAXPROCS` and Crossbeam's `cpu` pool are all N.
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

Requires Linux, Rust 1.98+, Go 1.27+, Python 3.10+, `taskset` and `lscpu`; numpy is optional. The published results
were built with Rust 1.98.0 and Go 1.27.0; other versions may give different numbers.

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
