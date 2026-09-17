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

From [`results/full-20260917-103559`](results/full-20260917-103559/summary.md): AMD Ryzen 5 5625U laptop
(6 cores / 12 threads), `performance` governor, on AC power, code at commit `8e4c12b`. 3 warm-ups + 10 measured
runs; medians. Background CPU measured before each test stayed at 0.5–6.8%. The CPU reached 84 °C, so
the CPU-heavy row probably includes thermal throttling. **Bold** marks a clear best: its confidence interval
doesn't overlap the runner-up's. Every thread count, confidence intervals, CPU time and p99.9 latency are in
`summary.md` / `summary.csv`.

At 12 threads:

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---|
| 1 sender → 1 receiver, capacity 1024 | 13.1M | **135M** | 37.1M | 29.3M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 4.91M | **19.7M** | 7.10M | 10.5M | messages/s |
| 4 senders → 4 receivers, capacity 1024 | 9.78M | **81.1M** | 26.5M | 18.7M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 2.08M | **19.2M** | 5.14M | 6.62M | messages/s |
| Ping-pong | 4.31M | **7.04M** | 3.86M | 3.91M | round trips/s |
| Ping-pong latency p50 | 140 ns | **90 ns** | 280 ns | 250 ns | per round trip, lower is better |
| Ping-pong latency p99 | 2.18 µs | 2.17 µs | **341 ns** | 516 ns | per round trip, lower is better |
| Spawn and join, 10K tasks | 3.87M | 5.87M | 28.2K | 5.32M | tasks/s |
| Spawn and join, 1M tasks | 3.56M | 5.31M | skipped | **5.59M** | tasks/s |
| CPU-heavy hashing | 99.0M | 99.1M | 99.7M | 90.7M | items/s |
| Select over 2 channels, capacity 1024 | 20.0M | **36.9M** | 13.3M | 13.8M | messages/s |
| Select over 2 channels, capacity 1 | 5.43M | 4.91M | 5.77M | **7.09M** | messages/s |
| Lock contention, 8 workers | 8.98M | **74.8M** | 29.4M | 25.8M | increments/s |
| Memory per idle task, 10K tasks | 408 B | **261 B** | 9.92 KiB | 2.79 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 385 B | **258 B** | skipped ¹ | 2.69 KiB | bytes per task, lower is better |

1. Crossbeam runs one OS thread per task and stops at 20,000. This cell reads "error" in `summary.md` because
   the runner's memory guard skipped it first; the runner now records that as a skip.

**Default Tokio, Crossbeam and Go:**
- **Channels with room to buffer (capacity 1024):** Crossbeam is fastest (37.1M on 1 → 1, 26.5M on 4 → 4),
  Go second (29.3M, 18.7M), default Tokio last (13.1M, 9.78M).
- **Capacity 1:** Go is the fastest of the three on all three capacity-1 tests at every thread count from 2 up,
  e.g. 1 → 1 at 12 threads: Go 10.5M, Crossbeam 7.10M, Tokio 4.91M.
- **Ping-pong:** Tokio does the most round trips (4.31M) with the lowest median latency (140 ns vs Go 250 ns,
  Crossbeam 280 ns). Crossbeam has the best tail from 2 threads up (p99 331–346 ns, Go 441–516 ns, Tokio about
  2.2 µs). On 1 CPU Crossbeam collapses to 134K round trips/s because each hop is an OS thread switch.
- **Select at capacity 1024:** Tokio 20.0M, well ahead of Go (13.8M) and Crossbeam (13.3M).
- **Spawn:** Go leads at 12 threads (5.59M tasks/s at 1M tasks vs Tokio 3.56M); on 1 thread Tokio leads (3.80M
  vs Go 1.25M). Crossbeam's OS threads manage 18K–29K/s.
- **Lock contention:** Crossbeam's `std::sync::Mutex` (29.4M) and Go's `sync.Mutex` (25.8M) are close; Tokio's
  async mutex is about 3× slower (8.98M).
- **CPU-heavy:** Tokio and Crossbeam tie at about 99M items/s; Go is about 9% behind.
- **Memory per idle task:** Tokio 385 B, Go 2.69 KiB (about 7×), a Crossbeam OS thread 9.92 KiB (about 25× Tokio
  at 10K tasks, not counting kernel memory).

**Tuned Tokio** is the clear best on 10 of the 15 rows. Against default Tokio: 10× on 1 → 1, 8× on 4 → 4, 4× and
9× on their capacity-1 versions, 1.8× on select, 8× on lock contention, 1.5× on spawning 1M tasks, and a third
less memory per idle task. Where it doesn't win:
- **Select at capacity 1:** 5–10% slower than default Tokio at every thread count; batching can't help a 1-slot
  channel.
- **Ping-pong tail:** p99 is about 2.2 µs from 2 threads up, the same as default Tokio.
- **Spawn:** no clear winner against Go at 10K tasks; Go leads at 6 and 12 threads with 1M tasks.
- **CPU-heavy:** no gain; the loop doesn't allocate.

**What the fairness fixes changed**, compared with the earlier run in `results/full-20260916-231803` (same machine,
`powersave` governor, older code):
- Tokio ping-pong p50 190 → 140 ns, and tuned Tokio's 1-thread p99 301 → 166 ns (sampling no longer aliases).
- Default Tokio spawning 1M tasks at 12 threads 2.59M → 3.56M/s, and Go at 10K tasks 4.14M → 5.32M/s (untimed
  warm-up pass). Tuned Tokio's lead over Go at 10K tasks went from 1.41× to no clear winner.
- Crossbeam lock contention at 12 threads 81.6M → 29.4M (`std::sync::Mutex` instead of `parking_lot`), level with
  Go.
- Tuned Tokio memory at 10K tasks 225 → 261 B (exact RSS), now in line with its 1M-task figure.
- Not from the fixes: CPU-heavy at 12 threads 115M → 99M for every implementation, most likely throttling under
  the `performance` governor.

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
