# Tokio

Median of 3 runs after 1 warm-up (profile `full`, started 2026-09-16T22:58:52+05:30). **Bold** marks a clear best: its 75% confidence interval for the median doesn't overlap the next best's. No bold means no clear winner. ⚠ means the runs varied by more than 5%; (n/3) means only n runs succeeded. Confidence intervals, min/max, CPU time and p99.9 latency are in `summary.csv`.

⚠ Run conditions: CPU governor is 'powersave', not 'performance', so frequency scaling adds noise. 1-minute load average was 1.44 at start; other programs compete for CPU.

## At 12 threads

| Test | Tokio | Tokio + mimalloc | Tokio + batch | Tokio + unconstrained | Tokio + kanal | Tokio + flume | Tokio + join | Tokio + biased | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 13.4M | 13.5M | 26.6M | 16.5M | **42.5M** ⚠ | 14.9M ⚠ | 23.1M | — | messages/s |
| 4 senders → 4 receivers, capacity 1024 | 9.96M | 9.55M | 10.3M | — | **34.7M** | 8.25M | — | — | messages/s |
| Ping-pong | 3.85M | 3.76M | — | 3.59M | **5.53M** | 3.67M | 2.22M | — | round trips/s |
| Ping-pong latency p50 | 200 ns | 210 ns | — | 210 ns | **120 ns** | 170 ns | 311 ns | — | per round trip, lower is better |
| Ping-pong latency p99 | 2.34 µs | 2.54 µs | — | 2.52 µs | 2.35 µs | 400 ns | 3.01 µs | — | per round trip, lower is better |
| Select over 2 channels, capacity 1024 | 18.7M | 19.3M | **32.5M** | 17.9M | — | — | — | 11.9M | messages/s |

## All thread counts

| Test | Threads | Tokio | Tokio + mimalloc | Tokio + batch | Tokio + unconstrained | Tokio + kanal | Tokio + flume | Tokio + join | Tokio + biased | Unit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 sender → 1 receiver, capacity 1024 | 1 | 28.9M ⚠ | 28.1M | 36.2M | 29.4M | **77.3M** | 59.6M ⚠ | 25.3M | — | messages/s |
|  | 2 | 13.3M ⚠ | 13.4M | 27.4M | 16.7M | **41.8M** ⚠ | 13.2M | 23.7M | — |  |
|  | 12 | 13.4M | 13.5M | 26.6M | 16.5M | **42.5M** ⚠ | 14.9M ⚠ | 23.1M | — |  |
| 4 senders → 4 receivers, capacity 1024 | 1 | 35.1M | 34.8M | 38.1M | — | **67.8M** ⚠ | 52.8M | — | — | messages/s |
|  | 2 | 18.1M ⚠ | 15.2M ⚠ | 16.2M ⚠ | — | **53.3M** | 7.35M | — | — |  |
|  | 12 | 9.96M | 9.55M | 10.3M | — | **34.7M** | 8.25M | — | — |  |
| Ping-pong | 1 | 6.57M | 6.36M | — | 6.49M | **10.1M** | 6.48M | 4.26M | — | round trips/s |
|  | 2 | 3.84M | 3.79M | — | 3.82M | **5.57M** | 3.78M | 2.24M | — |  |
|  | 12 | 3.85M | 3.76M | — | 3.59M | **5.53M** | 3.67M | 2.22M | — |  |
| Ping-pong latency p50 | 1 | 220 ns | 220 ns | — | 220 ns | **111 ns** | 180 ns | 280 ns | — | per round trip, lower is better |
|  | 2 | 201 ns | 201 ns | — | 200 ns | **110 ns** | 161 ns | 290 ns | — |  |
|  | 12 | 200 ns | 210 ns | — | 210 ns | **120 ns** | 170 ns | 311 ns | — |  |
| Ping-pong latency p99 | 1 | 451 ns | 481 ns | — | 470 ns | **341 ns** | 421 ns | 621 ns | — | per round trip, lower is better |
|  | 2 | 2.36 µs | 2.32 µs | — | 2.34 µs | 2.26 µs | 2.38 µs | 2.90 µs | — |  |
|  | 12 | 2.34 µs | 2.54 µs | — | 2.52 µs | 2.35 µs | 400 ns | 3.01 µs | — |  |
| Select over 2 channels, capacity 1024 | 1 | 20.4M | 20.2M | **31.7M** | 18.0M | — | — | — | 23.2M | messages/s |
|  | 2 | 19.0M | 19.4M | **28.3M** | 15.7M | — | — | — | 11.1M |  |
|  | 12 | 18.7M | 19.3M | **32.5M** | 17.9M | — | — | — | 11.9M |  |

## Notes

- Tokio + mimalloc: mimalloc global allocator
- Tokio + batch: receive up to 256 queued messages per wake-up
- Tokio + unconstrained: tasks opt out of Tokio's co-operative yield budget
- Tokio + kanal: kanal async channels instead of tokio/async-channel
- Tokio + flume: flume async channels instead of tokio/async-channel
- Tokio + join: both sides as futures in one task via join! (no parallelism)
- Tokio + biased: select! polls branches in a fixed order instead of randomly
- **Run:** profile `full`, started 2026-09-16T22:58:52+05:30, seed 833203794
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor powersave
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 14,240 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, parking_lot 0.12.5, tokio 1.53.1
