//! Tokio implementations of every workload.
//!
//! The whole workload runs inside a spawned task so that all work happens on
//! the `worker_threads` pool and never on the `block_on` thread. Every spawned
//! task body is a named function, so flame graphs show `produce`, `consume` and
//! so on instead of anonymous closures.

use common::{chunk_bounds, cpu_range, fail, proc_rss_kb, Args, Report};
use std::future::Future;
use std::ops::Range;
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
    let (tx, rx) = mpsc::channel::<u64>(a.capacity);
    let start = Instant::now();
    let producer = tokio::spawn(produce(tx, 0..n));
    let consumer = tokio::spawn(consume(rx));
    producer.await.unwrap();
    let sum = consumer.await.unwrap();
    Report::ok(IMPL, &a, n, start.elapsed(), sum)
}

/// Sends every value in `values`.
async fn produce(tx: mpsc::Sender<u64>, values: Range<u64>) {
    for i in values {
        tx.send(i).await.unwrap();
    }
}

/// Sums everything received until every sender is gone.
async fn consume(mut rx: mpsc::Receiver<u64>) -> u64 {
    let mut sum = 0u64;
    while let Some(v) = rx.recv().await {
        sum = sum.wrapping_add(v);
    }
    sum
}

/// Several senders, one receiver: what `tokio::sync::mpsc` is built for.
async fn many_to_one(a: Args) -> Report {
    let per = a.size / a.producers as u64;
    let total = per * a.producers as u64;
    let (tx, rx) = mpsc::channel::<u64>(a.capacity);
    let mut producers = Vec::with_capacity(a.producers);
    let start = Instant::now();
    let consumer = tokio::spawn(consume(rx));
    for p in 0..a.producers as u64 {
        producers.push(tokio::spawn(produce(tx.clone(), p * per..(p + 1) * per)));
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
        consumers.push(tokio::spawn(consume_mpmc(rx.clone())));
    }
    drop(rx);
    for p in 0..a.producers as u64 {
        producers.push(tokio::spawn(produce_mpmc(tx.clone(), p * per..(p + 1) * per)));
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

/// `produce` for an async-channel sender.
async fn produce_mpmc(tx: async_channel::Sender<u64>, values: Range<u64>) {
    for i in values {
        tx.send(i).await.unwrap();
    }
}

/// `consume` for an async-channel receiver.
async fn consume_mpmc(rx: async_channel::Receiver<u64>) -> u64 {
    let mut sum = 0u64;
    while let Ok(v) = rx.recv().await {
        sum = sum.wrapping_add(v);
    }
    sum
}

async fn pingpong(a: Args) -> Report {
    let n = a.size;
    let every = a.sample_every;
    let (to_b, b_rx) = mpsc::channel::<u64>(1);
    let (to_a, a_rx) = mpsc::channel::<u64>(1);
    let samples = Vec::with_capacity((n / every + 1) as usize);
    let start = Instant::now();
    let b = tokio::spawn(pong(b_rx, to_a));
    let a_side = tokio::spawn(ping(to_b, a_rx, n, every, samples));
    let (token, mut samples) = a_side.await.unwrap();
    b.await.unwrap();
    Report::ok(IMPL, &a, n, start.elapsed(), token).with_latencies(&mut samples)
}

/// Sends the token `n` times, waiting for each reply; times every `every`-th round trip.
async fn ping(to_b: mpsc::Sender<u64>, mut a_rx: mpsc::Receiver<u64>, n: u64, every: u64, mut samples: Vec<u64>) -> (u64, Vec<u64>) {
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
}

/// Replies to every token with token + 1 until `ping` hangs up.
async fn pong(mut b_rx: mpsc::Receiver<u64>, to_a: mpsc::Sender<u64>) {
    while let Some(v) = b_rx.recv().await {
        if to_a.send(v + 1).await.is_err() {
            break;
        }
    }
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
        handles.push(tokio::spawn(task_value(i)));
    }
    let mut sum = 0u64;
    for h in handles {
        sum = sum.wrapping_add(h.await.unwrap());
    }
    (start.elapsed(), sum)
}

/// The spawned task: returns its own index.
async fn task_value(i: u64) -> u64 {
    i
}

/// CPU-bound chunks spawned straight onto the runtime (no `spawn_blocking`),
/// i.e. the cost of using Tokio's scheduler as a compute pool.
async fn cpu(a: Args) -> Report {
    let (n, chunks, rounds) = (a.size, a.tasks, a.rounds);
    let mut handles = Vec::with_capacity(chunks);
    let start = Instant::now();
    for c in 0..chunks {
        let (lo, hi) = chunk_bounds(n, chunks, c);
        handles.push(tokio::spawn(hash_chunk(lo, hi, rounds)));
    }
    let mut sum = 0u64;
    for h in handles {
        sum = sum.wrapping_add(h.await.unwrap());
    }
    Report::ok(IMPL, &a, n, start.elapsed(), sum)
}

async fn hash_chunk(lo: u64, hi: u64, rounds: u32) -> u64 {
    cpu_range(lo, hi, rounds)
}

async fn select(a: Args) -> Report {
    let half = a.size / 2;
    let (tx1, rx1) = mpsc::channel::<u64>(a.capacity);
    let (tx2, rx2) = mpsc::channel::<u64>(a.capacity);
    let start = Instant::now();
    let p1 = tokio::spawn(produce(tx1, 0..half));
    let p2 = tokio::spawn(produce(tx2, half..2 * half));
    let consumer = tokio::spawn(select_sum(rx1, rx2));
    p1.await.unwrap();
    p2.await.unwrap();
    let sum = consumer.await.unwrap();
    Report::ok(IMPL, &a, 2 * half, start.elapsed(), sum)
}

/// Sums everything from both channels, taking whichever is ready, until both close.
async fn select_sum(mut rx1: mpsc::Receiver<u64>, mut rx2: mpsc::Receiver<u64>) -> u64 {
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
}

async fn mutex(a: Args) -> Report {
    let per = a.size / a.workers as u64;
    let counter = Arc::new(Mutex::new(0u64));
    let mut handles = Vec::with_capacity(a.workers);
    let start = Instant::now();
    for _ in 0..a.workers {
        handles.push(tokio::spawn(increment(counter.clone(), per)));
    }
    for h in handles {
        h.await.unwrap();
    }
    let elapsed = start.elapsed();
    let total = *counter.lock().await;
    Report::ok(IMPL, &a, per * a.workers as u64, elapsed, total)
}

/// Adds 1 to the shared counter `times` times, taking the lock each time.
async fn increment(counter: Arc<Mutex<u64>>, times: u64) {
    for _ in 0..times {
        *counter.lock().await += 1;
    }
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
        tokio::spawn(park(gate.clone(), parked.clone(), finished.clone(), all_done.clone(), n));
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

/// An idle task: counts itself as parked, waits for the gate to close, then counts itself as finished.
///
/// A plain fn returning an async block, not an `async fn`: an `async fn`'s future keeps its arguments twice
/// (once as passed, once as the locals held across `.await`), which made every idle task 128 B bigger.
fn park(
    gate: Arc<Semaphore>,
    parked: Arc<AtomicU64>,
    finished: Arc<AtomicU64>,
    all_done: Arc<Notify>,
    n: u64,
) -> impl Future<Output = ()> {
    async move {
        parked.fetch_add(1, Ordering::Relaxed);
        let _ = gate.acquire().await;
        if finished.fetch_add(1, Ordering::Relaxed) + 1 == n {
            all_done.notify_one();
        }
    }
}
