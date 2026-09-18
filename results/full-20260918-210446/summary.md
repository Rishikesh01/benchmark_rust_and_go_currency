# Tokio vs Tuned Tokio vs Crossbeam vs Go

Median of 10 runs after 3 warm-ups (profile `full`, started 2026-09-18T21:04:46+05:30). **Bold** marks a clear best: its 98% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/10) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

Threads = N: pinned to N CPUs; Tokio has N worker threads, Go has `GOMAXPROCS=N`. Crossbeam runs the OS threads in its column on those CPUs. Throughput is the whole test's total, not per thread or task. Latency is per round trip, memory per idle task.

Up to 6 threads, each thread has its own physical core; above 6, threads share cores (SMT).

⚠ Run conditions: 1-minute load average was 2.35 at start; other programs compete for CPU. Working tree has uncommitted changes; git_commit in meta.json does not fully describe the code.

## At 12 threads

### MPMC channels

Every implementation uses a bounded multi-producer, multi-consumer channel: async-channel (Tokio), kanal (tuned Tokio), crossbeam-channel and Go `chan`.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 8 | 8 | 9.80M ⚠ | **81.3M** | 28.0M ⚠ | 18.8M | messages/s |
| 4 senders → 4 receivers, capacity 1 | 8 | 8 | 1.99M ⚠ | **18.8M** | 5.17M | 6.61M | messages/s |

### Single-receiver channels

One receiver per channel. Tokio uses its MPSC channel, `tokio::sync::mpsc` (so does tuned Tokio for select); tuned Tokio otherwise uses kanal, and Crossbeam and Go use their MPMC channels with a single receiver.

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 2 | 2 | 13.4M | **136M** | 36.8M ⚠ | 29.4M | messages/s |
| 1 sender → 1 receiver, capacity 1 | 2 | 2 | 5.29M | **20.5M** ⚠ | 7.21M | 11.2M | messages/s |
| 4 senders → 1 receiver, capacity 1024 | 5 | 5 | 8.76M | **102M** ⚠ | 40.0M ⚠ | 26.6M | messages/s |
| 4 senders → 1 receiver, capacity 1 | 5 | 5 | 5.23M | **19.7M** | 5.78M | 10.1M | messages/s |
| Ping-pong | 2 | 2 | 4.10M | **7.33M** ⚠ | 4.18M ⚠ | 3.89M | round trips/s |
| Ping-pong latency p50 | 2 | 2 | 150 ns | **86 ns** | 281 ns | 250 ns | per round trip, lower is better |
| Ping-pong latency p99 | 2 | 2 | 2.18 µs | 2.13 µs | **301 ns** | 451 ns | per round trip, lower is better |
| Select over 2 channels, capacity 1024 | 3 | 3 | 20.6M | **41.5M** | 13.4M | 13.9M | messages/s |
| Select over 2 channels, capacity 1 | 3 | 3 | 5.81M | 5.37M | 6.33M ⚠ | **7.25M** | messages/s |

### Tasks, CPU, locks and memory

| Test | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 10K | 10K | 3.93M ⚠ | **6.08M** ⚠ | 29.2K | 5.37M ⚠ | tasks/s |
| Spawn and join, 1M tasks | 1M | — | 3.85M | 5.42M | skipped | **5.90M** | tasks/s |
| CPU-heavy hashing | 256 | 12 | 114M | **116M** | 115M | 109M | items/s |
| Lock contention, 8 workers | 8 | 8 | 9.71M | **84.1M** ⚠ | 32.6M | 27.1M | increments/s |
| Memory per idle task, 10K tasks | 10K | 10K | 460 B ⚠ | **233 B** ⚠ | 9.93 KiB | 2.78 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 100K | — | 386 B | **261 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 1M | — | 385 B | **257 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## All thread counts

