# Flame graphs

One `perf record` at 9999 Hz per test, `full` sizes, recorded 2026-09-19 at commit a361c74. Whole process, startup and untimed passes included. Frame width is CPU cycles; kernel frames end in `_[k]`. Rust is built with frame pointers for complete stacks.

## 12 threads

| Test | Tokio | Tuned Tokio | Crossbeam | Go |
|---|---|---|---|---|
| 1 sender → 1 receiver, capacity 1024 | [svg](spsc-tokio-12t.svg) | [svg](spsc-tokio-tuned-12t.svg) | [svg](spsc-crossbeam-12t.svg) | [svg](spsc-go-12t.svg) |
| 1 sender → 1 receiver, capacity 1 | [svg](spsc-cap1-tokio-12t.svg) | [svg](spsc-cap1-tokio-tuned-12t.svg) | [svg](spsc-cap1-crossbeam-12t.svg) | [svg](spsc-cap1-go-12t.svg) |
| 4 senders → 1 receiver, capacity 1024 | [svg](mpsc-tokio-12t.svg) | [svg](mpsc-tokio-tuned-12t.svg) | [svg](mpsc-crossbeam-12t.svg) | [svg](mpsc-go-12t.svg) |
| 4 senders → 1 receiver, capacity 1 | [svg](mpsc-cap1-tokio-12t.svg) | [svg](mpsc-cap1-tokio-tuned-12t.svg) | [svg](mpsc-cap1-crossbeam-12t.svg) | [svg](mpsc-cap1-go-12t.svg) |
| 4 senders → 4 receivers, capacity 1024 | [svg](mpmc-tokio-12t.svg) | [svg](mpmc-tokio-tuned-12t.svg) | [svg](mpmc-crossbeam-12t.svg) | [svg](mpmc-go-12t.svg) |
| 4 senders → 4 receivers, capacity 1 | [svg](mpmc-cap1-tokio-12t.svg) | [svg](mpmc-cap1-tokio-tuned-12t.svg) | [svg](mpmc-cap1-crossbeam-12t.svg) | [svg](mpmc-cap1-go-12t.svg) |
| Ping-pong | [svg](pingpong-tokio-12t.svg) | [svg](pingpong-tokio-tuned-12t.svg) | [svg](pingpong-crossbeam-12t.svg) | [svg](pingpong-go-12t.svg) |
| Spawn and join | [svg](spawn-tokio-12t.svg) | [svg](spawn-tokio-tuned-12t.svg) | [svg](spawn-crossbeam-12t.svg) | [svg](spawn-go-12t.svg) |
| CPU-heavy hashing | [svg](cpu-tokio-12t.svg) | [svg](cpu-tokio-tuned-12t.svg) | [svg](cpu-crossbeam-12t.svg) | [svg](cpu-go-12t.svg) |
| Select over 2 channels, capacity 1024 | [svg](select-tokio-12t.svg) | [svg](select-tokio-tuned-12t.svg) | [svg](select-crossbeam-12t.svg) | [svg](select-go-12t.svg) |
| Select over 2 channels, capacity 1 | [svg](select-cap1-tokio-12t.svg) | [svg](select-cap1-tokio-tuned-12t.svg) | [svg](select-cap1-crossbeam-12t.svg) | [svg](select-cap1-go-12t.svg) |
| Lock contention, 8 workers | [svg](mutex-tokio-12t.svg) | [svg](mutex-tokio-tuned-12t.svg) | [svg](mutex-crossbeam-12t.svg) | [svg](mutex-go-12t.svg) |
