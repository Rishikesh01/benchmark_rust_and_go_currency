# Tokio vs Tuned Tokio, Tokio channels vs Tuned Tokio vs Crossbeam vs Go

Median of 10 runs after 3 warm-ups (profile `full`, started 2026-09-19T18:24:48+05:30). **Bold** marks a clear best: its 98% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/10) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

Threads = N: pinned to N CPUs; Tokio has N worker threads, Go has `GOMAXPROCS=N`. Crossbeam runs the OS threads in its column on those CPUs. Throughput is the whole test's total, not per thread or task. Latency is per round trip, memory per idle task.

Up to 6 threads, each thread has its own physical core; above 6, threads share cores (SMT).

⚠ Run conditions: 1-minute load average was 3.25 at start; other programs compete for CPU.

## At 12 threads

### MPMC channels

Every implementation uses a bounded multi-producer, multi-consumer channel: async-channel (Tokio and tuned Tokio, Tokio channels; Tokio has none), kanal (tuned Tokio), crossbeam-channel and Go `chan`.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 8 | 8 | 9.32M ⚠ (async-channel) | 9.21M ⚠ (async-channel) | **81.0M** ⚠ | 23.3M ⚠ | 18.7M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 8 | 8 | 2.03M ⚠ (async-channel) | 1.93M (async-channel) | **19.4M** | 5.17M | 6.87M | messages/s |

### Single-receiver channels

One receiver per channel. Tokio uses its MPSC channel, `tokio::sync::mpsc` (so does tuned Tokio for select); tuned Tokio otherwise uses kanal, and Crossbeam and Go use their MPMC channels with a single receiver. Tuned Tokio, Tokio channels is tuned Tokio with `tokio::sync::mpsc` instead of kanal.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 2 | 2 | 13.2M ⚠ | 23.8M ⚠ | **137M** | 38.3M ⚠ | 29.6M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 2 | 2 | 5.13M | 5.12M | **20.5M** ⚠ | 6.76M ⚠ | 11.3M | messages/s |
| 4 senders → 1 receiver, capacity 1024 | 5 | 5 | 8.81M | 7.07M | **104M** | 35.4M ⚠ | 25.9M | messages/s |
| 4 senders → 1 receiver, capacity 1 | 5 | 5 | 5.00M | 4.92M ⚠ | **20.0M** | 5.74M | 10.1M | messages/s |
| Ping-pong | 2 | 2 | 4.46M | 4.35M | **7.51M** ⚠ | 3.86M ⚠ | 4.03M | round trips/s |
| Ping-pong latency p50 | 2 | 2 | 140 ns | 141 ns | **80 ns** | 280 ns | 241 ns | per round trip, lower is better |
| Ping-pong latency p99 | 2 | 2 | 2.17 µs | 2.15 µs | 2.13 µs | **301 ns** | 391 ns | per round trip, lower is better |
| Select over 2 channels, capacity 1024 | 3 | 3 | 20.6M | 40.6M | 40.6M | 13.8M | 13.9M | messages/s |
| Select over 2 channels, capacity 1 | 3 | 3 | 5.96M | 5.34M ⚠ | 5.37M | 7.37M ⚠ | 7.30M | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 10K | 10K | 3.87M ⚠ | 5.83M | 5.95M ⚠ | 29.2K | 5.95M ⚠ | tasks/s |
| Spawn and join, 1M tasks | 1M | — | 4.05M | 5.44M | 5.41M | skipped | **6.48M** | tasks/s |
| CPU-heavy hashing | 256 | 12 | 116M | 116M | 115M | 114M | 108M | items/s |
| Lock contention, 8 workers | 8 | 8 | 9.78M | 81.9M | 80.0M ⚠ | 31.9M | 25.6M | increments/s |
| Memory per idle task, 10K tasks | 10K | 10K | 411 B ⚠ | 245 B ⚠ | 244 B ⚠ | 9.92 KiB | 2.78 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 100K | — | 386 B | 268 B | 268 B | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 1M | — | 385 B | 257 B | 258 B | skipped | 2.69 KiB | bytes per task, lower is better |

## All thread counts

