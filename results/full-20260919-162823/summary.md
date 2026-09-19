# Tokio vs Tuned Tokio, Tokio channels vs Tuned Tokio vs Crossbeam vs Go

Median of 10 runs after 3 warm-ups (profile `full`, started 2026-09-19T16:28:24+05:30). **Bold** marks a clear best: its 98% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/10) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

Threads = N: pinned to N CPUs; Tokio has N worker threads, Go has `GOMAXPROCS=N`. Crossbeam runs the OS threads in its column on those CPUs. Throughput is the whole test's total, not per thread or task. Latency is per round trip, memory per idle task.

Up to 6 threads, each thread has its own physical core; above 6, threads share cores (SMT).

⚠ Run conditions: 1-minute load average was 3.35 at start; other programs compete for CPU.

## At 12 threads

### MPMC channels

Every implementation uses a bounded multi-producer, multi-consumer channel: async-channel (Tokio), kanal (tuned Tokio), crossbeam-channel and Go `chan`.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 8 | 8 | 9.29M ⚠ | **82.0M** ⚠ | 29.8M ⚠ | 18.7M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 8 | 8 | 2.03M ⚠ | **19.1M** | 5.19M | 6.73M | messages/s |

### Single-receiver channels

One receiver per channel. Tokio uses its MPSC channel, `tokio::sync::mpsc` (so does tuned Tokio for select); tuned Tokio otherwise uses kanal, and Crossbeam and Go use their MPMC channels with a single receiver. Tuned Tokio, Tokio channels is tuned Tokio with `tokio::sync::mpsc` instead of kanal.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 2 | 2 | 13.0M ⚠ | 24.1M | **138M** | 37.1M ⚠ | 29.6M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 2 | 2 | 5.10M | 5.38M | **21.2M** ⚠ | 7.10M ⚠ | 11.3M | messages/s |
| 4 senders → 1 receiver, capacity 1024 | 5 | 5 | 8.93M | 6.78M | **110M** | 37.9M ⚠ | 26.1M | messages/s |
| 4 senders → 1 receiver, capacity 1 | 5 | 5 | 5.00M | 5.40M | **20.1M** | 5.90M | 10.2M | messages/s |
| Ping-pong | 2 | 2 | 4.46M | 4.52M | **7.49M** | 3.86M ⚠ | 4.02M | round trips/s |
| Ping-pong latency p50 | 2 | 2 | 140 ns | 131 ns | **80 ns** | 276 ns | 241 ns | per round trip, lower is better |
| Ping-pong latency p99 | 2 | 2 | 2.18 µs | 2.17 µs | 2.15 µs | **301 ns** | 420 ns | per round trip, lower is better |
| Select over 2 channels, capacity 1024 | 3 | 3 | 20.7M | — | **42.0M** | 13.7M | 14.2M | messages/s |
| Select over 2 channels, capacity 1 | 3 | 3 | 5.96M | — | 5.81M | 8.11M ⚠ | 7.32M | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 10K | 10K | 3.87M ⚠ | 6.10M ⚠ | 29.0K | 6.10M ⚠ | tasks/s |
| Spawn and join, 1M tasks | 1M | — | 4.11M ⚠ | 5.40M | skipped | **6.45M** | tasks/s |
| CPU-heavy hashing | 256 | 12 | 116M | 116M | 114M | 108M | items/s |
| Lock contention, 8 workers | 8 | 8 | 9.69M | **79.0M** ⚠ | 32.4M | 26.0M | increments/s |
| Memory per idle task, 10K tasks | 10K | 10K | 406 B ⚠ | 236 B ⚠ | 9.93 KiB | 2.78 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 100K | — | 386 B | **254 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 1M | — | 384 B | **258 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## All thread counts

