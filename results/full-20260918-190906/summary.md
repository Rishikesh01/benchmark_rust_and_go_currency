# Tokio vs Tuned Tokio vs Crossbeam vs Go

Median of 10 runs after 3 warm-ups (profile `full`, started 2026-09-18T19:09:06+05:30). **Bold** marks a clear best: its 98% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/10) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

Up to 6 threads, each thread has its own physical core; above 6, threads share cores (SMT).

⚠ Run conditions: 1-minute load average was 2.37 at start; other programs compete for CPU.

## At 12 threads

### MPMC channels

Every implementation uses a bounded multi-producer, multi-consumer channel: async-channel (Tokio), kanal (tuned Tokio), crossbeam-channel and Go `chan`.

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 9.32M ⚠ | **78.5M** ⚠ | 24.3M ⚠ | 17.6M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 1.74M ⚠ | **17.4M** | 4.62M | 5.89M | messages/s |

### Single-receiver channels

One receiver per channel. Tokio uses its MPSC channel, `tokio::sync::mpsc` (so does tuned Tokio for select); tuned Tokio otherwise uses kanal, and Crossbeam and Go use their MPMC channels with a single receiver.

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 13.2M | **129M** | 33.9M ⚠ | 28.0M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 4.63M ⚠ | **17.3M** ⚠ | 6.70M ⚠ | 10.4M | messages/s |
| Ping-pong | 3.85M ⚠ | **6.25M** ⚠ | 3.81M ⚠ | 3.58M | round trips/s |
| Ping-pong latency p50 | 151 ns | **100 ns** | 281 ns | 275 ns | per round trip, lower is better |
| Ping-pong latency p99 | 2.48 µs | 2.46 µs | **350 ns** | 581 ns | per round trip, lower is better |
| Select over 2 channels, capacity 1024 | 19.8M | **37.8M** ⚠ | 13.3M | 13.8M | messages/s |
| Select over 2 channels, capacity 1 | 5.00M | 4.58M | 5.88M ⚠ | **6.74M** | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 3.59M ⚠ | 5.90M | 26.0K | 5.39M ⚠ | tasks/s |
| Spawn and join, 1M tasks | 3.39M ⚠ | 4.91M | skipped | **5.32M** | tasks/s |
| CPU-heavy hashing | 99.5M ⚠ | 96.0M ⚠ | 94.6M ⚠ | 90.6M ⚠ | items/s |
| Lock contention, 8 workers | 8.49M ⚠ | **75.1M** | 28.4M ⚠ | 24.8M ⚠ | increments/s |
| Memory per idle task, 10K tasks | 410 B | **281 B** ⚠ | 9.92 KiB | 2.78 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 386 B | **257 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 384 B | **257 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## All thread counts

### MPMC channels

| Test | Threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 1 | 41.1M | **120M** ⚠ | 19.2M ⚠ | 33.2M | messages/s |
|  | 2 | 13.2M ⚠ | **97.3M** | 19.8M ⚠ | 23.1M |  |
|  | 6 | 9.12M ⚠ | **70.3M** | 23.0M ⚠ | 20.4M |  |
|  | 12 | 9.32M ⚠ | **78.5M** ⚠ | 24.3M ⚠ | 17.6M |  |
| 4 senders → 4 receivers, capacity 1 | 1 | 4.69M | **33.7M** | 107K | 9.75M | messages/s |
|  | 2 | 2.45M | **30.9M** | 5.94M ⚠ | 7.17M ⚠ |  |
|  | 6 | 1.88M ⚠ | **18.9M** | 4.83M | 6.38M |  |
|  | 12 | 1.74M ⚠ | **17.4M** | 4.62M | 5.89M |  |

### Single-receiver channels