### MPMC channels

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 4 senders → 4 receivers, capacity 1024 | 1 | 8 | 8 | 45.9M | **138M** | 45.7M ⚠ | 36.4M | messages/s |
|  | 2 | 8 | 8 | 13.9M | **108M** | 20.5M ⚠ | 24.0M |  |
|  | 6 | 8 | 8 | 9.66M ⚠ | **71.6M** | 26.5M ⚠ | 20.9M |  |
|  | 12 | 8 | 8 | 9.80M ⚠ | **81.3M** | 28.0M ⚠ | 18.8M |  |
| 4 senders → 4 receivers, capacity 1 | 1 | 8 | 8 | 4.90M ⚠ | **36.8M** | 110K | 10.8M | messages/s |
|  | 2 | 8 | 8 | 2.64M | **32.3M** | 6.64M ⚠ | 7.36M |  |
|  | 6 | 8 | 8 | 2.22M | **20.0M** | 5.59M | 7.38M |  |
|  | 12 | 8 | 8 | 1.99M ⚠ | **18.8M** | 5.17M | 6.61M |  |

### Single-receiver channels

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 1 | 2 | 2 | 29.4M | **143M** | 48.3M ⚠ | 37.4M | messages/s |
|  | 2 | 2 | 2 | 13.6M | **136M** | 40.5M | 30.9M |  |
|  | 6 | 2 | 2 | 13.7M ⚠ | **137M** | 34.7M ⚠ | 29.4M |  |
|  | 12 | 2 | 2 | 13.4M | **136M** | 36.8M ⚠ | 29.4M |  |
| 1 sender → 1 receiver, capacity 1 | 1 | 2 | 2 | 9.89M | **40.4M** | 136K | 10.9M | messages/s |
|  | 2 | 2 | 2 | 5.12M | **20.3M** ⚠ | 6.14M | 11.5M |  |
|  | 6 | 2 | 2 | 5.41M | **21.7M** | 6.90M ⚠ | 11.3M |  |
|  | 12 | 2 | 2 | 5.29M | **20.5M** ⚠ | 7.21M | 11.2M |  |
| 4 senders → 1 receiver, capacity 1024 | 1 | 5 | 5 | 28.2M | **138M** | 14.8M | 36.8M | messages/s |
|  | 2 | 5 | 5 | 9.34M | **71.8M** ⚠ | 21.0M ⚠ | 30.6M |  |
|  | 6 | 5 | 5 | 8.13M | **101M** | 38.8M ⚠ | 27.6M |  |
|  | 12 | 5 | 5 | 8.76M | **102M** ⚠ | 40.0M ⚠ | 26.6M |  |
| 4 senders → 1 receiver, capacity 1 | 1 | 5 | 5 | 9.94M | **33.7M** | 57.3K | 10.9M | messages/s |
|  | 2 | 5 | 5 | 5.16M | **28.1M** | 6.27M ⚠ | 11.5M |  |
|  | 6 | 5 | 5 | 5.41M | **20.6M** | 5.97M | 10.6M |  |
|  | 12 | 5 | 5 | 5.23M | **19.7M** | 5.78M | 10.1M |  |
| Ping-pong | 1 | 2 | 2 | 7.58M | **13.9M** | 135K | 3.82M | round trips/s |
|  | 2 | 2 | 2 | 4.18M ⚠ | **7.20M** | 3.82M | 4.01M |  |
|  | 6 | 2 | 2 | 4.26M | **7.61M** ⚠ | 3.83M ⚠ | 3.89M |  |
|  | 12 | 2 | 2 | 4.10M | **7.33M** ⚠ | 4.18M ⚠ | 3.89M |  |
| Ping-pong latency p50 | 1 | 2 | 2 | 140 ns | **90 ns** | 7.38 µs | 270 ns | per round trip, lower is better |
|  | 2 | 2 | 2 | 141 ns | **81 ns** | 231 ns | 250 ns |  |
|  | 6 | 2 | 2 | 141 ns | **81 ns** | 280 ns | 251 ns |  |
|  | 12 | 2 | 2 | 150 ns | **86 ns** | 281 ns | 250 ns |  |
| Ping-pong latency p99 | 1 | 2 | 2 | 246 ns | **146 ns** | 8.58 µs | 350 ns | per round trip, lower is better |
|  | 2 | 2 | 2 | 2.21 µs | 2.16 µs | **300 ns** | 370 ns |  |
|  | 6 | 2 | 2 | 2.18 µs | 2.14 µs | **300 ns** | 421 ns |  |
|  | 12 | 2 | 2 | 2.18 µs | 2.13 µs | **301 ns** | 451 ns |  |
| Select over 2 channels, capacity 1024 | 1 | 3 | 3 | 23.4M | **37.6M** | 11.1M | 17.9M | messages/s |
|  | 2 | 3 | 3 | 21.4M | **30.8M** | 9.17M | 17.3M |  |
|  | 6 | 3 | 3 | 21.1M | **41.4M** | 13.4M | 14.4M |  |
|  | 12 | 3 | 3 | 20.6M | **41.5M** | 13.4M | 13.9M |  |
| Select over 2 channels, capacity 1 | 1 | 3 | 3 | 7.26M | 6.47M | 154K | 7.31M | messages/s |
|  | 2 | 3 | 3 | 4.00M | 3.69M | 1.83M ⚠ | **7.44M** |  |
|  | 6 | 3 | 3 | 5.91M | 5.55M | 6.11M ⚠ | **7.24M** |  |
|  | 12 | 3 | 3 | 5.81M | 5.37M | 6.33M ⚠ | **7.25M** |  |

