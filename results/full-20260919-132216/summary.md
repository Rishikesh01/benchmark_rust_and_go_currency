# Tokio vs Tuned Tokio, Tokio channels vs Tuned Tokio vs Crossbeam vs Go

Median of 10 runs after 3 warm-ups (profile `full`, started 2026-09-19T13:22:16+05:30). **Bold** marks a clear best: its 98% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/10) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

Threads = N: pinned to N CPUs; Tokio has N worker threads, Go has `GOMAXPROCS=N`. Crossbeam runs the OS threads in its column on those CPUs. Throughput is the whole test's total, not per thread or task. Latency is per round trip, memory per idle task.

Up to 6 threads, each thread has its own physical core; above 6, threads share cores (SMT).

⚠ Run conditions: 1-minute load average was 1.93 at start; other programs compete for CPU.

## At 12 threads

### MPMC channels

Every implementation uses a bounded multi-producer, multi-consumer channel: async-channel (Tokio), kanal (tuned Tokio), crossbeam-channel and Go `chan`.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 8 | 8 | 9.22M ⚠ | **77.5M** ⚠ | 30.5M ⚠ | 18.8M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 8 | 8 | 2.12M ⚠ | **19.1M** | 5.20M | 6.61M | messages/s |

### Single-receiver channels

One receiver per channel. Tokio uses its MPSC channel, `tokio::sync::mpsc` (so does tuned Tokio for select); tuned Tokio otherwise uses kanal, and Crossbeam and Go use their MPMC channels with a single receiver. Tuned Tokio, Tokio channels is tuned Tokio with `tokio::sync::mpsc` instead of kanal.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 2 | 2 | 12.8M ⚠ | 23.5M | **133M** | 36.3M ⚠ | 29.3M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 2 | 2 | 5.42M | 5.27M ⚠ | **21.3M** ⚠ | 7.15M | 11.3M | messages/s |
| 4 senders → 1 receiver, capacity 1024 | 5 | 5 | 8.59M | 6.81M | **99.4M** ⚠ | 39.1M ⚠ | 26.4M | messages/s |
| 4 senders → 1 receiver, capacity 1 | 5 | 5 | 4.87M ⚠ | 5.01M | **19.5M** ⚠ | 5.78M | 10.1M | messages/s |
| Ping-pong | 2 | 2 | 4.10M | 4.56M ⚠ | **7.49M** ⚠ | 3.82M ⚠ | 3.86M | round trips/s |
| Ping-pong latency p50 | 2 | 2 | 150 ns | 131 ns | **81 ns** | 280 ns | 251 ns | per round trip, lower is better |
| Ping-pong latency p99 | 2 | 2 | 2.18 µs | 2.16 µs | 2.13 µs | **301 ns** | 416 ns | per round trip, lower is better |
| Select over 2 channels, capacity 1024 | 3 | 3 | 20.4M | — | **37.8M** ⚠ | 13.5M | 14.0M | messages/s |
| Select over 2 channels, capacity 1 | 3 | 3 | 5.77M | — | 5.21M | 6.81M ⚠ | 7.15M | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 10K | 10K | 3.86M ⚠ | 5.93M ⚠ | 29.7K | 5.53M | tasks/s |
| Spawn and join, 1M tasks | 1M | — | 3.96M ⚠ | 5.42M | skipped | **5.91M** | tasks/s |
| CPU-heavy hashing | 256 | 12 | 116M | 115M | 115M | 109M | items/s |
| Lock contention, 8 workers | 8 | 8 | 9.74M | **83.5M** ⚠ | 32.2M | 27.1M | increments/s |
| Memory per idle task, 10K tasks | 10K | 10K | 411 B ⚠ | **367 B** ⚠ | 9.92 KiB | 2.81 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 100K | — | 387 B | **267 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 1M | — | 385 B | **258 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## All thread counts

