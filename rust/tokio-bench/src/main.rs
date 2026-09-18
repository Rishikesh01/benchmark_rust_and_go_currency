//! Tokio implementations of every workload.
//!
//! The whole workload runs inside a spawned task so that all work happens on
//! the `worker_threads` pool and never on the `block_on` thread.

use common::{chunk_bounds, cpu_range, fail, proc_rss_kb, Args, Report};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{mpsc, Mutex, Notify, Semaphore};

const IMPL: &str = "tokio";

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
        "mpmc" => mpmc(a).await,
        "mpsc" => many_to_one(a).await,
        "pingpong" => pingpong(a).await,
        "spawn" => spawn(a).await,
        "cpu" => cpu(a).await,
        "select" => select(a).await,
        "mutex" => mutex(a).await,
        "idle" => idle(a).await,
        other => fail(&format!("unknown workload {other}")),
    }
}

async fn spsc(a: Args) -> Report {
    let n = a.size;
    let (tx, mut rx) = mpsc::channel::<u64>(a.capacity);
    let start = Instant::now();
    let producer = tokio::spawn(async move {
        for i in 0..n {
            tx.send(i).await.unwrap();
        }
    });
    let consumer = tokio::spawn(async move {
        let mut sum = 0u64;
        while let Some(v) = rx.recv().await {
            sum = sum.wrapping_add(v);
        }
        sum
    });
    producer.await.unwrap();
    let sum = consumer.await.unwrap();
    Report::ok(IMPL, &a, n, start.elapsed(), sum)
}