### MPMC channels

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 1 | 8 | 8 | 46.2M | **140M** | 40.2M ⚠ | 36.4M | messages/s |
|  | 2 | 8 | 8 | 13.7M | **105M** | 18.8M ⚠ | 23.6M |  |
|  | 6 | 8 | 8 | 8.53M ⚠ | **71.1M** | 20.8M ⚠ | 20.5M |  |
|  | 12 | 8 | 8 | 9.29M ⚠ | **82.0M** ⚠ | 29.8M ⚠ | 18.7M |  |
| 4 senders → 4 receivers, capacity 1 | 1 | 8 | 8 | 4.91M | **37.9M** | 110K | 10.9M | messages/s |
|  | 2 | 8 | 8 | 2.69M | **32.2M** | 5.92M ⚠ | 7.57M |  |
|  | 6 | 8 | 8 | 2.15M ⚠ | **20.3M** | 5.61M | 7.62M |  |
|  | 12 | 8 | 8 | 2.03M ⚠ | **19.1M** | 5.19M | 6.73M |  |

### Single-receiver channels

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 1 | 2 | 2 | 29.5M | 32.7M | **143M** | 46.4M ⚠ | 37.2M | messages/s |
|  | 2 | 2 | 2 | 13.2M | 23.4M | **137M** | 41.2M | 31.2M |  |
|  | 6 | 2 | 2 | 13.2M ⚠ | 24.1M | **138M** | 36.1M ⚠ | 29.6M |  |
|  | 12 | 2 | 2 | 13.0M ⚠ | 24.1M | **138M** | 37.1M ⚠ | 29.6M |  |
| 1 sender → 1 receiver, capacity 1 | 1 | 2 | 2 | 9.59M | 9.95M | **41.3M** | 135K | 10.9M | messages/s |
|  | 2 | 2 | 2 | 4.95M | 5.21M | **20.3M** | 5.75M ⚠ | 11.5M |  |
|  | 6 | 2 | 2 | 5.16M | 5.43M ⚠ | **22.2M** | 6.90M ⚠ | 11.4M |  |
|  | 12 | 2 | 2 | 5.10M | 5.38M | **21.2M** ⚠ | 7.10M ⚠ | 11.3M |  |
| 4 senders → 1 receiver, capacity 1024 | 1 | 5 | 5 | 28.5M | 34.1M | **140M** | 14.4M | 36.8M | messages/s |
|  | 2 | 5 | 5 | 9.39M | 8.67M | **70.0M** | 24.9M ⚠ | 29.9M |  |
|  | 6 | 5 | 5 | 8.36M | 6.48M | **110M** ⚠ | 37.8M ⚠ | 26.9M |  |
|  | 12 | 5 | 5 | 8.93M | 6.78M | **110M** | 37.9M ⚠ | 26.1M |  |
| 4 senders → 1 receiver, capacity 1 | 1 | 5 | 5 | 9.39M | 9.84M | **34.1M** | 56.9K | 11.0M | messages/s |
|  | 2 | 5 | 5 | 4.87M | 5.09M | **28.3M** | 6.38M ⚠ | 11.5M |  |
|  | 6 | 5 | 5 | 5.10M | 5.38M | **20.7M** | 5.99M | 10.6M |  |
|  | 12 | 5 | 5 | 5.00M | 5.40M | **20.1M** | 5.90M | 10.2M |  |
| Ping-pong | 1 | 2 | 2 | 8.12M ⚠ | 8.29M | **14.3M** | 135K | 3.97M | round trips/s |
|  | 2 | 2 | 2 | 4.37M | 4.44M | **7.16M** | 3.84M | 4.14M |  |
|  | 6 | 2 | 2 | 4.45M | 4.58M | **7.71M** | 3.93M ⚠ | 4.05M |  |
|  | 12 | 2 | 2 | 4.46M | 4.52M | **7.49M** | 3.86M ⚠ | 4.02M |  |
| Ping-pong latency p50 | 1 | 2 | 2 | 136 ns | 130 ns | **80 ns** | 7.39 µs | 261 ns | per round trip, lower is better |
|  | 2 | 2 | 2 | 140 ns | 131 ns | **80 ns** | 240 ns | 241 ns |  |
|  | 6 | 2 | 2 | 140 ns | 131 ns | **80 ns** | 281 ns | 241 ns |  |
|  | 12 | 2 | 2 | 140 ns | 131 ns | **80 ns** | 276 ns | 241 ns |  |
| Ping-pong latency p99 | 1 | 2 | 2 | 236 ns | 231 ns | **131 ns** | 7.93 µs | 326 ns | per round trip, lower is better |
|  | 2 | 2 | 2 | 2.22 µs | 2.19 µs | 2.18 µs | **291 ns** | 356 ns |  |
|  | 6 | 2 | 2 | 2.19 µs | 2.16 µs | 2.16 µs | **301 ns** | 386 ns |  |
|  | 12 | 2 | 2 | 2.18 µs | 2.17 µs | 2.15 µs | **301 ns** | 420 ns |  |
| Select over 2 channels, capacity 1024 | 1 | 3 | 3 | 23.9M ⚠ | — | **38.3M** | 11.1M | 18.4M | messages/s |
|  | 2 | 3 | 3 | 21.5M | — | **31.6M** | 9.72M | 17.7M |  |
|  | 6 | 3 | 3 | 21.6M | — | **42.6M** | 13.6M | 14.5M |  |
|  | 12 | 3 | 3 | 20.7M | — | **42.0M** | 13.7M | 14.2M |  |
| Select over 2 channels, capacity 1 | 1 | 3 | 3 | 7.48M | — | 7.23M | 153K | 7.39M | messages/s |
|  | 2 | 3 | 3 | 4.02M | — | 3.82M | 929K ⚠ | **7.44M** |  |
|  | 6 | 3 | 3 | 6.14M | — | 5.95M | 7.65M ⚠ | 7.33M |  |
|  | 12 | 3 | 3 | 5.96M | — | 5.81M | 8.11M ⚠ | 7.32M |  |