### MPMC channels

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 1 | 8 | 8 | 45.1M ⚠ (async-channel) | 44.2M (async-channel) | **136M** | 27.8M ⚠ | 35.8M | messages/s |
|  | 2 | 8 | 8 | 13.9M (async-channel) | 13.4M ⚠ (async-channel) | **111M** | 17.0M ⚠ | 23.6M |  |
|  | 6 | 8 | 8 | 8.64M ⚠ (async-channel) | 8.85M ⚠ (async-channel) | **73.3M** | 18.2M ⚠ | 20.5M |  |
|  | 12 | 8 | 8 | 9.32M ⚠ (async-channel) | 9.21M ⚠ (async-channel) | **81.0M** ⚠ | 23.3M ⚠ | 18.7M |  |
| 4 senders → 4 receivers, capacity 1 | 1 | 8 | 8 | 4.83M (async-channel) | 4.91M (async-channel) | **36.8M** | 110K | 10.7M | messages/s |
|  | 2 | 8 | 8 | 2.66M (async-channel) | 3.04M (async-channel) | **32.6M** | 5.37M ⚠ | 7.61M |  |
|  | 6 | 8 | 8 | 2.18M ⚠ (async-channel) | 1.98M (async-channel) | **20.4M** | 5.41M | 7.26M |  |
|  | 12 | 8 | 8 | 2.03M ⚠ (async-channel) | 1.93M (async-channel) | **19.4M** | 5.17M | 6.87M |  |

### Single-receiver channels

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 1 | 2 | 2 | 29.4M | 32.4M | **142M** | 46.5M ⚠ | 37.2M | messages/s |
|  | 2 | 2 | 2 | 13.1M | 23.9M | **135M** | 39.6M ⚠ | 31.0M |  |
|  | 6 | 2 | 2 | 12.9M ⚠ | 24.0M | **137M** | 38.0M ⚠ | 29.5M |  |
|  | 12 | 2 | 2 | 13.2M ⚠ | 23.8M ⚠ | **137M** | 38.3M ⚠ | 29.6M |  |
| 1 sender → 1 receiver, capacity 1 | 1 | 2 | 2 | 9.38M | 9.51M | **40.4M** | 135K | 10.8M | messages/s |
|  | 2 | 2 | 2 | 4.96M | 5.04M | **20.6M** | 6.04M | 11.4M |  |
|  | 6 | 2 | 2 | 5.13M | 5.26M | **22.2M** | 7.32M | 11.3M |  |
|  | 12 | 2 | 2 | 5.13M | 5.12M | **20.5M** ⚠ | 6.76M ⚠ | 11.3M |  |
| 4 senders → 1 receiver, capacity 1024 | 1 | 5 | 5 | 27.8M | 32.8M | **137M** | 14.6M | 36.0M | messages/s |
|  | 2 | 5 | 5 | 9.46M | 8.73M | **74.1M** ⚠ | 24.9M ⚠ | 29.8M |  |
|  | 6 | 5 | 5 | 8.34M | 6.74M | **103M** | 36.0M | 26.7M |  |
|  | 12 | 5 | 5 | 8.81M | 7.07M | **104M** | 35.4M ⚠ | 25.9M |  |
| 4 senders → 1 receiver, capacity 1 | 1 | 5 | 5 | 9.21M | 9.47M | **33.4M** | 57.5K | 10.8M | messages/s |
|  | 2 | 5 | 5 | 4.88M | 5.07M | **28.1M** | 6.07M ⚠ | 11.4M |  |
|  | 6 | 5 | 5 | 5.12M | 5.26M | **20.6M** | 5.81M | 10.6M |  |
|  | 12 | 5 | 5 | 5.00M | 4.92M ⚠ | **20.0M** | 5.74M | 10.1M |  |
| Ping-pong | 1 | 2 | 2 | 7.78M | 7.61M | **13.9M** | 135K | 3.90M | round trips/s |
|  | 2 | 2 | 2 | 4.40M | 4.27M | **7.18M** | 3.84M | 4.15M |  |
|  | 6 | 2 | 2 | 4.46M | 4.37M | **7.70M** | 3.88M | 4.04M |  |
|  | 12 | 2 | 2 | 4.46M | 4.35M | **7.51M** ⚠ | 3.86M ⚠ | 4.03M |  |
| Ping-pong latency p50 | 1 | 2 | 2 | 140 ns | 141 ns | **90 ns** | 7.35 µs | 261 ns | per round trip, lower is better |
|  | 2 | 2 | 2 | 140 ns | 141 ns | **80 ns** | 240 ns | 241 ns |  |
|  | 6 | 2 | 2 | 140 ns | 141 ns | **80 ns** | 280 ns | 241 ns |  |
|  | 12 | 2 | 2 | 140 ns | 141 ns | **80 ns** | 280 ns | 241 ns |  |
| Ping-pong latency p99 | 1 | 2 | 2 | 241 ns | 240 ns | **130 ns** | 8.52 µs | 321 ns | per round trip, lower is better |
|  | 2 | 2 | 2 | 2.20 µs | 2.17 µs | 2.15 µs | **296 ns** | 351 ns |  |
|  | 6 | 2 | 2 | 2.17 µs | 2.16 µs | 2.13 µs | **301 ns** | 386 ns |  |
|  | 12 | 2 | 2 | 2.17 µs | 2.15 µs | 2.13 µs | **301 ns** | 391 ns |  |
| Select over 2 channels, capacity 1024 | 1 | 3 | 3 | 23.1M | 36.8M | 36.8M | 11.1M | 17.9M | messages/s |
|  | 2 | 3 | 3 | 21.1M | 30.9M | 30.9M | 9.71M | 17.2M |  |
|  | 6 | 3 | 3 | 20.9M | 40.5M | 40.8M | 13.9M | 14.1M |  |
|  | 12 | 3 | 3 | 20.6M | 40.6M | 40.6M | 13.8M | 13.9M |  |
| Select over 2 channels, capacity 1 | 1 | 3 | 3 | 7.30M | 6.73M | 6.64M | 155K | 7.39M | messages/s |
|  | 2 | 3 | 3 | 4.03M ⚠ | 3.78M | 3.74M | 732K ⚠ | **7.44M** |  |
|  | 6 | 3 | 3 | 6.11M | 5.61M | 5.56M | 7.69M ⚠ | 7.36M |  |
|  | 12 | 3 | 3 | 5.96M | 5.34M ⚠ | 5.37M | 7.37M ⚠ | 7.30M |  |