### MPMC channels

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 1 | 8 | 8 | 44.9M | **134M** | 45.1M ⚠ | 35.8M | messages/s |
|  | 2 | 8 | 8 | 13.9M | **106M** | 25.7M ⚠ | 24.2M |  |
|  | 6 | 8 | 8 | 8.97M ⚠ | **72.9M** | 20.1M ⚠ | 20.7M |  |
|  | 12 | 8 | 8 | 9.22M ⚠ | **77.5M** ⚠ | 30.5M ⚠ | 18.8M |  |
| 4 senders → 4 receivers, capacity 1 | 1 | 8 | 8 | 4.88M | **36.7M** | 111K | 10.7M | messages/s |
|  | 2 | 8 | 8 | 2.63M | **32.3M** | 6.87M ⚠ | 7.52M |  |
|  | 6 | 8 | 8 | 2.25M ⚠ | **20.1M** | 5.47M | 7.47M |  |
|  | 12 | 8 | 8 | 2.12M ⚠ | **19.1M** | 5.20M | 6.61M |  |

### Single-receiver channels

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 1 | 2 | 2 | 29.4M | 33.0M | **142M** | 48.5M ⚠ | 37.4M ⚠ | messages/s |
|  | 2 | 2 | 2 | 13.6M ⚠ | 23.8M | **134M** | 40.2M | 31.2M |  |
|  | 6 | 2 | 2 | 13.0M ⚠ | 24.4M | **136M** | 35.4M ⚠ | 29.2M |  |
|  | 12 | 2 | 2 | 12.8M ⚠ | 23.5M | **133M** | 36.3M ⚠ | 29.3M |  |
| 1 sender → 1 receiver, capacity 1 | 1 | 2 | 2 | 9.84M | 9.33M | **39.5M** | 135K | 10.8M | messages/s |
|  | 2 | 2 | 2 | 5.20M | 5.09M | **20.3M** | 5.64M ⚠ | 11.5M |  |
|  | 6 | 2 | 2 | 5.45M | 5.27M | **22.0M** | 7.30M ⚠ | 11.3M |  |
|  | 12 | 2 | 2 | 5.42M | 5.27M ⚠ | **21.3M** ⚠ | 7.15M | 11.3M |  |
| 4 senders → 1 receiver, capacity 1024 | 1 | 5 | 5 | 27.4M | 33.2M | **136M** | 14.8M | 36.4M | messages/s |
|  | 2 | 5 | 5 | 9.32M | 8.63M | **69.3M** ⚠ | 20.5M ⚠ | 30.4M |  |
|  | 6 | 5 | 5 | 8.04M | 6.43M | **99.4M** ⚠ | 37.9M ⚠ | 27.3M |  |
|  | 12 | 5 | 5 | 8.59M | 6.81M | **99.4M** ⚠ | 39.1M ⚠ | 26.4M |  |
| 4 senders → 1 receiver, capacity 1 | 1 | 5 | 5 | 9.62M ⚠ | 9.26M | **33.0M** | 57.3K | 10.8M | messages/s |
|  | 2 | 5 | 5 | 5.12M | 5.01M | **27.8M** | 6.27M ⚠ | 11.5M |  |
|  | 6 | 5 | 5 | 5.36M | 5.16M | **20.6M** | 5.94M | 10.7M |  |
|  | 12 | 5 | 5 | 4.87M ⚠ | 5.01M | **19.5M** ⚠ | 5.78M | 10.1M |  |
| Ping-pong | 1 | 2 | 2 | 7.27M | 8.03M | **13.8M** | 135K | 3.81M | round trips/s |
|  | 2 | 2 | 2 | 4.08M ⚠ | 4.54M | **7.26M** | 3.82M | 3.99M |  |
|  | 6 | 2 | 2 | 4.16M | 4.60M | **7.75M** | 3.88M | 3.90M |  |
|  | 12 | 2 | 2 | 4.10M | 4.56M ⚠ | **7.49M** ⚠ | 3.82M ⚠ | 3.86M |  |
| Ping-pong latency p50 | 1 | 2 | 2 | 141 ns | 136 ns | **90 ns** | 7.38 µs | 270 ns | per round trip, lower is better |
|  | 2 | 2 | 2 | 141 ns | 130 ns | **81 ns** | 231 ns | 250 ns |  |
|  | 6 | 2 | 2 | 141 ns | 131 ns | **81 ns** | 286 ns | 250 ns |  |
|  | 12 | 2 | 2 | 150 ns | 131 ns | **81 ns** | 280 ns | 251 ns |  |
| Ping-pong latency p99 | 1 | 2 | 2 | 270 ns | 236 ns | **140 ns** | 8.52 µs | 340 ns | per round trip, lower is better |
|  | 2 | 2 | 2 | 2.21 µs | 2.17 µs | 2.15 µs | **291 ns** | 361 ns |  |
|  | 6 | 2 | 2 | 2.18 µs | 2.19 µs | 2.12 µs | **301 ns** | 401 ns |  |
|  | 12 | 2 | 2 | 2.18 µs | 2.16 µs | 2.13 µs | **301 ns** | 416 ns |  |
| Select over 2 channels, capacity 1024 | 1 | 3 | 3 | 23.2M | — | **37.1M** | 11.1M | 17.6M | messages/s |
|  | 2 | 3 | 3 | 21.0M ⚠ | — | **30.4M** | 9.16M | 17.0M |  |
|  | 6 | 3 | 3 | 21.1M | — | **41.1M** | 13.4M | 14.3M |  |
|  | 12 | 3 | 3 | 20.4M | — | **37.8M** ⚠ | 13.5M | 14.0M |  |
| Select over 2 channels, capacity 1 | 1 | 3 | 3 | 7.29M | — | 6.60M | 154K | 7.18M | messages/s |
|  | 2 | 3 | 3 | 3.98M | — | 3.72M | 1.68M ⚠ | **7.38M** |  |
|  | 6 | 3 | 3 | 5.87M | — | 5.56M | 6.33M ⚠ | **7.23M** |  |
|  | 12 | 3 | 3 | 5.77M | — | 5.21M | 6.81M ⚠ | 7.15M |  |

