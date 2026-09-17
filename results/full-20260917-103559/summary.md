# Tokio vs Tuned Tokio vs Crossbeam vs Go

Median of 10 runs after 3 warm-ups (profile `full`, started 2026-09-17T10:35:59+05:30). **Bold** marks a clear best: its 98% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/10) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

Up to 6 threads, each thread has its own physical core; above 6, threads share cores (SMT).

⚠ Run conditions: 1-minute load average was 2.22 at start; other programs compete for CPU.

## At 12 threads

### MPMC channels

Every implementation uses a bounded multi-producer, multi-consumer channel: async-channel (Tokio), kanal (tuned Tokio), crossbeam-channel and Go `chan`.

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 9.78M ⚠ | **81.1M** ⚠ | 26.5M ⚠ | 18.7M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 2.08M ⚠ | **19.2M** | 5.14M | 6.62M ⚠ | messages/s |

### Single-receiver channels

One receiver per channel. Tokio uses its MPSC channel, `tokio::sync::mpsc` (so does tuned Tokio for select); tuned Tokio otherwise uses kanal, and Crossbeam and Go use their MPMC channels with a single receiver.

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 13.1M ⚠ | **135M** | 37.1M ⚠ | 29.3M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 4.91M | **19.7M** | 7.10M ⚠ | 10.5M | messages/s |
| Ping-pong | 4.31M | **7.04M** ⚠ | 3.86M ⚠ | 3.91M | round trips/s |
| Ping-pong latency p50 | 140 ns | **90 ns** | 280 ns | 250 ns | per round trip, lower is better |
| Ping-pong latency p99 | 2.18 µs | 2.17 µs | **341 ns** | 516 ns | per round trip, lower is better |
| Select over 2 channels, capacity 1024 | 20.0M | **36.9M** | 13.3M | 13.8M | messages/s |
| Select over 2 channels, capacity 1 | 5.43M | 4.91M | 5.77M ⚠ | **7.09M** | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 3.87M ⚠ | 5.87M ⚠ | 28.2K ⚠ | 5.32M ⚠ | tasks/s |
| Spawn and join, 1M tasks | 3.56M ⚠ | 5.31M | skipped | **5.59M** ⚠ | tasks/s |
| CPU-heavy hashing | 99.0M | 99.1M | 99.7M | 90.7M | items/s |
| Lock contention, 8 workers | 8.98M | **74.8M** ⚠ | 29.4M | 25.8M | increments/s |
| Memory per idle task, 10K tasks | 408 B ⚠ | **261 B** ⚠ | 9.92 KiB | 2.79 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 386 B | **259 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 385 B | **258 B** | error | 2.69 KiB | bytes per task, lower is better |

## All thread counts

### MPMC channels

| Test | Threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 1 | 44.2M | **131M** | 42.0M ⚠ | 35.2M | messages/s |
|  | 2 | 13.8M | **105M** | 21.4M ⚠ | 23.7M ⚠ |  |
|  | 6 | 9.45M ⚠ | **72.1M** | 20.7M ⚠ | 20.7M |  |
|  | 12 | 9.78M ⚠ | **81.1M** ⚠ | 26.5M ⚠ | 18.7M |  |
| 4 senders → 4 receivers, capacity 1 | 1 | 4.99M | **36.7M** | 111K | 10.5M | messages/s |
|  | 2 | 2.57M | **33.0M** | 6.19M ⚠ | 7.45M |  |
|  | 6 | 2.09M ⚠ | **19.6M** | 5.50M | 7.47M |  |
|  | 12 | 2.08M ⚠ | **19.2M** | 5.14M | 6.62M ⚠ |  |

### Single-receiver channels

