# Flame graphs

One `perf record` at 9999 Hz per test, `full` sizes, recorded 2026-09-19 at commit 127cc33. Whole process, startup and untimed passes included. Hover shows each frame's CPU time (samples ÷ 9,999 Hz); kernel frames end in `_[k]`. Rust is built with frame pointers for complete stacks. Rust `async fn` bodies (`f::{closure#0}`) are shown as `f`; the closures and Go `gowrap` wrappers that only start a thread or goroutine are hidden.

Numbers are medians from the benchmark run [`full-20260919-162823`](../full-20260919-162823/summary.md) (commit 127cc33); each links to its flame graph.

## 12 threads

| Test | Tokio | Tuned Tokio, Tokio channels | Tuned Tokio | Crossbeam | Go | Unit |
|---|---:|---:|---:|---:|---:|---|
| 1 sender → 1 receiver, capacity 1024 | [13.0M](spsc-tokio-12t.svg) | [24.1M](spsc-tokio-tuned-tokio-channels-12t.svg) | [138M](spsc-tokio-tuned-12t.svg) | [37.1M](spsc-crossbeam-12t.svg) | [29.6M](spsc-go-12t.svg) | messages/s |
| 1 sender → 1 receiver, capacity 1 | [5.10M](spsc-cap1-tokio-12t.svg) | [5.38M](spsc-cap1-tokio-tuned-tokio-channels-12t.svg) | [21.2M](spsc-cap1-tokio-tuned-12t.svg) | [7.10M](spsc-cap1-crossbeam-12t.svg) | [11.3M](spsc-cap1-go-12t.svg) | messages/s |
| 4 senders → 1 receiver, capacity 1024 | [8.93M](mpsc-tokio-12t.svg) | [6.78M](mpsc-tokio-tuned-tokio-channels-12t.svg) | [110M](mpsc-tokio-tuned-12t.svg) | [37.9M](mpsc-crossbeam-12t.svg) | [26.1M](mpsc-go-12t.svg) | messages/s |
| 4 senders → 1 receiver, capacity 1 | [5.00M](mpsc-cap1-tokio-12t.svg) | [5.40M](mpsc-cap1-tokio-tuned-tokio-channels-12t.svg) | [20.1M](mpsc-cap1-tokio-tuned-12t.svg) | [5.90M](mpsc-cap1-crossbeam-12t.svg) | [10.2M](mpsc-cap1-go-12t.svg) | messages/s |
| 4 senders → 4 receivers, capacity 1024 | [9.29M](mpmc-tokio-12t.svg) | — | [82.0M](mpmc-tokio-tuned-12t.svg) | [29.8M](mpmc-crossbeam-12t.svg) | [18.7M](mpmc-go-12t.svg) | messages/s |
| 4 senders → 4 receivers, capacity 1 | [2.03M](mpmc-cap1-tokio-12t.svg) | — | [19.1M](mpmc-cap1-tokio-tuned-12t.svg) | [5.19M](mpmc-cap1-crossbeam-12t.svg) | [6.73M](mpmc-cap1-go-12t.svg) | messages/s |
| Ping-pong | [4.46M](pingpong-tokio-12t.svg) | [4.52M](pingpong-tokio-tuned-tokio-channels-12t.svg) | [7.49M](pingpong-tokio-tuned-12t.svg) | [3.86M](pingpong-crossbeam-12t.svg) | [4.02M](pingpong-go-12t.svg) | round trips/s |
| Spawn and join, 1M tasks | [4.11M](spawn-tokio-12t.svg) | — | [5.40M](spawn-tokio-tuned-12t.svg) | [29.0K at 10K](spawn-crossbeam-12t.svg) | [6.45M](spawn-go-12t.svg) | tasks/s |
| CPU-heavy hashing | [116M](cpu-tokio-12t.svg) | — | [116M](cpu-tokio-tuned-12t.svg) | [114M](cpu-crossbeam-12t.svg) | [108M](cpu-go-12t.svg) | items/s |
| Select over 2 channels, capacity 1024 | [20.7M](select-tokio-12t.svg) | — | [42.0M](select-tokio-tuned-12t.svg) | [13.7M](select-crossbeam-12t.svg) | [14.2M](select-go-12t.svg) | messages/s |
| Select over 2 channels, capacity 1 | [5.96M](select-cap1-tokio-12t.svg) | — | [5.81M](select-cap1-tokio-tuned-12t.svg) | [8.11M](select-cap1-crossbeam-12t.svg) | [7.32M](select-cap1-go-12t.svg) | messages/s |
| Lock contention, 8 workers | [9.69M](mutex-tokio-12t.svg) | — | [79.0M](mutex-tokio-tuned-12t.svg) | [32.4M](mutex-crossbeam-12t.svg) | [26.0M](mutex-go-12t.svg) | increments/s |
