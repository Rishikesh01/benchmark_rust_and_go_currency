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

> **These results predate a fairness review, and some rows are biased. Rerun before relying on them.**
> An independent code review found problems that the current code fixes but these numbers still contain:
> - **Ping-pong latency:** sampling every 16th round trip lined up with Tokio's scheduler. Tokio's p50 reads
>   190 ns instead of about 140 ns, and the 1-thread p99 for both Tokio builds is inflated (tuned: 301 ns vs
>   about 160 ns). Now every 17th.
> - **Spawn:** timed in a cold process, so Go and default Tokio paid first-touch costs (thread creation, stack
>   and page faults) inside the timer. Warm, default Tokio gets about 4M tasks/s instead of 2.6M, and tuned
>   Tokio's lead over Go at 10K tasks shrinks from 1.41× to about 1.1×. Now every implementation does one untimed
>   pass first.
> - **Lock contention:** Crossbeam used `parking_lot::Mutex`, a third-party lock, so its "3× Go" was
>   parking_lot's design. With `std::sync::Mutex` (Crossbeam has no mutex) it runs about 34M/s at 12 threads,
>   close to Go.
> - **Memory at 10K tasks:** read from `VmRSS`, which moves in per-CPU batches. It can be off by roughly
>   ±150 B per task. Now read from `smaps_rollup`, which is exact.

From [`results/full-20260916-231803`](results/full-20260916-231803/summary.md): AMD Ryzen 5 5625U laptop
(6 cores / 12 threads), 3 warm-ups + 10 measured runs, medians. The CPU governor was `powersave` and the load
average was 3.3 at the start, so some cells are noisy (marked ⚠ in `summary.md`). `summary.md` also has every
test at 1, 2 and 6 threads; spread, min/max and p99.9 latency are in `summary.csv`; charts are in `report.html`.

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

- **Tuned Tokio** is clearly fastest on 7 of the 11 cases, ahead by under 2% on `cpu`, tied with Crossbeam on
  `mutex`, and behind Go on `spawn` (1M tasks) and `select-cap1`. On `select-cap1` it is also 10–14% slower than
  default Tokio at every thread count: batched receives can't help when only one message fits. The big gains are
  on channels: 10× default Tokio on `spsc` and 7× on `mpmc` (see "Tuned Tokio" for where that comes from).
- **Default Tokio** is the slowest on `spsc`, `mpmc` and their capacity-1 versions from 2 threads up, though its
  `select!` beats both Go and Crossbeam at capacity 1024 (not at capacity 1, where Go wins). Its async
  `tokio::sync::Mutex` is about 3× slower than Go's `sync.Mutex` and about 9× slower than `parking_lot`.
- **Capacity 1** costs everyone. Among the untuned implementations Go copes best: it leads on every capacity-1
  case at 6 and 12 threads (at 2 threads Crossbeam edges it on `mpmc-cap1`, 7.19M vs 6.93M, both noisy) and is
  fastest overall on `select-cap1`, where tuned Tokio's batching can't help.
- **Crossbeam on 1 CPU** drops to 109K–154K messages/s on capacity-1 channels and ping-pong, because each message
  needs an OS thread switch. With 2 or more CPUs it has the best ping-pong tail: p99 about 300 ns, against
  320–430 ns for Go and about 2.2 µs for both Tokio versions. Tuned Tokio has the best median, 90 ns.
