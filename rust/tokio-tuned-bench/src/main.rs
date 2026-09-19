//! Tuned Tokio with kanal channels; the workloads are in lib.rs.

#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

fn main() {
    tokio_tuned_bench::main(tokio_tuned_bench::Channels::Kanal);
}
