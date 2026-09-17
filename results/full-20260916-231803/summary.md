# Tokio vs Tuned Tokio vs Crossbeam vs Go

Median of 10 runs after 3 warm-ups (profile `full`, started 2026-09-16T23:18:03+05:30). **Bold** marks a clear best: its 98% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/10) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

⚠ Run conditions: CPU governor is 'powersave', not 'performance', so frequency scaling adds noise. 1-minute load average was 3.33 at start; other programs compete for CPU.

## At 12 threads

| Test | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 12.8M | **129M** | 36.4M ⚠ | 28.5M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 4.52M | **18.2M** ⚠ | 6.64M ⚠ | 9.92M ⚠ | messages/s |
| 4 senders → 4 receivers, capacity 1024 | 9.46M ⚠ | **67.7M** ⚠ | 24.1M ⚠ | 15.3M ⚠ | messages/s |
| 4 senders → 4 receivers, capacity 1 | 1.95M ⚠ | **18.1M** | 4.83M | 6.20M | messages/s |
| Ping-pong | 4.37M | **7.53M** | 3.94M ⚠ | 4.00M | round trips/s |
| Ping-pong latency p50 | 190 ns | **90 ns** | 280 ns | 241 ns | per round trip, lower is better |
| Ping-pong latency p99 | 2.18 µs | 2.13 µs | **301 ns** | 431 ns | per round trip, lower is better |
| Spawn and join, 10K tasks | 2.64M ⚠ | **5.82M** | 29.2K | 4.14M | tasks/s |
| Spawn and join, 1M tasks | 2.59M ⚠ | 5.21M | skipped | **5.55M** | tasks/s |
| CPU-heavy hashing | 115M | **117M** | 115M | 107M | items/s |
| Select over 2 channels, capacity 1024 | 20.3M | **40.7M** | 13.2M | 13.8M | messages/s |
| Select over 2 channels, capacity 1 | 5.78M | 5.15M | 3.32M ⚠ | **7.17M** | messages/s |
| Lock contention, 8 workers | 9.47M | 82.6M ⚠ | 81.6M ⚠ | 27.0M | increments/s |
| Memory per idle task, 10K tasks | 393 B | **225 B** ⚠ | 9.84 KiB | 2.75 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 385 B | **253 B** | skipped | 2.70 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 384 B | **256 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## All thread counts

