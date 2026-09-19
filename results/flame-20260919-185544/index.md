# Flame graphs

One `perf record` at 9999 Hz per test, `full` sizes, recorded 2026-09-19 at commit 9f0fdab. Whole process, startup and untimed passes included. Hover shows each frame's CPU time (samples ÷ 9,999 Hz); kernel frames end in `_[k]`. Rust is built with frame pointers for complete stacks. Rust `async fn` bodies (`f::{closure#0}`) are shown as `f`; the closures and Go `gowrap` wrappers that only start a thread or goroutine are hidden.

Numbers are medians from the benchmark run [`full-20260919-182448`](../full-20260919-182448/summary.md) (commit 9f0fdab); each links to its flame graph.

## 12 threads

| Test | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---:|---|
| 1 sender → 1 receiver, capacity 1024 | [13.2M](spsc-tokio-12t.svg) | [23.8M](spsc-tokio-tuned-tokio-channels-12t.svg) | [137M](spsc-tokio-tuned-12t.svg) | [38.3M](spsc-crossbeam-12t.svg) | [29.6M](spsc-go-12t.svg) | messages/s |
| 1 sender → 1 receiver, capacity 1 | [5.13M](spsc-cap1-tokio-12t.svg) | [5.12M](spsc-cap1-tokio-tuned-tokio-channels-12t.svg) | [20.5M](spsc-cap1-tokio-tuned-12t.svg) | [6.76M](spsc-cap1-crossbeam-12t.svg) | [11.3M](spsc-cap1-go-12t.svg) | messages/s |
| 4 senders → 1 receiver, capacity 1024 | [8.81M](mpsc-tokio-12t.svg) | [7.07M](mpsc-tokio-tuned-tokio-channels-12t.svg) | [104M](mpsc-tokio-tuned-12t.svg) | [35.4M](mpsc-crossbeam-12t.svg) | [25.9M](mpsc-go-12t.svg) | messages/s |
| 4 senders → 1 receiver, capacity 1 | [5.00M](mpsc-cap1-tokio-12t.svg) | [4.92M](mpsc-cap1-tokio-tuned-tokio-channels-12t.svg) | [20.0M](mpsc-cap1-tokio-tuned-12t.svg) | [5.74M](mpsc-cap1-crossbeam-12t.svg) | [10.1M](mpsc-cap1-go-12t.svg) | messages/s |
| 4 senders → 4 receivers, capacity 1024 | [9.32M (async-channel)](mpmc-tokio-12t.svg) | [9.21M (async-channel)](mpmc-tokio-tuned-tokio-channels-12t.svg) | [81.0M](mpmc-tokio-tuned-12t.svg) | [23.3M](mpmc-crossbeam-12t.svg) | [18.7M](mpmc-go-12t.svg) | messages/s |
| 4 senders → 4 receivers, capacity 1 | [2.03M (async-channel)](mpmc-cap1-tokio-12t.svg) | [1.93M (async-channel)](mpmc-cap1-tokio-tuned-tokio-channels-12t.svg) | [19.4M](mpmc-cap1-tokio-tuned-12t.svg) | [5.17M](mpmc-cap1-crossbeam-12t.svg) | [6.87M](mpmc-cap1-go-12t.svg) | messages/s |
| Ping-pong | [4.46M](pingpong-tokio-12t.svg) | [4.35M](pingpong-tokio-tuned-tokio-channels-12t.svg) | [7.51M](pingpong-tokio-tuned-12t.svg) | [3.86M](pingpong-crossbeam-12t.svg) | [4.03M](pingpong-go-12t.svg) | round trips/s |
| Spawn and join, 1M tasks | [4.05M](spawn-tokio-12t.svg) | [5.44M](spawn-tokio-tuned-tokio-channels-12t.svg) | [5.41M](spawn-tokio-tuned-12t.svg) | [29.2K at 10K](spawn-crossbeam-12t.svg) | [6.48M](spawn-go-12t.svg) | tasks/s |
| CPU-heavy hashing | [116M](cpu-tokio-12t.svg) | [116M](cpu-tokio-tuned-tokio-channels-12t.svg) | [115M](cpu-tokio-tuned-12t.svg) | [114M](cpu-crossbeam-12t.svg) | [108M](cpu-go-12t.svg) | items/s |
| Select over 2 channels, capacity 1024 | [20.6M](select-tokio-12t.svg) | [40.6M](select-tokio-tuned-tokio-channels-12t.svg) | [40.6M](select-tokio-tuned-12t.svg) | [13.8M](select-crossbeam-12t.svg) | [13.9M](select-go-12t.svg) | messages/s |
| Select over 2 channels, capacity 1 | [5.96M](select-cap1-tokio-12t.svg) | [5.34M](select-cap1-tokio-tuned-tokio-channels-12t.svg) | [5.37M](select-cap1-tokio-tuned-12t.svg) | [7.37M](select-cap1-crossbeam-12t.svg) | [7.30M](select-cap1-go-12t.svg) | messages/s |
| Lock contention, 8 workers | [9.78M](mutex-tokio-12t.svg) | [81.9M](mutex-tokio-tuned-tokio-channels-12t.svg) | [80.0M](mutex-tokio-tuned-12t.svg) | [31.9M](mutex-crossbeam-12t.svg) | [25.6M](mutex-go-12t.svg) | increments/s |
