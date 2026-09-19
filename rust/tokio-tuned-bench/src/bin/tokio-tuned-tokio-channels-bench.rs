//! Tuned Tokio's channel tests with Tokio's own channels instead of kanal.
//!
//! Everything else matches `tokio-tuned-bench`: mimalloc, the same runtime, and consumers
//! that take up to BATCH already-queued messages per wake-up. Comparing the two isolates
//! the channel. Only the tests where tuned Tokio uses kanal and Tokio has a channel are here:
//! Tokio has no MPMC channel, and the other workloads would be identical to `tokio-tuned-bench`.

use common::{fail, Args, Report};
use std::time::Instant;
use tokio::sync::mpsc;

#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

const IMPL: &str = "tokio-tuned-tokio-channels";

/// Most messages a consumer takes per wake-up, as in `tokio-tuned-bench`.
const BATCH: usize = 256;

fn main() {
    let args = Args::parse();
    let rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(args.threads)
        .enable_all()
        .build()
        .unwrap_or_else(|e| fail(&format!("runtime: {e}")));
    let report = rt.block_on(async move { tokio::spawn(run(args)).await.expect("workload task panicked") });
    report.print();
}

async fn run(a: Args) -> Report {
    match a.workload.as_str() {
        "spsc" => spsc(a).await,
        "mpsc" => many_to_one(a).await,
        "pingpong" => pingpong(a).await,
        other => fail(&format!("unknown workload {other} (this build runs spsc, mpsc and pingpong)")),
    }
}

/// `drain_sum` from `tokio-tuned-bench`, on a tokio mpsc receiver.
async fn drain_sum(mut rx: mpsc::Receiver<u64>) -> u64 {
    let mut sum = 0u64;
    while let Some(v) = rx.recv().await {
        sum = sum.wrapping_add(v);
        for _ in 1..BATCH {
            match rx.try_recv() {
                Ok(v) => sum = sum.wrapping_add(v),
                Err(_) => break,
            }
        }
    }
    sum
}

async fn spsc(a: Args) -> Report {
    let n = a.size;
    let (tx, rx) = mpsc::channel::<u64>(a.capacity);
    let start = Instant::now();
    let producer = tokio::spawn(async move {
        for i in 0..n {
            tx.send(i).await.unwrap();
        }
    });
    let consumer = tokio::spawn(drain_sum(rx));
    producer.await.unwrap();
    let sum = consumer.await.unwrap();
    Report::ok(IMPL, &a, n, start.elapsed(), sum)
}

/// Several senders, one receiver.
async fn many_to_one(a: Args) -> Report {
    let per = a.size / a.producers as u64;
    let total = per * a.producers as u64;
    let (tx, rx) = mpsc::channel::<u64>(a.capacity);
    let mut producers = Vec::with_capacity(a.producers);
    let start = Instant::now();
    let consumer = tokio::spawn(drain_sum(rx));
    for p in 0..a.producers as u64 {
        let tx = tx.clone();
        producers.push(tokio::spawn(async move {
            let base = p * per;
            for i in 0..per {
                tx.send(base + i).await.unwrap();
            }
        }));
    }
    drop(tx);
    for p in producers {
        p.await.unwrap();
    }
    let sum = consumer.await.unwrap();
    Report::ok(IMPL, &a, total, start.elapsed(), sum)
}

async fn pingpong(a: Args) -> Report {
    let n = a.size;
    let every = a.sample_every;
    let (to_b, mut b_rx) = mpsc::channel::<u64>(1);
    let (to_a, mut a_rx) = mpsc::channel::<u64>(1);
    let mut samples = Vec::with_capacity((n / every + 1) as usize);
    let start = Instant::now();
    let b = tokio::spawn(async move {
        while let Some(v) = b_rx.recv().await {
            if to_a.send(v + 1).await.is_err() {
                break;
            }
        }
    });
    let a_side = tokio::spawn(async move {
        let mut token = 0u64;
        for i in 0..n {
            let t0 = (i % every == 0).then(Instant::now);
            to_b.send(token + 1).await.unwrap();
            token = a_rx.recv().await.unwrap();
            if let Some(t0) = t0 {
                samples.push(t0.elapsed().as_nanos() as u64);
            }
        }
        (token, samples)
    });
    let (token, mut samples) = a_side.await.unwrap();
    b.await.unwrap();
    Report::ok(IMPL, &a, n, start.elapsed(), token).with_latencies(&mut samples)
}
