# Concurrency benchmark: tokio vs tokio+mimalloc vs tokio+batch vs tokio+unconstrained vs tokio+kanal vs tokio+flume vs tokio+join vs tokio+biased

- **Run:** profile `full`, started 2026-09-16T22:58:52+05:30, seed 833203794
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor powersave
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 14,240 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, parking_lot 0.12.5, tokio 1.53.1

**Tokio variants**

- `mimalloc`: mimalloc global allocator
- `batch`: receive up to 256 queued messages per wake-up
- `unconstrained`: tasks opt out of Tokio's co-operative yield budget
- `kanal`: kanal async channels instead of tokio/async-channel
- `flume`: flume async channels instead of tokio/async-channel
- `join`: both sides as futures in one task via join! (no parallelism)
- `biased`: select! polls branches in a fixed order instead of randomly

**Warnings**

- ⚠ CPU governor is 'powersave', not 'performance', so frequency scaling adds noise. Fix: echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
- ⚠ 1-minute load average was 1.44 at start; other programs compete for CPU.

Each cell is the median of 3 measured runs (after 1 warm-up), with the coefficient of variation. **Bold** is the best in the row; ⚠ marks CV above 5%. Every run is a separate process pinned to `threads` CPUs with taskset.

## One sender, one receiver (`spsc`)

Raw message rate through a bounded channel.

Size: 10,000,000. Unit: messages/s, higher is better.

| Threads | tokio | tokio+mimalloc | tokio+batch | tokio+unconstrained | tokio+kanal | tokio+flume | tokio+join |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 28.9M ±19.9% ⚠ | 28.1M ±0.8% | 36.2M ±0.3% | 29.4M ±0.9% | **77.3M** ±4.1% | 59.6M ±6.2% ⚠ | 25.3M ±0.3% |
| 2 | 13.3M ±7.7% ⚠ | 13.4M ±1.8% | 27.4M ±0.4% | 16.7M ±0.5% | **41.8M** ±8.2% ⚠ | 13.2M ±1.6% | 23.7M ±1.3% |
| 12 | 13.4M ±2.8% | 13.5M ±3.7% | 26.6M ±3.5% | 16.5M ±4.4% | **42.5M** ±5.1% ⚠ | 14.9M ±5.5% ⚠ | 23.1M ±1.7% |

## Many senders, many receivers (`mpmc`)

4 senders and 4 receivers sharing one bounded channel.

Size: 10,000,000. Unit: messages/s, higher is better.

| Threads | tokio | tokio+mimalloc | tokio+batch | tokio+kanal | tokio+flume |
|---:|---:|---:|---:|---:|---:|
| 1 | 35.1M ±1.1% | 34.8M ±1.3% | 38.1M ±1.3% | **67.8M** ±7.1% ⚠ | 52.8M ±1.5% |
| 2 | 18.1M ±11.4% ⚠ | 15.2M ±28.1% ⚠ | 16.2M ±11.5% ⚠ | **53.3M** ±2.6% | 7.35M ±3.1% |
| 12 | 9.96M ±2.2% | 9.55M ±1.2% | 10.3M ±2.5% | **34.7M** ±3.2% | 8.25M ±0.2% |

## Ping-pong (`pingpong`)

Two tasks pass one token back and forth over capacity-1 channels; measures wake-up cost.

Size: 1,000,000. Unit: round trips/s, higher is better.

| Threads | tokio | tokio+mimalloc | tokio+unconstrained | tokio+kanal | tokio+flume | tokio+join |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6.57M ±0.8% | 6.36M ±1.4% | 6.49M ±1.0% | **10.1M** ±1.4% | 6.48M ±0.2% | 4.26M ±3.6% |
| 2 | 3.84M ±1.0% | 3.79M ±1.1% | 3.82M ±1.2% | **5.57M** ±2.4% | 3.78M ±1.4% | 2.24M ±1.1% |
| 12 | 3.85M ±0.4% | 3.76M ±1.2% | 3.59M ±2.9% | **5.53M** ±2.2% | 3.67M ±4.0% | 2.22M ±0.6% |

Round-trip latency p50 (lower is better):

| Threads | tokio | tokio+mimalloc | tokio+unconstrained | tokio+kanal | tokio+flume | tokio+join |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 220 ns | 220 ns | 220 ns | **111 ns** | 180 ns | 280 ns |
| 2 | 201 ns | 201 ns | 200 ns | **110 ns** | 161 ns | 290 ns |
| 12 | 200 ns | 210 ns | 210 ns | **120 ns** | 170 ns | 311 ns |

Round-trip latency p99 (lower is better):

| Threads | tokio | tokio+mimalloc | tokio+unconstrained | tokio+kanal | tokio+flume | tokio+join |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 451 ns | 481 ns | 470 ns | **341 ns** | 421 ns | 621 ns |
| 2 | 2.36 µs | 2.33 µs | 2.33 µs | **2.26 µs** | 2.38 µs | 2.9 µs |
| 12 | 2.34 µs | 2.54 µs | 2.52 µs | 2.35 µs | **400 ns** | 3.01 µs |

Round-trip latency p99.9 (lower is better):

| Threads | tokio | tokio+mimalloc | tokio+unconstrained | tokio+kanal | tokio+flume | tokio+join |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.06 µs | 1 µs | 1.13 µs | **591 ns** | 692 ns | 1.38 µs |
| 2 | 3.74 µs | 3.6 µs | 3.93 µs | **3.18 µs** | 4.16 µs | 4.9 µs |
| 12 | 2.92 µs | 3.79 µs | 3.89 µs | 2.98 µs | **1.13 µs** | 4.68 µs |

## Select (`select`)

One consumer waits on two channels at once until both close.

Size: 10,000,000. Unit: messages/s, higher is better.

| Threads | tokio | tokio+mimalloc | tokio+batch | tokio+unconstrained | tokio+biased |
|---:|---:|---:|---:|---:|---:|
| 1 | 20.4M ±0.9% | 20.2M ±0.9% | **31.7M** ±0.7% | 18M ±0.4% | 23.2M ±0.6% |
| 2 | 19M ±0.2% | 19.4M ±1.2% | **28.3M** ±0.5% | 15.7M ±3.7% | 11.1M ±0.4% |
| 12 | 18.7M ±0.9% | 19.3M ±3.4% | **32.5M** ±4.6% | 17.9M ±2.2% | 11.9M ±0.3% |