### Tasks, CPU, locks and memory

| Test | Threads | Tokio/Go tasks | Crossbeam threads | Tokio | Tuned Tokio | Crossbeam | Go | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 1 | 10K | 10K | 3.97M ⚠ | **11.4M** ⚠ | 18.3K | 1.35M ⚠ | tasks/s |
|  | 2 | 10K | 10K | 3.37M ⚠ | **6.44M** ⚠ | 21.2K | 4.98M ⚠ |  |
|  | 6 | 10K | 10K | 3.86M ⚠ | 5.51M ⚠ | 29.2K | **5.82M** |  |
|  | 12 | 10K | 10K | 3.93M ⚠ | **6.08M** ⚠ | 29.2K | 5.37M ⚠ |  |
| Spawn and join, 1M tasks | 1 | 1M | — | 4.30M | **6.68M** | skipped | 1.44M | tasks/s |
|  | 2 | 1M | — | 3.86M ⚠ | **6.03M** | skipped | 5.22M |  |
|  | 6 | 1M | — | 3.83M | 4.95M | skipped | **5.98M** |  |
|  | 12 | 1M | — | 3.85M | 5.42M | skipped | **5.90M** |  |
| CPU-heavy hashing | 1 | 256 | 1 | 13.7M | 13.7M | 13.7M | 13.0M | items/s |
|  | 2 | 256 | 2 | 27.4M | **27.5M** | 27.4M | 25.9M |  |
|  | 6 | 256 | 6 | 78.4M | 77.7M | 77.9M | 70.2M |  |
|  | 12 | 256 | 12 | 114M | **116M** | 115M | 109M |  |
| Lock contention, 8 workers | 1 | 8 | 8 | 52.0M | 231M | 267M | 260M | increments/s |
|  | 2 | 8 | 8 | 9.54M ⚠ | **148M** | 51.1M ⚠ | 62.0M ⚠ |  |
|  | 6 | 8 | 8 | 9.99M | **82.8M** | 37.4M | 23.8M |  |
|  | 12 | 8 | 8 | 9.71M | **84.1M** ⚠ | 32.6M | 27.1M |  |
| Memory per idle task, 10K tasks | 12 | 10K | 10K | 460 B ⚠ | **233 B** ⚠ | 9.93 KiB | 2.78 KiB | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 12 | 100K | — | 386 B | **261 B** | skipped | 2.71 KiB | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 12 | 1M | — | 385 B | **257 B** | skipped | 2.69 KiB | bytes per task, lower is better |

## Notes

- Crossbeam skipped (one OS thread per task; capped at 20000): Spawn and join, 1M tasks; Memory per idle task, 100K tasks; Memory per idle task, 1M tasks
- CPU temperature before each config: 54–84 °C
- **Run:** profile `full`, started 2026-09-18T21:04:46+05:30, seed 3518097202
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor performance
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 14,953 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, flume 0.12.0, kanal 0.1.1, mimalloc 0.1.52, parking_lot 0.12.5, tokio 1.53.1