### Tasks, CPU, locks and memory

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 1 | 10K | 10K | 3.90M ⚠ | 11.4M | 11.4M ⚠ | 18.2K | 1.58M ⚠ | tasks/s |
|  | 2 | 10K | 10K | 3.33M ⚠ | 6.21M | 6.05M ⚠ | 22.4K | 5.43M ⚠ |  |
|  | 6 | 10K | 10K | 3.87M | 5.53M | 5.57M | 29.9K | **6.22M** ⚠ |  |
|  | 12 | 10K | 10K | 3.87M ⚠ | 5.83M | 5.95M ⚠ | 29.2K | 5.95M ⚠ |  |
| Spawn and join, 1M tasks | 1 | 1M | — | 4.25M | 7.23M | 7.20M | skipped | 1.53M | tasks/s |
|  | 2 | 1M | — | 3.81M | 6.28M | 6.32M | skipped | 5.52M |  |
|  | 6 | 1M | — | 3.94M | 4.88M | 4.96M | skipped | **6.52M** |  |
|  | 12 | 1M | — | 4.05M | 5.44M | 5.41M | skipped | **6.48M** |  |
| CPU-heavy hashing | 1 | 256 | 1 | 13.7M | 13.7M | 13.7M | 13.6M | 13.2M | items/s |
|  | 2 | 256 | 2 | 27.4M | 27.4M | 27.4M | 27.2M | 26.5M |  |
|  | 6 | 256 | 6 | 78.3M | 78.4M | 78.0M | 77.9M | 73.9M |  |
|  | 12 | 256 | 12 | 116M | 116M | 115M | 114M | 108M |  |
| Lock contention, 8 workers | 1 | 8 | 8 | 50.3M | 230M | 230M | **267M** | 249M | increments/s |
|  | 2 | 8 | 8 | 9.56M | 153M | 154M | 48.4M ⚠ | 65.5M ⚠ |  |
|  | 6 | 8 | 8 | 9.96M | 74.7M | 75.4M | 35.9M | 22.7M |  |
|  | 12 | 8 | 8 | 9.78M | 81.9M | 80.0M ⚠ | 31.9M | 25.6M |  |
| Memory per idle task, 10K tasks | 12 | 10K | 10K | 411 B ⚠ | 245 B ⚠ | 244 B ⚠ | 9.92 KiB | 2.78 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 12 | 100K | — | 386 B | 268 B | 268 B | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 12 | 1M | — | 385 B | 257 B | 258 B | skipped | 2.69 KiB | bytes per task, lower is better |

## Notes

- Crossbeam skipped (one OS thread per task; capped at 20000): Spawn and join, 1M tasks; Memory per idle task, 100K tasks; Memory per idle task, 1M tasks
- CPU temperature before each config: 58–84 °C
- **Run:** profile `full`, started 2026-09-19T18:24:48+05:30, seed 880417669
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor performance
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 14,677 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, flume 0.12.0, kanal 0.1.1, mimalloc 0.1.52, parking_lot 0.12.5, tokio 1.53.1
