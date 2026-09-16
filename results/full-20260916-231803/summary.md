# Concurrency benchmark: tokio vs crossbeam vs go vs tokio-tuned

- **Run:** profile `full`, started 2026-09-16T23:18:03+05:30, seed 4273460670
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor powersave
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 13,063 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, parking_lot 0.12.5, tokio 1.53.1

**Warnings**

- ⚠ CPU governor is 'powersave', not 'performance', so frequency scaling adds noise. Fix: echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
- ⚠ 1-minute load average was 3.33 at start; other programs compete for CPU.

Each cell is the median of 10 measured runs (after 3 warm-ups), with the coefficient of variation. **Bold** is the best in the row; ⚠ marks CV above 5%. Every run is a separate process pinned to `threads` CPUs with taskset.

## One sender, one receiver (`spsc`)

Raw message rate through a bounded channel of capacity 1024.

Size: 10,000,000. Unit: messages/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 28.6M ±0.9% | 46.4M ±13.3% ⚠ | 36M ±1.1% | **136M** ±0.6% |
| 2 | 13M ±1.6% | 40.7M ±4.1% | 30.6M ±9.6% ⚠ | **126M** ±2.1% |
| 6 | 13M ±5.4% ⚠ | 37.1M ±8.6% ⚠ | 28.6M ±0.9% | **130M** ±1.0% |
| 12 | 12.8M ±4.1% | 36.4M ±7.1% ⚠ | 28.5M ±0.6% | **129M** ±2.0% |

## One sender, one receiver, capacity 1 (`spsc-cap1`)

The same test with a channel of capacity 1, so nearly every message is a hand-off between tasks.

Size: 1,000,000. Unit: messages/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 8.26M ±3.1% | 132K ±1.0% | 9.7M ±4.3% | **35.7M** ±2.4% |
| 2 | 4.73M ±2.5% | 5.99M ±6.4% ⚠ | 10.8M ±3.4% | **19.1M** ±6.6% ⚠ |
| 6 | 4.84M ±5.8% ⚠ | 6.99M ±4.2% | 10.2M ±6.7% ⚠ | **20.4M** ±6.4% ⚠ |
| 12 | 4.52M ±4.8% | 6.64M ±6.7% ⚠ | 9.92M ±9.6% ⚠ | **18.2M** ±8.5% ⚠ |

## Many senders, many receivers (`mpmc`)

4 senders and 4 receivers sharing one bounded channel of capacity 1024.

Size: 10,000,000. Unit: messages/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 41.7M ±1.4% | 25.7M ±32.7% ⚠ | 33.5M ±6.8% ⚠ | **123M** ±3.3% |
| 2 | 12.6M ±6.3% ⚠ | 24.7M ±13.8% ⚠ | 20.1M ±6.9% ⚠ | **96.2M** ±6.7% ⚠ |
| 6 | 8.48M ±6.7% ⚠ | 25.9M ±18.1% ⚠ | 18.3M ±3.9% | **64.7M** ±7.1% ⚠ |
| 12 | 9.46M ±8.5% ⚠ | 24.1M ±14.4% ⚠ | 15.3M ±7.6% ⚠ | **67.7M** ±13.0% ⚠ |

## Many senders, many receivers, capacity 1 (`mpmc-cap1`)

4 senders and 4 receivers sharing one channel of capacity 1.

Size: 1,000,000. Unit: messages/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 4.61M ±1.2% | 109K ±0.4% | 10.4M ±1.5% | **34.9M** ±1.0% |
| 2 | 2.42M ±3.7% | 7.19M ±17.5% ⚠ | 6.93M ±10.9% ⚠ | **31.5M** ±6.0% ⚠ |
| 6 | 2.06M ±6.1% ⚠ | 5.05M ±1.0% | 6.7M ±0.8% | **19M** ±3.0% |
| 12 | 1.95M ±5.9% ⚠ | 4.83M ±2.3% | 6.2M ±1.2% | **18.1M** ±1.2% |

## Ping-pong (`pingpong`)

Two tasks pass one token back and forth over capacity-1 channels; measures wake-up cost.

Size: 1,000,000. Unit: round trips/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 7.55M ±22.3% ⚠ | 135K ±0.5% | 3.78M ±0.8% | **13.2M** ±1.1% |
| 2 | 4.31M ±8.4% ⚠ | 3.81M ±0.2% | 4.11M ±0.4% | **7.24M** ±1.1% |
| 6 | 4.37M ±1.3% | 3.88M ±4.1% | 4M ±1.1% | **7.72M** ±1.4% |
| 12 | 4.37M ±2.6% | 3.94M ±10.2% ⚠ | 4M ±0.6% | **7.53M** ±3.8% |

Round-trip latency p50 (lower is better):

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 200 ns | 7.37 µs | 271 ns | **100 ns** |
| 2 | 190 ns | 240 ns | 241 ns | **86 ns** |
| 6 | 190 ns | 281 ns | 241 ns | **90 ns** |
| 12 | 190 ns | 280 ns | 241 ns | **90 ns** |

Round-trip latency p99 (lower is better):

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 381 ns | 8.61 µs | 321 ns | **301 ns** |
| 2 | 2.24 µs | **291 ns** | 321 ns | 2.16 µs |
| 6 | 2.22 µs | **301 ns** | 420 ns | 2.15 µs |
| 12 | 2.18 µs | **301 ns** | 431 ns | 2.13 µs |

Round-trip latency p99.9 (lower is better):

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 451 ns | 12.9 µs | 511 ns | **330 ns** |
| 2 | 2.61 µs | **1.07 µs** | 2.46 µs | 2.34 µs |
| 6 | 2.63 µs | **1.09 µs** | 2.66 µs | 2.35 µs |
| 12 | 2.58 µs | **1.16 µs** | 2.58 µs | 2.35 µs |