| Test | Threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 1 | 28.6M | **136M** | 46.4M ⚠ | 36.0M | messages/s |
|  | 2 | 13.0M | **126M** | 40.7M | 30.6M ⚠ |  |
|  | 6 | 13.0M ⚠ | **130M** | 37.1M ⚠ | 28.6M |  |
|  | 12 | 12.8M | **129M** | 36.4M ⚠ | 28.5M |  |
| 1 sender → 1 receiver, capacity 1 | 1 | 8.26M | **35.7M** | 132K | 9.70M | messages/s |
|  | 2 | 4.73M | **19.1M** ⚠ | 5.99M ⚠ | 10.8M |  |
|  | 6 | 4.84M ⚠ | **20.4M** ⚠ | 6.99M | 10.2M ⚠ |  |
|  | 12 | 4.52M | **18.2M** ⚠ | 6.64M ⚠ | 9.92M ⚠ |  |
| 4 senders → 4 receivers, capacity 1024 | 1 | 41.7M | **123M** | 25.7M ⚠ | 33.5M ⚠ | messages/s |
|  | 2 | 12.6M ⚠ | **96.2M** ⚠ | 24.7M ⚠ | 20.1M ⚠ |  |
|  | 6 | 8.48M ⚠ | **64.7M** ⚠ | 25.9M ⚠ | 18.3M |  |
|  | 12 | 9.46M ⚠ | **67.7M** ⚠ | 24.1M ⚠ | 15.3M ⚠ |  |
| 4 senders → 4 receivers, capacity 1 | 1 | 4.61M | **34.9M** | 109K | 10.4M | messages/s |
|  | 2 | 2.42M | **31.5M** ⚠ | 7.19M ⚠ | 6.93M ⚠ |  |
|  | 6 | 2.06M ⚠ | **19.0M** | 5.05M | 6.70M |  |
|  | 12 | 1.95M ⚠ | **18.1M** | 4.83M | 6.20M |  |
| Ping-pong | 1 | 7.55M ⚠ | **13.2M** | 135K | 3.78M | round trips/s |
|  | 2 | 4.31M ⚠ | **7.24M** | 3.81M | 4.11M |  |
|  | 6 | 4.37M | **7.72M** | 3.88M | 4.00M |  |
|  | 12 | 4.37M | **7.53M** | 3.94M ⚠ | 4.00M |  |
| Ping-pong latency p50 | 1 | 200 ns | **100 ns** | 7.37 µs | 271 ns | per round trip, lower is better |
|  | 2 | 190 ns | **86 ns** | 240 ns | 241 ns |  |
|  | 6 | 190 ns | **90 ns** | 281 ns | 241 ns |  |
|  | 12 | 190 ns | **90 ns** | 280 ns | 241 ns |  |
| Ping-pong latency p99 | 1 | 381 ns | 301 ns | 8.61 µs | 321 ns | per round trip, lower is better |
|  | 2 | 2.24 µs | 2.16 µs | **291 ns** | 321 ns |  |
|  | 6 | 2.22 µs | 2.15 µs | **301 ns** | 420 ns |  |
|  | 12 | 2.18 µs | 2.13 µs | **301 ns** | 431 ns |  |
| Spawn and join, 10K tasks | 1 | 2.10M ⚠ | **7.42M** | 18.5K | 724K ⚠ | tasks/s |
|  | 2 | 2.49M ⚠ | **5.68M** | 21.7K | 4.18M |  |
|  | 6 | 2.69M | 5.21M ⚠ | 29.8K | 4.23M |  |
|  | 12 | 2.64M ⚠ | **5.82M** | 29.2K | 4.14M |  |
| Spawn and join, 1M tasks | 1 | 2.63M | **6.64M** | skipped | 1.43M | tasks/s |
|  | 2 | 2.47M | **6.19M** | skipped | 5.30M |  |
|  | 6 | 2.55M | 4.74M | skipped | **5.61M** |  |
|  | 12 | 2.59M ⚠ | 5.21M | skipped | **5.55M** |  |
| CPU-heavy hashing | 1 | 13.7M | 13.7M | 13.7M | 13.2M | items/s |
|  | 2 | 27.3M | 27.3M | **27.5M** | 26.3M |  |
|  | 6 | 77.7M | 77.5M | 77.2M | 71.8M |  |
|  | 12 | 115M | **117M** | 115M | 107M |  |
| Select over 2 channels, capacity 1024 | 1 | 23.0M | **36.7M** | 11.1M | 17.7M | messages/s |
|  | 2 | 20.7M | **30.1M** | 9.16M | 16.9M |  |
|  | 6 | 20.8M | **40.5M** | 13.2M | 14.2M |  |
|  | 12 | 20.3M | **40.7M** | 13.2M | 13.8M |  |
| Select over 2 channels, capacity 1 | 1 | 7.03M | 6.04M | 154K | 7.08M | messages/s |
|  | 2 | 3.96M | 3.55M | 1.57M ⚠ | **7.24M** |  |
|  | 6 | 5.88M | 5.28M | 3.08M ⚠ | **7.23M** |  |
|  | 12 | 5.78M | 5.15M | 3.32M ⚠ | **7.17M** |  |
| Lock contention, 8 workers | 1 | 50.5M | 228M | 226M | **259M** | increments/s |
|  | 2 | 9.46M | 143M | 150M ⚠ | 57.0M ⚠ |  |
|  | 6 | 9.91M | **80.5M** | 75.1M | 23.7M |  |
|  | 12 | 9.47M | 82.6M ⚠ | 81.6M ⚠ | 27.0M |  |
| Memory per idle task, 10K tasks | 12 | 393 B | **225 B** ⚠ | 9.84 KiB | 2.75 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 12 | 385 B | **253 B** | skipped | 2.70 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 12 | 384 B | **256 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## Notes

- Crossbeam skipped (one OS thread per task; capped at 20000): Spawn and join, 1M tasks; Memory per idle task, 100K tasks; Memory per idle task, 1M tasks
- **Run:** profile `full`, started 2026-09-16T23:18:03+05:30, seed 4273460670
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor powersave
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 13,063 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, parking_lot 0.12.5, tokio 1.53.1
