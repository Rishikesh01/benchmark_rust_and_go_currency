# Concurrency benchmark: tokio vs tokio+mimalloc vs tokio+no-handles vs tokio+mimalloc+no-handles vs tokio+std-mutex vs tokio+parking-lot vs tokio+unconstrained

- **Run:** profile `full`, started 2026-09-16T23:00:58+05:30, seed 2504389821
- **CPU:** AMD Ryzen 5 5625U with Radeon Graphics (12 logical CPUs), governor powersave
- **Pinning order:** 0,2,4,6,8,10,1,3,5,7,9,11
- **Kernel:** 6.8.0-11-generic · **Memory:** 22,844 MiB total, 14,147 MiB free at start
- **Toolchains:** rustc 1.98.0 (88d9e12ae 2026-08-18) · go version go1.27.0 linux/amd64
- **Crates:** async-channel 2.5.0, crossbeam 0.8.5, crossbeam-channel 0.5.17, crossbeam-deque 0.8.8, parking_lot 0.12.5, tokio 1.53.1

**Tokio variants**

- `mimalloc`: mimalloc global allocator
- `unconstrained`: tasks opt out of Tokio's co-operative yield budget
- `no-handles`: no JoinHandles; tasks write results into a shared slice, like the Go version
- `std-mutex`: std::sync::Mutex, never held across .await
- `parking-lot`: parking_lot::Mutex, never held across .await

**Warnings**

- ⚠ CPU governor is 'powersave', not 'performance', so frequency scaling adds noise. Fix: echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
- ⚠ 1-minute load average was 3.83 at start; other programs compete for CPU.

Each cell is the median of 3 measured runs (after 1 warm-up), with the coefficient of variation. **Bold** is the best in the row; ⚠ marks CV above 5%. Every run is a separate process pinned to `threads` CPUs with taskset.

## Spawn and join (`spawn`)

Start tasks that each return a number, then wait for all of them.

Size: 10,000. Unit: tasks/s, higher is better.

| Threads | tokio | tokio+mimalloc | tokio+no-handles | tokio+mimalloc+no-handles |
|---:|---:|---:|---:|---:|
| 1 | 2.05M ±17.9% ⚠ | 6.76M ±1.9% | 1.1M ±7.5% ⚠ | **8.41M** ±4.0% |
| 2 | 2.21M ±17.2% ⚠ | 4.03M ±20.7% ⚠ | 1.48M ±10.3% ⚠ | **5.04M** ±2.3% |
| 12 | 2.2M ±11.2% ⚠ | 5.21M ±3.0% | 1.7M ±6.6% ⚠ | **5.52M** ±7.0% ⚠ |

Size: 1,000,000. Unit: tasks/s, higher is better.

| Threads | tokio | tokio+mimalloc | tokio+no-handles | tokio+mimalloc+no-handles |
|---:|---:|---:|---:|---:|
| 1 | 2.09M ±0.4% | 4.98M ±4.1% | 1.78M ±0.9% | **5.36M** ±1.8% |
| 2 | 2.18M ±0.7% | 4.32M ±4.1% | 1.38M ±1.8% | **5.17M** ±0.7% |
| 12 | 2.21M ±3.1% | 4.19M ±1.9% | 1.74M ±1.8% | **5.16M** ±1.1% |

## CPU-heavy parallel work (`cpu`)

Hash items with splitmix64 (32 rounds each), split into 256 chunks.

Size: 16,000,000. Unit: items/s, higher is better.

| Threads | tokio | tokio+mimalloc |
|---:|---:|---:|
| 1 | **13.4M** ±0.6% | 13.4M ±1.0% |
| 2 | **26.5M** ±0.2% | 26.4M ±2.3% |
| 12 | **105M** ±0.8% | 104M ±3.1% |

## Lock contention (`mutex`)

8 workers increment one shared counter under a mutex.

Size: 10,000,000. Unit: increments/s, higher is better.

| Threads | tokio | tokio+mimalloc | tokio+std-mutex | tokio+parking-lot | tokio+unconstrained |
|---:|---:|---:|---:|---:|---:|
| 1 | 46.1M ±0.7% | 45.3M ±1.4% | **253M** ±1.6% | 219M ±2.6% | 47.5M ±1.5% |
| 2 | 8.53M ±2.3% | 8.64M ±5.9% ⚠ | 56.2M ±3.2% | **143M** ±0.2% | 8.62M ±1.2% |
| 12 | 8.94M ±3.5% | 8.2M ±3.4% | 30.6M ±3.2% | **83.4M** ±5.2% ⚠ | 8.72M ±14.7% ⚠ |

## Memory per idle task (`idle`)

Resident memory added per task parked on a channel or semaphore.

Tasks: 10,000. Lower is better.

| Threads | tokio | tokio+mimalloc |
|---:|---:|---:|
| 12 | 393 B ±1.9% | **227 B** ±0.9% |

Tasks: 100,000. Lower is better.

| Threads | tokio | tokio+mimalloc |
|---:|---:|---:|
| 12 | 385 B ±0.4% | **253 B** ±0.1% |

Tasks: 1,000,000. Lower is better.

| Threads | tokio | tokio+mimalloc |
|---:|---:|---:|
| 12 | 384 B ±0.0% | **256 B** ±0.0% |