## Spawn and join (`spawn`)

Start tasks that each return a number, then wait for all of them.

Size: 10,000. Unit: tasks/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 2.1M ±18.4% ⚠ | 18.5K ±0.6% | 724K ±9.6% ⚠ | **7.42M** ±3.6% |
| 2 | 2.49M ±12.0% ⚠ | 21.7K ±1.6% | 4.18M ±2.2% | **5.68M** ±3.6% |
| 6 | 2.69M ±3.2% | 29.8K ±2.6% | 4.23M ±2.0% | **5.21M** ±19.3% ⚠ |
| 12 | 2.64M ±12.8% ⚠ | 29.2K ±3.3% | 4.14M ±3.8% | **5.82M** ±3.3% |

Size: 1,000,000. Unit: tasks/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 2.63M ±4.1% | skipped | 1.43M ±0.8% | **6.64M** ±3.5% |
| 2 | 2.47M ±1.1% | skipped | 5.3M ±2.4% | **6.19M** ±1.0% |
| 6 | 2.55M ±1.2% | skipped | **5.61M** ±0.7% | 4.74M ±0.9% |
| 12 | 2.59M ±5.8% ⚠ | skipped | **5.55M** ±1.0% | 5.21M ±2.7% |

## CPU-heavy parallel work (`cpu`)

Hash items with splitmix64 (32 rounds each), split into 256 chunks.

Size: 16,000,000. Unit: items/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 13.7M ±0.1% | **13.7M** ±0.1% | 13.2M ±0.1% | 13.7M ±0.1% |
| 2 | 27.3M ±0.1% | **27.5M** ±0.1% | 26.3M ±0.2% | 27.3M ±0.1% |
| 6 | **77.7M** ±1.3% | 77.2M ±1.7% | 71.8M ±1.0% | 77.5M ±0.4% |
| 12 | 115M ±1.5% | 115M ±0.9% | 107M ±1.2% | **117M** ±1.1% |

## Select (`select`)

One consumer waits on two channels of capacity 1024 at once until both close.

Size: 10,000,000. Unit: messages/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 23M ±0.7% | 11.1M ±1.9% | 17.7M ±1.6% | **36.7M** ±0.7% |
| 2 | 20.7M ±0.8% | 9.16M ±0.3% | 16.9M ±0.9% | **30.1M** ±0.4% |
| 6 | 20.8M ±1.5% | 13.2M ±2.1% | 14.2M ±0.5% | **40.5M** ±3.0% |
| 12 | 20.3M ±2.0% | 13.2M ±1.2% | 13.8M ±1.4% | **40.7M** ±4.6% |

## Select, capacity 1 (`select-cap1`)

The same select test with both channels at capacity 1.

Size: 1,000,000. Unit: messages/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 7.03M ±1.0% | 154K ±1.4% | **7.08M** ±2.6% | 6.04M ±3.6% |
| 2 | 3.96M ±3.6% | 1.57M ±41.1% ⚠ | **7.24M** ±2.3% | 3.55M ±2.1% |
| 6 | 5.88M ±1.0% | 3.08M ±37.0% ⚠ | **7.23M** ±0.6% | 5.28M ±2.7% |
| 12 | 5.78M ±1.2% | 3.32M ±23.4% ⚠ | **7.17M** ±1.5% | 5.15M ±2.4% |

## Lock contention (`mutex`)

8 workers increment one shared counter under a mutex.

Size: 10,000,000. Unit: increments/s, higher is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 1 | 50.5M ±0.7% | 226M ±0.5% | **259M** ±1.3% | 228M ±0.3% |
| 2 | 9.46M ±0.9% | **150M** ±5.8% ⚠ | 57M ±13.1% ⚠ | 143M ±1.9% |
| 6 | 9.91M ±1.1% | 75.1M ±1.0% | 23.7M ±2.6% | **80.5M** ±1.6% |
| 12 | 9.47M ±2.3% | 81.6M ±5.6% ⚠ | 27M ±1.4% | **82.6M** ±6.9% ⚠ |

## Memory per idle task (`idle`)

Resident memory added per task parked on a channel or semaphore.

Tasks: 10,000. Lower is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 12 | 393 B ±1.4% | 9.84 KiB ±0.2% | 2.75 KiB ±0.8% | **225 B** ±27.1% ⚠ |

Tasks: 100,000. Lower is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 12 | 385 B ±0.2% | skipped | 2.7 KiB ±0.1% | **253 B** ±2.5% |

Tasks: 1,000,000. Lower is better.

| Threads | tokio | crossbeam | go | tokio-tuned |
|---:|---:|---:|---:|---:|
| 12 | 384 B ±0.0% | skipped | 2.69 KiB ±0.3% | **256 B** ±0.4% |

## Skipped or failed

| Workload | Size | Threads | Impl | Status | Reason |
|---|---:|---:|---|---|---|
| spawn | 1,000,000 | 1 | crossbeam | skipped | one OS thread per task; capped at 20000 |
| spawn | 1,000,000 | 2 | crossbeam | skipped | one OS thread per task; capped at 20000 |
| spawn | 1,000,000 | 6 | crossbeam | skipped | one OS thread per task; capped at 20000 |
| spawn | 1,000,000 | 12 | crossbeam | skipped | one OS thread per task; capped at 20000 |
| idle | 100,000 | 12 | crossbeam | skipped | one OS thread per task; capped at 20000 |
| idle | 1,000,000 | 12 | crossbeam | skipped | one OS thread per task; capped at 20000 |
