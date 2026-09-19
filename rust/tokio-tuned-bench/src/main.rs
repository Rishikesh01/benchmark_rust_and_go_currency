//! Tuned Tokio implementations of every workload.
//!
//! Same work, channel capacities and checksums as `tokio-bench`; only the
//! Tokio-side choices differ. Each change was first measured on its own with
//! `tokio-variants-bench` and kept only where it helped:
//!
//! - mimalloc as the global allocator (spawn ~2x faster, idle tasks ~1/3 smaller)
//! - kanal channels instead of tokio mpsc / async-channel (spsc, mpsc, mpmc, pingpong)
//! - consumers take every already-queued message per wake-up (spsc, mpsc, mpmc, select)
//! - no JoinHandles when spawning many tiny tasks (spawn)
//! - parking_lot::Mutex, never held across `.await` (mutex)
//!
//! `cpu` and `idle` are unchanged apart from the allocator. Every spawned task
//! body is a named function, so flame graphs show `produce`, `drain_sum` and so on.
//!
//! `src/bin/tokio-tuned-tokio-channels-bench.rs` runs the channel tests with these
//! same changes but Tokio's own channels, to isolate what kanal contributes.

use common::{chunk_bounds, cpu_range, fail, proc_rss_kb, Args, Report};
use std::ops::Range;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{mpsc, Notify, Semaphore};

#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

const IMPL: &str = "tokio-tuned";

/// Most messages a consumer takes per wake-up.
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

/// Sums everything received: one awaited receive per wake-up, then whatever is
/// already queued (up to BATCH) without going back through the scheduler.
async fn drain_sum(rx: kanal::AsyncReceiver<u64>) -> u64 {
    let mut sum = 0u64;
    while let Ok(v) = rx.recv().await {
        sum = sum.wrapping_add(v);
        for _ in 1..BATCH {
            match rx.try_recv() {
                Ok(Some(v)) => sum = sum.wrapping_add(v),
                _ => break,
            }
        }
    }
    sum
}

/// Sends every value in `values`.
async fn produce(tx: kanal::AsyncSender<u64>, values: Range<u64>) {
    for i in values {
        tx.send(i).await.unwrap();
    }
}

async fn spsc(a: Args) -> Report {
    let n = a.size;
    let (tx, rx) = kanal::bounded_async::<u64>(a.capacity);
    let start = Instant::now();
    let producer = tokio::spawn(produce(tx, 0..n));
    let consumer = tokio::spawn(drain_sum(rx));
    producer.await.unwrap();
    let sum = consumer.await.unwrap();
    Report::ok(IMPL, &a, n, start.elapsed(), sum)
}

/// Several senders, one receiver.
async fn many_to_one(a: Args) -> Report {
    let per = a.size / a.producers as u64;
    let total = per * a.producers as u64;
    let (tx, rx) = kanal::bounded_async::<u64>(a.capacity);
    let mut producers = Vec::with_capacity(a.producers);
    let start = Instant::now();
    let consumer = tokio::spawn(drain_sum(rx));
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

async fn mpmc(a: Args) -> Report {
    let per = a.size / a.producers as u64;
    let total = per * a.producers as u64;
    let (tx, rx) = kanal::bounded_async::<u64>(a.capacity);
    let mut producers = Vec::with_capacity(a.producers);
    let mut consumers = Vec::with_capacity(a.consumers);
    let start = Instant::now();
    for _ in 0..a.consumers {
        consumers.push(tokio::spawn(drain_sum(rx.clone())));
    }
    drop(rx);
    for p in 0..a.producers as u64 {
        producers.push(tokio::spawn(produce(tx.clone(), p * per..(p + 1) * per)));
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
    let (to_b, b_rx) = kanal::bounded_async::<u64>(1);
    let (to_a, a_rx) = kanal::bounded_async::<u64>(1);
    let samples = Vec::with_capacity((n / every + 1) as usize);
    let start = Instant::now();
    let b = tokio::spawn(pong(b_rx, to_a));
    let a_side = tokio::spawn(ping(to_b, a_rx, n, every, samples));
    let (token, mut samples) = a_side.await.unwrap();
    b.await.unwrap();
    Report::ok(IMPL, &a, n, start.elapsed(), token).with_latencies(&mut samples)
}

/// Sends the token `n` times, waiting for each reply; times every `every`-th round trip.
async fn ping(
    to_b: kanal::AsyncSender<u64>,
    a_rx: kanal::AsyncReceiver<u64>,
    n: u64,
    every: u64,
    mut samples: Vec<u64>,
) -> (u64, Vec<u64>) {
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
async fn pong(b_rx: kanal::AsyncReceiver<u64>, to_a: kanal::AsyncSender<u64>) {
    while let Ok(v) = b_rx.recv().await {
        if to_a.send(v + 1).await.is_err() {
            break;
        }
    }
}

struct Completion {
    slots: Box<[AtomicU64]>,
    done: AtomicU64,
    all_done: Notify,
}

/// No JoinHandles: each task writes its own slot and bumps a counter, like the
/// Go version with its results slice and WaitGroup. One untimed pass runs first,
/// as in every implementation, so the timed pass runs in a warm process.
async fn spawn(a: Args) -> Report {
    let n = a.size;
    // Leaked so tasks can borrow it as 'static without per-task Arc refcounting.
    let shared: &'static Completion = Box::leak(Box::new(Completion {
        slots: (0..n).map(|_| AtomicU64::new(0)).collect(),
        done: AtomicU64::new(0),
        all_done: Notify::new(),
    }));
    spawn_once(shared, n).await;
    // Reset outside the timer, like Go clearing its results slice between passes.
    shared.slots.iter().for_each(|slot| slot.store(0, Ordering::Relaxed));
    shared.done.store(0, Ordering::Relaxed);
    let (elapsed, sum) = spawn_once(shared, n).await;
    Report::ok(IMPL, &a, n, elapsed, sum)
}