### Tasks, CPU, locks and memory

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 1 | 10K | 10K | 3.91M ⚠ | **11.5M** | 18.0K | 1.36M ⚠ | tasks/s |
|  | 2 | 10K | 10K | 3.35M ⚠ | 6.22M ⚠ | 21.7K | 5.00M |  |
|  | 6 | 10K | 10K | 3.83M ⚠ | 5.52M ⚠ | 30.3K | 5.68M |  |
|  | 12 | 10K | 10K | 3.86M ⚠ | 5.93M ⚠ | 29.7K | 5.53M |  |
| Spawn and join, 1M tasks | 1 | 1M | — | 4.14M | **7.20M** | skipped | 1.47M | tasks/s |
|  | 2 | 1M | — | 3.65M | **6.23M** | skipped | 5.31M |  |
|  | 6 | 1M | — | 3.92M | 5.00M | skipped | **6.04M** |  |
|  | 12 | 1M | — | 3.96M ⚠ | 5.42M | skipped | **5.91M** |  |
| CPU-heavy hashing | 1 | 256 | 1 | 13.7M | **13.8M** | 13.7M | 13.0M | items/s |
|  | 2 | 256 | 2 | 27.4M | **27.5M** | 27.4M | 25.9M |  |
|  | 6 | 256 | 6 | 77.8M | 78.8M | 78.2M | 71.6M |  |
|  | 12 | 256 | 12 | 116M | 115M | 115M | 109M |  |
| Lock contention, 8 workers | 1 | 8 | 8 | 51.4M | 231M | **266M** | 259M | increments/s |
|  | 2 | 8 | 8 | 9.53M | **148M** | 46.9M ⚠ | 57.3M ⚠ |  |
|  | 6 | 8 | 8 | 9.97M | **82.2M** | 35.6M | 23.5M ⚠ |  |
|  | 12 | 8 | 8 | 9.74M | **83.5M** ⚠ | 32.2M | 27.1M |  |
| Memory per idle task, 10K tasks | 12 | 10K | 10K | 411 B ⚠ | **367 B** ⚠ | 9.92 KiB | 2.81 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 12 | 100K | — | 387 B | **267 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 12 | 1M | — | 385 B | **258 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## Notes

- Crossbeam skipped (one OS thread per task; capped at 20000): Spawn and join, 1M tasks; Memory per idle task, 100K tasks
- Crossbeam skipped (runner: not enough free memory): Memory per idle task, 1M tasks
- CPU temperature before each config: 56–84 °C
- **Run:** profile `full`, started 2026-09-19T13:22:16+05:30, seed 3612073912
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor performance
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 13,985 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, flume 0.12.0, kanal 0.1.1, mimalloc 0.1.52, parking_lot 0.12.5, tokio 1.53.1
