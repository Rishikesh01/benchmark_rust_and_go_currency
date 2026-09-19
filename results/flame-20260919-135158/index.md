# Flame graphs

One `perf record` at 9999 Hz per test, `full` sizes, recorded 2026-09-19 at commit 40f6a5f. Whole process, startup and untimed passes included. Frame width is CPU cycles; kernel frames end in `_[k]`. Rust is built with frame pointers for complete stacks.

Numbers are medians from the benchmark run [`full-20260919-132216`](../full-20260919-132216/summary.md) (commit 40f6a5f); each links to its flame graph.

## 12 threads

| Test | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---:|---|
| 1 sender → 1 receiver, capacity 1024 | [12.8M](spsc-tokio-12t.svg) | [23.5M](spsc-tokio-tuned-tokio-channels-12t.svg) | [133M](spsc-tokio-tuned-12t.svg) | [36.3M](spsc-crossbeam-12t.svg) | [29.3M](spsc-go-12t.svg) | messages/s |
| 1 sender → 1 receiver, capacity 1 | [5.42M](spsc-cap1-tokio-12t.svg) | [5.27M](spsc-cap1-tokio-tuned-tokio-channels-12t.svg) | [21.3M](spsc-cap1-tokio-tuned-12t.svg) | [7.15M](spsc-cap1-crossbeam-12t.svg) | [11.3M](spsc-cap1-go-12t.svg) | messages/s |
| 4 senders → 1 receiver, capacity 1024 | [8.59M](mpsc-tokio-12t.svg) | [6.81M](mpsc-tokio-tuned-tokio-channels-12t.svg) | [99.4M](mpsc-tokio-tuned-12t.svg) | [39.1M](mpsc-crossbeam-12t.svg) | [26.4M](mpsc-go-12t.svg) | messages/s |
| 4 senders → 1 receiver, capacity 1 | [4.87M](mpsc-cap1-tokio-12t.svg) | [5.01M](mpsc-cap1-tokio-tuned-tokio-channels-12t.svg) | [19.5M](mpsc-cap1-tokio-tuned-12t.svg) | [5.78M](mpsc-cap1-crossbeam-12t.svg) | [10.1M](mpsc-cap1-go-12t.svg) | messages/s |
| 4 senders → 4 receivers, capacity 1024 | [9.22M](mpmc-tokio-12t.svg) | — | [77.5M](mpmc-tokio-tuned-12t.svg) | [30.5M](mpmc-crossbeam-12t.svg) | [18.8M](mpmc-go-12t.svg) | messages/s |
| 4 senders → 4 receivers, capacity 1 | [2.12M](mpmc-cap1-tokio-12t.svg) | — | [19.1M](mpmc-cap1-tokio-tuned-12t.svg) | [5.20M](mpmc-cap1-crossbeam-12t.svg) | [6.61M](mpmc-cap1-go-12t.svg) | messages/s |
| Ping-pong | [4.10M](pingpong-tokio-12t.svg) | [4.56M](pingpong-tokio-tuned-tokio-channels-12t.svg) | [7.49M](pingpong-tokio-tuned-12t.svg) | [3.82M](pingpong-crossbeam-12t.svg) | [3.86M](pingpong-go-12t.svg) | round trips/s |
| Spawn and join, 1M tasks | [3.96M](spawn-tokio-12t.svg) | — | [5.42M](spawn-tokio-tuned-12t.svg) | [29.7K at 10K](spawn-crossbeam-12t.svg) | [5.91M](spawn-go-12t.svg) | tasks/s |
| CPU-heavy hashing | [116M](cpu-tokio-12t.svg) | — | [115M](cpu-tokio-tuned-12t.svg) | [115M](cpu-crossbeam-12t.svg) | [109M](cpu-go-12t.svg) | items/s |
| Select over 2 channels, capacity 1024 | [20.4M](select-tokio-12t.svg) | — | [37.8M](select-tokio-tuned-12t.svg) | [13.5M](select-crossbeam-12t.svg) | [14.0M](select-go-12t.svg) | messages/s |
| Select over 2 channels, capacity 1 | [5.77M](select-cap1-tokio-12t.svg) | — | [5.21M](select-cap1-tokio-tuned-12t.svg) | [6.81M](select-cap1-crossbeam-12t.svg) | [7.15M](select-cap1-go-12t.svg) | messages/s |
| Lock contention, 8 workers | [9.74M](mutex-tokio-12t.svg) | — | [83.5M](mutex-tokio-tuned-12t.svg) | [32.2M](mutex-crossbeam-12t.svg) | [27.1M](mutex-go-12t.svg) | increments/s |