async fn spawn_once(shared: &'static Completion, n: u64) -> (Duration, u64) {
    let start = Instant::now();
    for i in 0..n {
        tokio::spawn(record(shared, i, n));
    }
    // A permit left over from the warm-up pass only causes one extra loop check.
    while shared.done.load(Ordering::Relaxed) < n {
        shared.all_done.notified().await;
    }
    let sum = shared.slots.iter().fold(0u64, |acc, s| acc.wrapping_add(s.load(Ordering::Relaxed)));
    (start.elapsed(), sum)
}

/// The spawned task: writes its own index into its slot and counts itself done.
async fn record(shared: &'static Completion, i: u64, n: u64) {
    shared.slots[i as usize].store(i, Ordering::Relaxed);
    if shared.done.fetch_add(1, Ordering::Relaxed) + 1 == n {
        shared.all_done.notify_one();
    }
}

/// Unchanged from `tokio-bench`: the hot loop never allocates.
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

/// Stays on tokio mpsc: kanal's receive future loses messages if it is dropped
/// after being polled, so kanal is not safe inside `select!`. `recv_many` is
/// cancel-safe.
async fn select(a: Args) -> Report {
    let half = a.size / 2;
    let (tx1, rx1) = mpsc::channel::<u64>(a.capacity);
    let (tx2, rx2) = mpsc::channel::<u64>(a.capacity);
    let start = Instant::now();
    let p1 = tokio::spawn(produce_mpsc(tx1, 0..half));
    let p2 = tokio::spawn(produce_mpsc(tx2, half..2 * half));
    let consumer = tokio::spawn(select_sum(rx1, rx2));
    p1.await.unwrap();
    p2.await.unwrap();
    let sum = consumer.await.unwrap();
    Report::ok(IMPL, &a, 2 * half, start.elapsed(), sum)
}

/// `produce` for a tokio mpsc sender.
async fn produce_mpsc(tx: mpsc::Sender<u64>, values: Range<u64>) {
    for i in values {
        tx.send(i).await.unwrap();
    }
}

/// Sums everything from both channels, taking up to BATCH queued messages from whichever is ready.
async fn select_sum(mut rx1: mpsc::Receiver<u64>, mut rx2: mpsc::Receiver<u64>) -> u64 {
    let (mut open1, mut open2) = (true, true);
    let (mut buf1, mut buf2) = (Vec::with_capacity(BATCH), Vec::with_capacity(BATCH));
    let mut sum = 0u64;
    while open1 || open2 {
        tokio::select! {
            k = rx1.recv_many(&mut buf1, BATCH), if open1 => {
                open1 = k > 0;
                sum = buf1.drain(..).fold(sum, u64::wrapping_add);
            }
            k = rx2.recv_many(&mut buf2, BATCH), if open2 => {
                open2 = k > 0;
                sum = buf2.drain(..).fold(sum, u64::wrapping_add);
            }
        }
    }
    sum
}

/// A blocking mutex is fine (and far faster) when the lock is never held
/// across an `.await`, which is what Tokio's own docs recommend.
async fn mutex(a: Args) -> Report {
    let per = a.size / a.workers as u64;
    let counter = Arc::new(parking_lot::Mutex::new(0u64));
    let mut handles = Vec::with_capacity(a.workers);
    let start = Instant::now();
    for _ in 0..a.workers {
        handles.push(tokio::spawn(increment(counter.clone(), per)));
    }
    for h in handles {
        h.await.unwrap();
    }
    let elapsed = start.elapsed();
    let total = *counter.lock();
    Report::ok(IMPL, &a, per * a.workers as u64, elapsed, total)
}

/// Adds 1 to the shared counter `times` times, taking the lock each time.
async fn increment(counter: Arc<parking_lot::Mutex<u64>>, times: u64) {
    for _ in 0..times {
        *counter.lock() += 1;
    }
}

/// Unchanged from `tokio-bench`; only the allocator differs.
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
async fn park(gate: Arc<Semaphore>, parked: Arc<AtomicU64>, finished: Arc<AtomicU64>, all_done: Arc<Notify>, n: u64) {
    parked.fetch_add(1, Ordering::Relaxed);
    let _ = gate.acquire().await;
    if finished.fetch_add(1, Ordering::Relaxed) + 1 == n {
        all_done.notify_one();
    }
}
