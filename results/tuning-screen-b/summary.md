# Tokio

Median of 3 runs after 1 warm-up (profile `full`, started 2026-09-16T23:00:58+05:30). **Bold** marks a clear best: its 75% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/3) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

⚠ Run conditions: CPU governor is 'powersave', not 'performance', so frequency scaling adds noise. 1-minute load average was 3.83 at start; other programs compete for CPU.

## At 12 threads

| Test | Tokio | Tokio + mimalloc | Tokio + no-handles | Tokio + mimalloc + no-handles | Tokio + std-mutex | Tokio + parking-lot | Tokio + unconstrained | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 2.20M ⚠ | 5.21M | 1.70M ⚠ | 5.52M ⚠ | — | — | — | tasks/s |
| Spawn and join, 1M tasks | 2.21M | 4.19M | 1.74M | **5.16M** | — | — | — | tasks/s |
| CPU-heavy hashing | 105M | 104M | — | — | — | — | — | items/s |
| Lock contention, 8 workers | 8.94M | 8.20M | — | — | 30.6M | **83.4M** ⚠ | 8.72M ⚠ | increments/s |
| Memory per idle task, 10K tasks | 393 B | **227 B** | — | — | — | — | — | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 385 B | **253 B** | — | — | — | — | — | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 384 B | **256 B** | — | — | — | — | — | bytes per task, lower is better |

## All thread counts

| Test | Threads | Tokio | Tokio + mimalloc | Tokio + no-handles | Tokio + mimalloc + no-handles | Tokio + std-mutex | Tokio + parking-lot | Tokio + unconstrained | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Spawn and join, 10K tasks | 1 | 2.05M ⚠ | 6.76M | 1.10M ⚠ | **8.41M** | — | — | — | tasks/s |
|  | 2 | 2.21M ⚠ | 4.03M ⚠ | 1.48M ⚠ | 5.04M | — | — | — |  |
|  | 12 | 2.20M ⚠ | 5.21M | 1.70M ⚠ | 5.52M ⚠ | — | — | — |  |
| Spawn and join, 1M tasks | 1 | 2.09M | 4.98M | 1.78M | **5.36M** | — | — | — | tasks/s |
|  | 2 | 2.18M | 4.32M | 1.38M | **5.17M** | — | — | — |  |
|  | 12 | 2.21M | 4.19M | 1.74M | **5.16M** | — | — | — |  |
| CPU-heavy hashing | 1 | 13.4M | 13.4M | — | — | — | — | — | items/s |
|  | 2 | **26.5M** | 26.4M | — | — | — | — | — |  |
|  | 12 | 105M | 104M | — | — | — | — | — |  |
| Lock contention, 8 workers | 1 | 46.1M | 45.3M | — | — | **253M** | 219M | 47.5M | increments/s |
|  | 2 | 8.53M | 8.64M ⚠ | — | — | 56.2M | **143M** | 8.62M |  |
|  | 12 | 8.94M | 8.20M | — | — | 30.6M | **83.4M** ⚠ | 8.72M ⚠ |  |
| Memory per idle task, 10K tasks | 12 | 393 B | **227 B** | — | — | — | — | — | bytes per task, lower is better |
| Memory per idle task, 100K tasks | 12 | 385 B | **253 B** | — | — | — | — | — | bytes per task, lower is better |
| Memory per idle task, 1M tasks | 12 | 384 B | **256 B** | — | — | — | — | — | bytes per task, lower is better |

## Notes

- Tokio + mimalloc: mimalloc global allocator
- Tokio + unconstrained: tasks opt out of Tokio's co-operative yield budget
- Tokio + no-handles: no JoinHandles; tasks write results into a shared slice, like the Go version
- Tokio + std-mutex: std::sync::Mutex, never held across .await
- Tokio + parking-lot: parking_lot::Mutex, never held across .await
- **Run:** profile `full`, started 2026-09-16T23:00:58+05:30, seed 2504389821
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor powersave
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 14,147 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, parking_lot 0.12.5, tokio 1.53.1
