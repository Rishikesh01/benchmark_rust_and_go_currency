//! The Tokio variant explorer with mimalloc as the global allocator.

#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

fn main() {
    tokio_variants_bench::run_process("mimalloc");
}