| Test | Threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 1 | 26.9M ⚠ | **135M** | 34.5M ⚠ | 34.5M | messages/s |
|  | 2 | 13.3M | **127M** | 39.1M ⚠ | 30.3M |  |
|  | 6 | 12.5M | **128M** | 36.2M ⚠ | 27.9M ⚠ |  |
|  | 12 | 13.2M | **129M** | 33.9M ⚠ | 28.0M |  |
| 1 sender → 1 receiver, capacity 1 | 1 | 9.72M | **39.2M** | 135K | 10.3M ⚠ | messages/s |
|  | 2 | 5.20M | **20.6M** ⚠ | 5.94M | 11.2M |  |
|  | 6 | 5.18M ⚠ | **20.1M** ⚠ | 7.19M ⚠ | 10.5M ⚠ |  |
|  | 12 | 4.63M ⚠ | **17.3M** ⚠ | 6.70M ⚠ | 10.4M |  |
| Ping-pong | 1 | 7.42M | **13.2M** | 134K | 3.73M | round trips/s |
|  | 2 | 4.00M ⚠ | **6.66M** | 3.80M ⚠ | 3.93M |  |
|  | 6 | 4.25M | **7.24M** ⚠ | 3.79M | 3.92M |  |
|  | 12 | 3.85M ⚠ | **6.25M** ⚠ | 3.81M ⚠ | 3.58M |  |
| Ping-pong latency p50 | 1 | 141 ns | **90 ns** | 7.37 µs | 271 ns | per round trip, lower is better |
|  | 2 | 150 ns | **90 ns** | 251 ns | 251 ns |  |
|  | 6 | 140 ns | **90 ns** | 280 ns | 250 ns |  |
|  | 12 | 151 ns | **100 ns** | 281 ns | 275 ns |  |
| Ping-pong latency p99 | 1 | 275 ns | **160 ns** | 9.42 µs | 376 ns | per round trip, lower is better |
|  | 2 | 2.40 µs | 2.38 µs | **340 ns** | 440 ns |  |
|  | 6 | 2.29 µs | 2.29 µs | **340 ns** | 466 ns |  |
|  | 12 | 2.48 µs | 2.46 µs | **350 ns** | 581 ns |  |
| Select over 2 channels, capacity 1024 | 1 | 22.1M | **35.0M** | 9.70M | 16.9M | messages/s |
|  | 2 | 20.3M | **29.4M** | 9.06M | 16.3M |  |
|  | 6 | 20.2M | **37.5M** | 13.3M | 14.2M |  |
|  | 12 | 19.8M | **37.8M** ⚠ | 13.3M | 13.8M |  |
| Select over 2 channels, capacity 1 | 1 | 6.87M | 6.27M ⚠ | 153K | 7.00M | messages/s |
|  | 2 | 3.62M ⚠ | 3.36M ⚠ | 1.41M ⚠ | **6.94M** ⚠ |  |
|  | 6 | 5.09M | 4.74M | 5.37M ⚠ | **6.64M** |  |
|  | 12 | 5.00M | 4.58M | 5.88M ⚠ | **6.74M** |  |

### Tasks, CPU, locks and memory

| Test | Threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 1 | 3.63M ⚠ | **11.4M** | 17.0K | 1.21M ⚠ | tasks/s |
|  | 2 | 3.14M ⚠ | **6.26M** ⚠ | 17.5K ⚠ | 5.00M ⚠ |  |
|  | 6 | 3.73M ⚠ | 5.57M ⚠ | 26.4K ⚠ | 5.69M ⚠ |  |
|  | 12 | 3.59M ⚠ | 5.90M | 26.0K | 5.39M ⚠ |  |
| Spawn and join, 1M tasks | 1 | 3.74M | **6.58M** ⚠ | skipped | 1.33M ⚠ | tasks/s |
|  | 2 | 3.24M ⚠ | **5.49M** ⚠ | skipped | 4.44M ⚠ |  |
|  | 6 | 3.37M ⚠ | 4.56M | skipped | **5.36M** ⚠ |  |
|  | 12 | 3.39M ⚠ | 4.91M | skipped | **5.32M** |  |
| CPU-heavy hashing | 1 | 13.6M | 13.6M | 13.6M | 13.0M | items/s |
|  | 2 | 26.4M | 26.9M | 26.9M | 25.6M |  |
|  | 6 | 69.5M | 70.0M | 69.8M ⚠ | 63.2M |  |
|  | 12 | 99.5M ⚠ | 96.0M ⚠ | 94.6M ⚠ | 90.6M ⚠ |  |
| Lock contention, 8 workers | 1 | 48.7M | 230M | **264M** | 255M | increments/s |
|  | 2 | 8.15M ⚠ | **141M** ⚠ | 48.2M ⚠ | 53.0M ⚠ |  |
|  | 6 | 8.43M | **73.5M** | 32.2M ⚠ | 23.2M ⚠ |  |
|  | 12 | 8.49M ⚠ | **75.1M** | 28.4M ⚠ | 24.8M ⚠ |  |
| Memory per idle task, 10K tasks | 12 | 410 B | **281 B** ⚠ | 9.92 KiB | 2.78 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 12 | 386 B | **257 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 12 | 384 B | **257 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## Notes

- Crossbeam skipped (one OS thread per task; capped at 20000): Spawn and join, 1M tasks; Memory per idle task, 100K tasks
- Crossbeam skipped (runner: not enough free memory): Memory per idle task, 1M tasks
- CPU temperature before each config: 63–84 °C
- **Run:** profile `full`, started 2026-09-18T19:09:06+05:30, seed 2760774673
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor performance
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 11,584 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, flume 0.12.0, kanal 0.1.1, mimalloc 0.1.52, parking_lot 0.12.5, tokio 1.53.1