### Tasks, CPU, locks and memory

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 1 | 10K | 10K | 3.92M ⚠ | **11.6M** | 17.9K | 1.59M ⚠ | tasks/s |
|  | 2 | 10K | 10K | 3.32M ⚠ | 6.29M ⚠ | 21.5K | 5.36M ⚠ |  |
|  | 6 | 10K | 10K | 3.86M ⚠ | 5.51M ⚠ | 29.8K | 6.12M ⚠ |  |
|  | 12 | 10K | 10K | 3.87M ⚠ | 6.10M ⚠ | 29.0K | 6.10M ⚠ |  |
| Spawn and join, 1M tasks | 1 | 1M | — | 4.39M | **7.65M** | skipped | 1.56M | tasks/s |
|  | 2 | 1M | — | 3.85M | **6.28M** | skipped | 5.48M |  |
|  | 6 | 1M | — | 4.01M | 4.96M | skipped | **6.57M** |  |
|  | 12 | 1M | — | 4.11M ⚠ | 5.40M | skipped | **6.45M** |  |
| CPU-heavy hashing | 1 | 256 | 1 | 13.7M | 13.7M | 13.6M | 13.2M | items/s |
|  | 2 | 256 | 2 | 27.4M | 27.4M | 27.2M | 26.5M |  |
|  | 6 | 256 | 6 | 79.3M | 79.3M | 78.7M | 75.3M |  |
|  | 12 | 256 | 12 | 116M | 116M | 114M | 108M |  |
| Lock contention, 8 workers | 1 | 8 | 8 | 52.3M | 231M | **267M** | 251M | increments/s |
|  | 2 | 8 | 8 | 9.52M ⚠ | **161M** | 45.9M ⚠ | 68.6M ⚠ |  |
|  | 6 | 8 | 8 | 9.97M ⚠ | **77.3M** | 36.1M | 23.0M |  |
|  | 12 | 8 | 8 | 9.69M | **79.0M** ⚠ | 32.4M | 26.0M |  |
| Memory per idle task, 10K tasks | 12 | 10K | 10K | 406 B ⚠ | 236 B ⚠ | 9.93 KiB | 2.78 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 12 | 100K | — | 386 B | **254 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 12 | 1M | — | 384 B | **258 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## Notes

- Crossbeam skipped (one OS thread per task; capped at 20000): Spawn and join, 1M tasks; Memory per idle task, 100K tasks; Memory per idle task, 1M tasks
- CPU temperature before each config: 58–83 °C
- **Run:** profile `full`, started 2026-09-19T16:28:24+05:30, seed 831920737
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor performance
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 16,879 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, flume 0.12.0, kanal 0.1.1, mimalloc 0.1.52, parking_lot 0.12.5, tokio 1.53.1
