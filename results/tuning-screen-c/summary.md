# Concurrency benchmark: tokio vs tokio+kanal+batch vs tokio+mimalloc+kanal+batch vs tokio+mimalloc+kanal vs tokio+mimalloc+batch vs tokio+mimalloc+parking-lot vs tokio+parking-lot

- **Run:** profile `full`, started 2026-09-16T23:02:45+05:30, seed 3772941740
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor powersave
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 12,963 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, parking_lot 0.12.5, tokio 1.53.1

**Tokio variants**

- `mimalloc`: mimalloc global allocator
- `batch`: receive up to 256 queued messages per wake-up
- `kanal`: kanal async channels instead of tokio/async-channel
- `parking-lot`: parking_lot::Mutex, never held across .await

**Warnings**

- ⚠ CPU governor is 'powersave', not 'performance', so frequency scaling adds noise. Fix: echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
- ⚠ 1-minute load average was 3.18 at start; other programs compete for CPU.

Each cell is the median of 3 measured runs (after 1 warm-up), with the coefficient of variation. **Bold** is the best in the row; ⚠ marks CV above 5%. Every run is a separate process pinned to `threads` CPUs with taskset.

## One sender, one receiver (`spsc`)

Raw message rate through a bounded channel.

Size: 10,000,000. Unit: messages/s, higher is better.

| Threads | tokio | tokio+kanal+batch | tokio+mimalloc+kanal+batch | tokio+mimalloc+kanal | tokio+mimalloc+batch |
|---:|---:|---:|---:|---:|---:|
| 1 | 25.3M ±1.2% | 92.5M ±5.0% | **92.6M** ±5.3% ⚠ | 70.8M ±1.3% | 32.4M ±0.8% |
| 2 | 12.7M ±1.4% | **77.6M** ±3.9% | 69.2M ±4.4% | 30.2M ±0.6% | 25.5M ±1.6% |
| 12 | 12.5M ±1.7% | 74.8M ±1.1% | **76.1M** ±3.8% | 36.4M ±2.5% | 24.1M ±1.1% |

## Many senders, many receivers (`mpmc`)

4 senders and 4 receivers sharing one bounded channel.

Size: 10,000,000. Unit: messages/s, higher is better.

| Threads | tokio | tokio+kanal+batch | tokio+mimalloc+kanal+batch | tokio+mimalloc+kanal | tokio+mimalloc+batch |
|---:|---:|---:|---:|---:|---:|
| 1 | 34M ±1.8% | **86.3M** ±1.3% | 85.2M ±1.4% | 62.4M ±4.5% | 34.9M ±6.2% ⚠ |
| 2 | 19.2M ±5.5% ⚠ | **74.3M** ±3.3% | 62M ±4.9% | 38.2M ±11.7% ⚠ | 16.9M ±16.3% ⚠ |
| 12 | 9.41M ±4.7% | **49.9M** ±4.9% | 46.2M ±14.1% ⚠ | 28.2M ±3.3% | 8.18M ±12.9% ⚠ |

## Ping-pong (`pingpong`)

Two tasks pass one token back and forth over capacity-1 channels; measures wake-up cost.

Size: 1,000,000. Unit: round trips/s, higher is better.

| Threads | tokio | tokio+mimalloc+kanal |
|---:|---:|---:|
| 1 | 6.42M ±3.1% | **10.1M** ±3.1% |
| 2 | 4M ±1.7% | **5.66M** ±5.0% ⚠ |
| 12 | 4.11M ±1.3% | **5.8M** ±8.0% ⚠ |

Round-trip latency p50 (lower is better):

| Threads | tokio | tokio+mimalloc+kanal |
|---:|---:|---:|
| 1 | 221 ns | **120 ns** |
| 2 | 200 ns | **110 ns** |
| 12 | 190 ns | **101 ns** |

Round-trip latency p99 (lower is better):

| Threads | tokio | tokio+mimalloc+kanal |
|---:|---:|---:|
| 1 | 461 ns | **350 ns** |
| 2 | 2.34 µs | **2.31 µs** |
| 12 | 2.24 µs | **2.2 µs** |

Round-trip latency p99.9 (lower is better):

| Threads | tokio | tokio+mimalloc+kanal |
|---:|---:|---:|
| 1 | 932 ns | **381 ns** |
| 2 | 3.09 µs | **2.92 µs** |
| 12 | **2.65 µs** | **2.65 µs** |

## Select (`select`)

One consumer waits on two channels at once until both close.

Size: 10,000,000. Unit: messages/s, higher is better.

| Threads | tokio | tokio+mimalloc+batch |
|---:|---:|---:|
| 1 | 20.8M ±4.1% | **33.3M** ±1.8% |
| 2 | 19.8M ±0.4% | **28.6M** ±0.8% |
| 12 | 19.4M ±3.6% | **36.8M** ±4.9% |

## Lock contention (`mutex`)

8 workers increment one shared counter under a mutex.

Size: 10,000,000. Unit: increments/s, higher is better.

| Threads | tokio | tokio+mimalloc+parking-lot | tokio+parking-lot |
|---:|---:|---:|---:|
| 1 | 48.9M ±0.4% | **230M** ±0.8% | 228M ±0.7% |
| 2 | 8.71M ±1.3% | **148M** ±3.0% | 141M ±6.8% ⚠ |
| 12 | 8.3M ±3.9% | 79.5M ±8.8% ⚠ | **86.8M** ±4.4% |