/// Several senders, one receiver: what `tokio::sync::mpsc` is built for.
async fn many_to_one(a: Args) -> Report {
    let per = a.size / a.producers as u64;
    let total = per * a.producers as u64;
    let (tx, mut rx) = mpsc::channel::<u64>(a.capacity);
    let mut producers = Vec::with_capacity(a.producers);
    let start = Instant::now();
    let consumer = tokio::spawn(async move {
        let mut sum = 0u64;
        while let Some(v) = rx.recv().await {
            sum = sum.wrapping_add(v);
        }
        sum
    });
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

/// Tokio's own mpsc has a single receiver, so MPMC uses `async-channel`.
async fn mpmc(a: Args) -> Report {
    let per = a.size / a.producers as u64;
    let total = per * a.producers as u64;
    let (tx, rx) = async_channel::bounded::<u64>(a.capacity);
    let mut producers = Vec::with_capacity(a.producers);
    let mut consumers = Vec::with_capacity(a.consumers);
    let start = Instant::now();
    for _ in 0..a.consumers {
        let rx = rx.clone();
        consumers.push(tokio::spawn(async move {
            let mut sum = 0u64;
            while let Ok(v) = rx.recv().await {
                sum = sum.wrapping_add(v);
            }
            sum
        }));
    }
    drop(rx);
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
    let mut sum = 0u64;
    for c in consumers {
        sum = sum.wrapping_add(c.await.unwrap());
    }
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

/// One untimed pass first, in every implementation, so the timed pass runs in a warm
/// process (allocator pools, task memory, worker threads) instead of paying first-touch costs.
async fn spawn(a: Args) -> Report {
    spawn_join(a.size).await;
    let (elapsed, sum) = spawn_join(a.size).await;
    Report::ok(IMPL, &a, a.size, elapsed, sum)
}

async fn spawn_join(n: u64) -> (Duration, u64) {
    let mut handles = Vec::with_capacity(n as usize);
    let start = Instant::now();
    for i in 0..n {
        handles.push(tokio::spawn(async move { i }));
    }
    let mut sum = 0u64;
    for h in handles {
        sum = sum.wrapping_add(h.await.unwrap());
    }
    (start.elapsed(), sum)
}

/// CPU-bound chunks spawned straight onto the runtime (no `spawn_blocking`),
/// i.e. the cost of using Tokio's scheduler as a compute pool.
async fn cpu(a: Args) -> Report {
    let (n, chunks, rounds) = (a.size, a.tasks, a.rounds);
    let mut handles = Vec::with_capacity(chunks);
    let start = Instant::now();
    for c in 0..chunks {
        let (lo, hi) = chunk_bounds(n, chunks, c);
        handles.push(tokio::spawn(async move { cpu_range(lo, hi, rounds) }));
    }
    let mut sum = 0u64;
    for h in handles {
        sum = sum.wrapping_add(h.await.unwrap());
    }
    Report::ok(IMPL, &a, n, start.elapsed(), sum)
}

async fn select(a: Args) -> Report {
    let half = a.size / 2;
    let (tx1, mut rx1) = mpsc::channel::<u64>(a.capacity);
    let (tx2, mut rx2) = mpsc::channel::<u64>(a.capacity);
    let start = Instant::now();
    let p1 = tokio::spawn(async move {
        for i in 0..half {
            tx1.send(i).await.unwrap();
        }
    });
    let p2 = tokio::spawn(async move {
        for i in half..2 * half {
            tx2.send(i).await.unwrap();
        }
    });
    let consumer = tokio::spawn(async move {
        let (mut open1, mut open2) = (true, true);
        let mut sum = 0u64;
        while open1 || open2 {
            tokio::select! {
                v = rx1.recv(), if open1 => match v {
                    Some(v) => sum = sum.wrapping_add(v),
                    None => open1 = false,
                },
                v = rx2.recv(), if open2 => match v {
                    Some(v) => sum = sum.wrapping_add(v),
                    None => open2 = false,
                },
            }
        }
        sum
    });
    p1.await.unwrap();
    p2.await.unwrap();
    let sum = consumer.await.unwrap();
    Report::ok(IMPL, &a, 2 * half, start.elapsed(), sum)
}

async fn mutex(a: Args) -> Report {
    let per = a.size / a.workers as u64;
    let counter = Arc::new(Mutex::new(0u64));
    let mut handles = Vec::with_capacity(a.workers);
    let start = Instant::now();
    for _ in 0..a.workers {
        let counter = counter.clone();
        handles.push(tokio::spawn(async move {
            for _ in 0..per {
                *counter.lock().await += 1;
            }
        }));
    }
    for h in handles {
        h.await.unwrap();
    }
    let elapsed = start.elapsed();
    let total = *counter.lock().await;
    Report::ok(IMPL, &a, per * a.workers as u64, elapsed, total)
}

/// Memory per parked task. Tasks wait on a closed-later semaphore; no
/// JoinHandles are kept so only the tasks themselves are measured.
async fn idle(a: Args) -> Report {
    let n = a.size;
    let gate = Arc::new(Semaphore::new(0));
    let parked = Arc::new(AtomicU64::new(0));
    let finished = Arc::new(AtomicU64::new(0));
    let all_done = Arc::new(Notify::new());
    let before = proc_rss_kb().unwrap_or(0);
    let start = Instant::now();
    for _ in 0..n {
        let (gate, parked, finished, all_done) = (gate.clone(), parked.clone(), finished.clone(), all_done.clone());
        tokio::spawn(async move {
            parked.fetch_add(1, Ordering::Relaxed);
            let _ = gate.acquire().await;
            if finished.fetch_add(1, Ordering::Relaxed) + 1 == n {
                all_done.notify_one();
            }
        });
    }
    while parked.load(Ordering::Relaxed) < n {
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
    let elapsed = start.elapsed();
    tokio::time::sleep(Duration::from_millis(a.settle_ms)).await;
    let after = proc_rss_kb().unwrap_or(0);
    gate.close();
    while finished.load(Ordering::Relaxed) < n {
        all_done.notified().await;
    }
    Report::ok(IMPL, &a, n, elapsed, finished.load(Ordering::Relaxed)).with_memory(before, after, n)
}
