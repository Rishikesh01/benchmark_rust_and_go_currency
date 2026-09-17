# Tokio

Median of 3 runs after 1 warm-up (profile `full`, started 2026-09-16T23:02:45+05:30). **Bold** marks a clear best: its 75% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/3) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

⚠ Run conditions: CPU governor is 'powersave', not 'performance', so frequency scaling adds noise. 1-minute load average was 3.18 at start; other programs compete for CPU.

## At 12 threads

| Test | Tokio | Tokio + kanal + batch | Tokio + mimalloc + kanal + batch | Tokio + mimalloc + kanal | Tokio + mimalloc + batch | Tokio + mimalloc + parking-lot | Tokio + parking-lot | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 12.5M | 74.8M | 76.1M | 36.4M | 24.1M | — | — | messages/s |
| 4 senders → 4 receivers, capacity 1024 | 9.41M | 49.9M | 46.2M ⚠ | 28.2M | 8.18M ⚠ | — | — | messages/s |
| Ping-pong | 4.11M | — | — | **5.80M** ⚠ | — | — | — | round trips/s |
| Ping-pong latency p50 | 190 ns | — | — | **101 ns** | — | — | — | per round trip, lower is better |
| Ping-pong latency p99 | 2.24 µs | — | — | 2.20 µs | — | — | — | per round trip, lower is better |
| Select over 2 channels, capacity 1024 | 19.4M | — | — | — | **36.8M** | — | — | messages/s |
| Lock contention, 8 workers | 8.30M | — | — | — | — | 79.5M ⚠ | 86.8M | increments/s |

## All thread counts

| Test | Threads | Tokio | Tokio + kanal + batch | Tokio + mimalloc + kanal + batch | Tokio + mimalloc + kanal | Tokio + mimalloc + batch | Tokio + mimalloc + parking-lot | Tokio + parking-lot | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 1 | 25.3M | 92.5M | 92.6M ⚠ | 70.8M | 32.4M | — | — | messages/s |
|  | 2 | 12.7M | 77.6M | 69.2M | 30.2M | 25.5M | — | — |  |
|  | 12 | 12.5M | 74.8M | 76.1M | 36.4M | 24.1M | — | — |  |
| 4 senders → 4 receivers, capacity 1024 | 1 | 34.0M | 86.3M | 85.2M | 62.4M | 34.9M ⚠ | — | — | messages/s |
|  | 2 | 19.2M ⚠ | **74.3M** | 62.0M | 38.2M ⚠ | 16.9M ⚠ | — | — |  |
|  | 12 | 9.41M | 49.9M | 46.2M ⚠ | 28.2M | 8.18M ⚠ | — | — |  |
| Ping-pong | 1 | 6.42M | — | — | **10.1M** | — | — | — | round trips/s |
|  | 2 | 4.00M | — | — | **5.66M** ⚠ | — | — | — |  |
|  | 12 | 4.11M | — | — | **5.80M** ⚠ | — | — | — |  |
| Ping-pong latency p50 | 1 | 221 ns | — | — | **120 ns** | — | — | — | per round trip, lower is better |
|  | 2 | 200 ns | — | — | **110 ns** | — | — | — |  |
|  | 12 | 190 ns | — | — | **101 ns** | — | — | — |  |
| Ping-pong latency p99 | 1 | 461 ns | — | — | **350 ns** | — | — | — | per round trip, lower is better |
|  | 2 | 2.34 µs | — | — | 2.31 µs | — | — | — |  |
|  | 12 | 2.24 µs | — | — | 2.20 µs | — | — | — |  |
| Select over 2 channels, capacity 1024 | 1 | 20.8M | — | — | — | **33.3M** | — | — | messages/s |
|  | 2 | 19.8M | — | — | — | **28.6M** | — | — |  |
|  | 12 | 19.4M | — | — | — | **36.8M** | — | — |  |
| Lock contention, 8 workers | 1 | 48.9M | — | — | — | — | **230M** | 228M | increments/s |
|  | 2 | 8.71M | — | — | — | — | 148M | 141M ⚠ |  |
|  | 12 | 8.30M | — | — | — | — | 79.5M ⚠ | 86.8M |  |

## Notes

- Tokio + mimalloc: mimalloc global allocator
- Tokio + batch: receive up to 256 queued messages per wake-up
- Tokio + kanal: kanal async channels instead of tokio/async-channel
- Tokio + parking-lot: parking_lot::Mutex, never held across .await
- **Run:** profile `full`, started 2026-09-16T23:02:45+05:30, seed 3772941740
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor powersave
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 12,963 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, parking_lot 0.12.5, tokio 1.53.1