| Test | Threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 1 | 28.7M | **137M** | 46.4M ⚠ | 35.8M | messages/s |
|  | 2 | 13.4M | **133M** | 39.6M ⚠ | 31.2M |  |
|  | 6 | 12.5M ⚠ | **135M** | 36.5M ⚠ | 29.4M |  |
|  | 12 | 13.1M ⚠ | **135M** | 37.1M ⚠ | 29.3M |  |
| 1 sender → 1 receiver, capacity 1 | 1 | 9.18M | **39.9M** ⚠ | 136K | 10.5M | messages/s |
|  | 2 | 4.88M | **20.7M** | 5.95M | 11.1M |  |
|  | 6 | 5.17M | **22.2M** | 7.51M ⚠ | 11.1M |  |
|  | 12 | 4.91M | **19.7M** | 7.10M ⚠ | 10.5M |  |
| Ping-pong | 1 | 7.59M ⚠ | **13.1M** | 134K | 3.65M | round trips/s |
|  | 2 | 4.26M ⚠ | **7.01M** | 3.80M ⚠ | 3.90M |  |
|  | 6 | 4.44M | **7.57M** | 3.80M ⚠ | 3.95M |  |
|  | 12 | 4.31M | **7.04M** ⚠ | 3.86M ⚠ | 3.91M |  |
| Ping-pong latency p50 | 1 | 141 ns | **90 ns** | 7.37 µs | 280 ns | per round trip, lower is better |
|  | 2 | 140 ns | **86 ns** | 256 ns | 251 ns |  |
|  | 6 | 136 ns | **80 ns** | 281 ns | 250 ns |  |
|  | 12 | 140 ns | **90 ns** | 280 ns | 250 ns |  |
| Ping-pong latency p99 | 1 | 270 ns | **166 ns** | 9.45 µs | 451 ns | per round trip, lower is better |
|  | 2 | 2.25 µs | 2.21 µs | **331 ns** | 461 ns |  |
|  | 6 | 2.17 µs | 2.16 µs | **346 ns** | 441 ns |  |
|  | 12 | 2.18 µs | 2.17 µs | **341 ns** | 516 ns |  |
| Select over 2 channels, capacity 1024 | 1 | 22.7M | **35.7M** | 11.0M | 17.4M ⚠ | messages/s |
|  | 2 | 20.7M | **29.7M** ⚠ | 9.10M | 16.4M |  |
|  | 6 | 19.1M | **37.0M** ⚠ | 12.3M | 13.5M |  |
|  | 12 | 20.0M | **36.9M** | 13.3M | 13.8M |  |
| Select over 2 channels, capacity 1 | 1 | 7.08M | 6.48M | 152K | 6.94M | messages/s |
|  | 2 | 3.91M | 3.64M | 1.82M ⚠ | **7.23M** |  |
|  | 6 | 5.47M | 5.19M | 6.02M ⚠ | **7.17M** |  |
|  | 12 | 5.43M | 4.91M | 5.77M ⚠ | **7.09M** |  |

### Tasks, CPU, locks and memory

| Test | Threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 1 | 3.92M ⚠ | **11.3M** | 18.2K | 1.19M ⚠ | tasks/s |
|  | 2 | 3.33M ⚠ | **6.21M** ⚠ | 20.7K | 4.99M ⚠ |  |
|  | 6 | 3.79M ⚠ | 5.51M ⚠ | 29.1K ⚠ | 5.73M ⚠ |  |
|  | 12 | 3.87M ⚠ | 5.87M ⚠ | 28.2K ⚠ | 5.32M ⚠ |  |
| Spawn and join, 1M tasks | 1 | 3.80M | **6.00M** ⚠ | skipped | 1.25M ⚠ | tasks/s |
|  | 2 | 3.63M | **6.03M** | skipped | 5.25M |  |
|  | 6 | 3.70M | 4.75M | skipped | **5.90M** |  |
|  | 12 | 3.56M ⚠ | 5.31M | skipped | **5.59M** ⚠ |  |
| CPU-heavy hashing | 1 | 13.6M | 13.7M | 13.7M | 13.1M | items/s |
|  | 2 | 26.9M | 27.0M | 27.1M ⚠ | 26.1M |  |
|  | 6 | 67.6M | 68.1M | 67.7M | 61.8M |  |
|  | 12 | 99.0M | 99.1M | 99.7M | 90.7M |  |
| Lock contention, 8 workers | 1 | 51.0M | 230M | **266M** | 262M | increments/s |
|  | 2 | 9.06M ⚠ | **146M** | 54.5M ⚠ | 56.3M ⚠ |  |
|  | 6 | 9.27M | **71.8M** | 33.3M | 22.8M |  |
|  | 12 | 8.98M | **74.8M** ⚠ | 29.4M | 25.8M |  |
| Memory per idle task, 10K tasks | 12 | 408 B ⚠ | **261 B** ⚠ | 9.92 KiB | 2.79 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 12 | 386 B | **259 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 12 | 385 B | **258 B** | error | 2.69 KiB | bytes per task, lower is better |

## Notes

- Crossbeam skipped (one OS thread per task; capped at 20000): Spawn and join, 1M tasks; Memory per idle task, 100K tasks
- Crossbeam error (runner: not enough free memory): Memory per idle task, 1M tasks
- CPU temperature before each config: 65–84 °C
- **Run:** profile `full`, started 2026-09-17T10:35:59+05:30, seed 1760887766
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor performance
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 12,941 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, flume 0.12.0, kanal 0.1.1, mimalloc 0.1.52, parking_lot 0.12.5, tokio 1.53.1
