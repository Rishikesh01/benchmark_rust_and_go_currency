//! Tuned Tokio with Tokio's own channels instead of kanal; the workloads are in lib.rs.

#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

fn main() {
    tokio_tuned_bench::main(tokio_tuned_bench::Channels::Tokio);
}