- **Spawning 1M tasks:** Go leads at 6 and 12 threads; tuned Tokio leads on 1 and 2 threads (6.64M and 6.19M
  tasks/s, against Go's 1.43M and 5.30M), and at every thread count with 10k tasks. Crossbeam's OS threads
  manage 18.5K–29.8K/s at 10k tasks.
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
- Plug in the charger and close heavy programs (browsers, IDE indexers, other benchmarks). The runner warns about
  battery power, load average > 1 or a non-`performance` governor, waits for background CPU to drop before each
  test, and lists tests that still started noisy in `summary.md`.
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
| `mutex` | 8 workers incrementing one counter | `sync::Mutex` | `std::sync::Mutex` ³ | `sync.Mutex` |
| `idle` | resident memory per parked task (10k / 100k / 1M) | `Semaphore` wait | blocked OS thread ² | blocked goroutine |

1. Tokio's own mpsc has a single receiver.
2. Crossbeam has no lightweight tasks. Above 20,000 threads the binary reports `skipped`.
3. Crossbeam has no mutex, so its column uses the standard library's. Results before this change used
   `parking_lot::Mutex`, which is much faster under contention and made Crossbeam look 3× faster than Go.

`spawn` does one untimed pass of the same work first, in every implementation, so the timed pass runs in a
warm process. The other workloads are long enough that first-touch costs don't matter.

### Channel capacity

Every implementation, including `tokio-tuned`, uses the same capacity in each test case:

| Test case | Capacity |
|---|---|
| `spsc`, `mpmc`, `select` (each of the two channels) | 1024 |
| `spsc-cap1`, `mpmc-cap1`, `select-cap1` | 1 |
| `pingpong` (both directions) | 1 |

Capacity 1 rather than 0 because Tokio channels can't be zero-capacity. At capacity 1 most messages are a
hand-off between tasks, so these cases mostly measure wake-up cost. That's not identical across channels,
though. In kanal and Go a receiver can take a blocked sender's value directly, so a capacity-1 channel holds
one value plus one per waiting sender. Tuned Tokio's drain loop gets about 2 messages per wake-up on
`spsc-cap1` and up to 5 on `mpmc-cap1`. Tokio's mpsc, async-channel and crossbeam-channel don't do this. They use 1M messages
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
| mimalloc | spawn 1.9× (1M tasks; 2.4× at 10K), idle memory −33% (1M; −42% at 10K), mutex −8%, other tests within noise | yes, everywhere |
| no `JoinHandle`s | spawn 0.8× alone; on top of mimalloc 1.2× at 1M tasks, 1.06× at 10K | yes, with mimalloc |
| `parking_lot::Mutex` | mutex 9.3× | yes |
| `std::sync::Mutex` | mutex 3.4× (fastest on 1 thread, slower than parking_lot from 2) | no |
| flume channels | spsc 1.1×, mpmc 0.8×, pingpong ≈1× | no |
| `unconstrained` (no co-op budget) | spsc 1.2×, pingpong and select slightly slower | no |
| both sides in one task with `join!` | spsc 1.7×, pingpong 0.6×, and no parallelism | no |
| `biased` `select!` | select 0.6× | no |

**Why tuned Tokio beats the sum of its tweaks.** `tokio-tuned` is faster than the screening build with the
same tweaks switched on. On `spsc` at 12 threads it does about 134M messages/s against 84–96M, and on
ping-pong about 7M against 6M. It isn't doing less work: same messages, same checksums. The screening build
wraps every send and receive in generic async helpers and collects batches in a `Vec`. A scratch experiment
switching those on one at a time measured 131–136M with none, about 116M with the send wrapper, and 101–106M
with both. The last ~10% wasn't isolated; it is probably code layout in the larger binary. At default Tokio's
speed (~13M/s) this overhead is invisible, which is why both builds agree there. So the screening ratios
understate tweaks that make per-message work very cheap. Default Tokio, Crossbeam and Go are written as
directly as `tokio-tuned`.

Screening only used capacity 1024, so the tweaks were never checked at capacity 1; that is how the batched
`select` made it into `tokio-tuned` although it is slower on `select-cap1`.

**kanal and cancellation.** kanal's docs say its async receive future must not be dropped once polled: a
message can be lost if it is cancelled at the wrong moment, so kanal is not correct inside `tokio::select!`,
`tokio::time::timeout` or aborted tasks. The benchmarks never cancel a kanal receive (`select` stays on
`tokio::sync::mpsc`), but real code that swaps in kanal has to avoid those patterns.

**CPU cost.** A quick ad-hoc check of CPU time (not part of the committed results) showed the kanal builds
using less CPU per message than default Tokio or Crossbeam, so the gain isn't bought with busy-waiting. From
now on every run records its CPU time (`ops_per_cpu_s` in `summary.csv`), so the next full run measures this
properly.

The screening runs were made before the variant code moved into its own crate, so their `raw.jsonl` names
the binary `tokio-bench(-mimalloc)`; the code is the same.

## How the numbers are kept comparable

- **Same CPUs:** every run is a fresh process under `taskset` with exactly N logical CPUs, picked one per
  physical core before any SMT sibling. `worker_threads`, the Crossbeam pool size and `GOMAXPROCS` are all N.
  Workloads with a fixed number of workers (e.g. 4+4 in `mpmc`) still get only N CPUs.
- **Same order effects:** warm-up runs first, then measured runs. The order of the implementations is
  shuffled every round, and the seed is saved in `meta.json`.
- **Checked results:** a run only counts if its checksum matches the expected value: closed-form for most
  workloads, and computed with numpy for `cpu`. Without numpy, the `cpu` implementations must agree with each
  other. Each binary also echoes the workload, thread count, size and every parameter it actually used
  (capacity, workers, …), and a run that differs from what was requested is rejected. A wrong checksum drops
  that implementation for the configuration.
- **Timed section:** only the workload is timed, not runtime or process startup. Crossbeam's long-lived
  workers wait at a barrier, and the first worker to start reads the clock, so OS thread creation is excluded
  just as Tokio's pre-built worker pool is. `spawn` and `idle` time thread creation on purpose. `spawn` runs
  one untimed pass first in every implementation, so thread, stack and allocator warm-up aren't timed.
- **Build settings:** Rust uses `--release` with `lto = "fat"` and `codegen-units = 1`. Go uses a default
  `go build`. Default allocators everywhere except `tokio-tuned` (mimalloc).
- **Reporting:** medians with a distribution-free confidence interval (order statistics; about 98% with 10 runs).
  A value is only bold when its interval doesn't overlap the runner-up's, so "no bold" means no clear winner.
  ⚠ marks a coefficient of variation above 5%, and a cell where some runs failed shows "(n/10)" instead of
  passing as a full median; one wrong checksum marks the whole cell invalid.
- **Run conditions:** before each test configuration the runner waits up to 10 s for other processes to use
  under 10% of CPU, and records that figure and the CPU temperature. Every run records its CPU time and context
  switches, and gets a random-length environment variable so memory-layout effects average out.
- **Traceability:** `meta.json` records the git commit (and whether the tree had uncommitted changes), toolchain
  and crate versions, CPU governor, power source and physical core count.

## Caveats

- Tokio vs Crossbeam is an async runtime vs a set of thread tools. The results show what each costs when used
  normally, not raw library speed.
- `tokio-tuned` leans on third-party crates (kanal, mimalloc, parking_lot). Crossbeam and Go were not given the
  same tuning pass.
- The mutex test's critical section is a single increment. That exaggerates differences between lock designs
  (spinning, fairness, hand-off) compared with real work under a lock.
- `idle` memory at 10K tasks is small enough that allocator reuse of memory touched before the baseline shows
  up (e.g. tuned Tokio 225 B at 10K vs 256 B at 1M); the 100K and 1M rows are more reliable.
- `cpu` also measures compiler code generation (LLVM vs Go's compiler), not only scheduling.
- Tokio's docs recommend rayon or `spawn_blocking` for CPU-heavy work; `cpu` shows the cost of using the async
  runtime anyway.
- Go numbers include its garbage collector.
- `idle` counts resident memory only. Kernel thread structures aren't included, which flatters OS threads.
- Latency is sampled every 17th round trip (every 16th in the committed results; 17 can't line up with Tokio's
  co-op budget of 128). Reading the clock (~25 ns) is inside each sample, which is a large share of a 90 ns
  round trip.
- Ping-pong is a closed loop: its latency is round-trip time at saturation, not latency under a given load.
- Up to 6 threads each thread has its own physical core; 12 threads adds the SMT siblings.
- Laptop CPUs throttle when hot, so compare runs taken under similar conditions.

## Compared with other concurrency benchmarks

How this suite lines up with established practice (sources: crossbeam-channel's
[benchmarks](https://github.com/crossbeam-rs/crossbeam/tree/master/crossbeam-channel/benchmarks), the
[kanal suite](https://github.com/fereidani/rust-channel-benchmarks), Tokio's
[benches](https://github.com/tokio-rs/tokio/tree/master/benches), Go's
[runtime/chan_test.go](https://github.com/golang/go/blob/master/src/runtime/chan_test.go) and
[benchstat](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat), [Savina](https://github.com/shamsimam/savina),
[Georges et al. 2007](https://dri.es/files/oopsla07-georges.pdf),
[pyperf](https://pyperf.readthedocs.io/en/latest/system.html) and [wrk2](https://github.com/giltene/wrk2)):

| Practice | Here |
|---|---|
| Fresh process per measurement, interleaved/shuffled order | yes |
| Thread-count sweep, CPU pinning | yes |
| Received values and parameters checked | yes (checksums, echoed parameters) |
| Warm-up inside the measured process (Criterion, kanal suite) | partly: `spawn` only; other runs are long enough |
| Median with confidence interval, no winner when intervals overlap | yes |
| CPU time and peak memory alongside throughput | yes (CPU time from now on) |
| Capacities 0 / 1 / N / unbounded | partly: 1 and 1024 (Tokio has no capacity 0) |
| Several payload sizes (kanal, Tokio `sync_mpsc`) | no: `u64` only |
| Work per message or outside the lock (Go `ChanProdConsWork`, `MutexWork`) | no: empty critical sections, which exaggerate hand-off and spinning effects |
| 20 runs per cell (benchstat) | no: 10 |
| `performance` governor, turbo/SMT off, isolated CPUs | no: warned about, not enforced (laptop) |
| Open-loop latency with a latency histogram (wrk2/HdrHistogram) | no: ping-pong is closed-loop |
| Scheduler cases such as chained spawn, yield, remote spawn (Tokio benches) | no |
| Systematic concurrency testing (loom, shuttle, `go test -race`) | no |

## Outputs

| File | Contents |
|---|---|
| `meta.json` | machine, toolchains, crate versions, git commit, governor, power, warnings, seed |
| `raw.jsonl` | every run, including warm-ups, skips and failures, with CPU time, context switches and the conditions it started under |
| `summary.csv` | one row per test case × size × threads × implementation, with confidence interval, CPU time per op, p99.9 |
| `summary.md` | every test in one table at the highest thread count, then the same table for all thread counts; clear best in bold, ⚠ for noisy results, (n/10) for incomplete cells |
| `report.html` | self-contained charts (hover for details, table view under each chart); download and open it locally, GitHub shows HTML as source |

## Adding a workload

1. Implement it in `tokio-bench`, `tokio-tuned-bench`, `crossbeam-bench` and `go/main.go`, printing
   `Report`/`okReport`.
2. Add its parameters to `WORKLOAD_PARAMS`, its sizes to both `PROFILES`, and its checksum to `expected_checksum`
   in `runner/run.py`. A new parameter set for an existing workload also needs an entry in `CASE_WORKLOAD`.
3. Add a title, description and unit to `WORKLOAD_INFO` in `runner/report.py`.
