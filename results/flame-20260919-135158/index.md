# Flame graphs

One `perf record` at 9999 Hz per test, `full` sizes, recorded 2026-09-19 at commit 40f6a5f. Whole process, startup and untimed passes included. Frame width is CPU cycles; kernel frames end in `_[k]`. Rust is built with frame pointers for complete stacks.

## 12 threads

- 1 sender → 1 receiver, capacity 1024: [Tokio](spsc-tokio-12t.svg) · [Tuned Tokio, Tokio channels](spsc-tokio-tuned-tokio-channels-12t.svg) · [Tuned Tokio](spsc-tokio-tuned-12t.svg) · [Crossbeam](spsc-crossbeam-12t.svg) · [Go](spsc-go-12t.svg)
- 1 sender → 1 receiver, capacity 1: [Tokio](spsc-cap1-tokio-12t.svg) · [Tuned Tokio, Tokio channels](spsc-cap1-tokio-tuned-tokio-channels-12t.svg) · [Tuned Tokio](spsc-cap1-tokio-tuned-12t.svg) · [Crossbeam](spsc-cap1-crossbeam-12t.svg) · [Go](spsc-cap1-go-12t.svg)
- 4 senders → 1 receiver, capacity 1024: [Tokio](mpsc-tokio-12t.svg) · [Tuned Tokio, Tokio channels](mpsc-tokio-tuned-tokio-channels-12t.svg) · [Tuned Tokio](mpsc-tokio-tuned-12t.svg) · [Crossbeam](mpsc-crossbeam-12t.svg) · [Go](mpsc-go-12t.svg)
- 4 senders → 1 receiver, capacity 1: [Tokio](mpsc-cap1-tokio-12t.svg) · [Tuned Tokio, Tokio channels](mpsc-cap1-tokio-tuned-tokio-channels-12t.svg) · [Tuned Tokio](mpsc-cap1-tokio-tuned-12t.svg) · [Crossbeam](mpsc-cap1-crossbeam-12t.svg) · [Go](mpsc-cap1-go-12t.svg)
- 4 senders → 4 receivers, capacity 1024: [Tokio](mpmc-tokio-12t.svg) · [Tuned Tokio](mpmc-tokio-tuned-12t.svg) · [Crossbeam](mpmc-crossbeam-12t.svg) · [Go](mpmc-go-12t.svg)
- 4 senders → 4 receivers, capacity 1: [Tokio](mpmc-cap1-tokio-12t.svg) · [Tuned Tokio](mpmc-cap1-tokio-tuned-12t.svg) · [Crossbeam](mpmc-cap1-crossbeam-12t.svg) · [Go](mpmc-cap1-go-12t.svg)
- Ping-pong: [Tokio](pingpong-tokio-12t.svg) · [Tuned Tokio, Tokio channels](pingpong-tokio-tuned-tokio-channels-12t.svg) · [Tuned Tokio](pingpong-tokio-tuned-12t.svg) · [Crossbeam](pingpong-crossbeam-12t.svg) · [Go](pingpong-go-12t.svg)
- Spawn and join: [Tokio](spawn-tokio-12t.svg) · [Tuned Tokio](spawn-tokio-tuned-12t.svg) · [Crossbeam](spawn-crossbeam-12t.svg) · [Go](spawn-go-12t.svg)
- CPU-heavy hashing: [Tokio](cpu-tokio-12t.svg) · [Tuned Tokio](cpu-tokio-tuned-12t.svg) · [Crossbeam](cpu-crossbeam-12t.svg) · [Go](cpu-go-12t.svg)
- Select over 2 channels, capacity 1024: [Tokio](select-tokio-12t.svg) · [Tuned Tokio](select-tokio-tuned-12t.svg) · [Crossbeam](select-crossbeam-12t.svg) · [Go](select-go-12t.svg)
- Select over 2 channels, capacity 1: [Tokio](select-cap1-tokio-12t.svg) · [Tuned Tokio](select-cap1-tokio-tuned-12t.svg) · [Crossbeam](select-cap1-crossbeam-12t.svg) · [Go](select-cap1-go-12t.svg)
- Lock contention, 8 workers: [Tokio](mutex-tokio-12t.svg) · [Tuned Tokio](mutex-tokio-tuned-12t.svg) · [Crossbeam](mutex-crossbeam-12t.svg) · [Go](mutex-go-12t.svg)
