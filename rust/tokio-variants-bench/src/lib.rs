//! Tokio implementations of every workload, plus opt-in tuning variants.
//!
//! The whole workload runs inside a spawned task so that all work happens on
//! the `worker_threads` pool and never on the `block_on` thread.
//!
//! Without `--variant`, every workload is the plain default Tokio version.
//! `--variant a,b` switches on tuning tricks (see `VARIANTS`). The allocator is
//! picked per binary: `tokio-bench` (system malloc) or `tokio-bench-mimalloc`.

use common::{chunk_bounds, cpu_range, fail, proc_rss_kb, Args, Report};
use std::future::Future;
use std::ops::Range;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};
use tokio::sync::{mpsc, Mutex, Notify, Semaphore};
use tokio::task::JoinHandle;

/// Tuning variants and the workloads each one applies to.
const VARIANTS: &[(&str, &[&str])] = &[
    // Take up to BATCH already-queued messages per wake-up.
    ("batch", &["spsc", "mpsc", "mpmc", "select"]),
    // Opt tasks out of Tokio's co-operative scheduling budget.
    ("unconstrained", &["spsc", "select", "pingpong", "mutex"]),
    // Swap the channel crate.
    ("kanal", &["spsc", "mpsc", "mpmc", "pingpong"]),
    ("flume", &["spsc", "mpsc", "mpmc", "pingpong"]),
    // Run both sides as futures in one task with join! (concurrency without parallelism).
    ("join", &["spsc", "pingpong"]),
    // Spawn without JoinHandles; tasks write into a shared slice like the Go version.
    ("no-handles", &["spawn"]),
    // select! polls branches in order instead of in random order.
    ("biased", &["select"]),
    // A blocking mutex that is never held across an .await.
    ("std-mutex", &["mutex"]),
    ("parking-lot", &["mutex"]),
];
const CONFLICTS: &[(&str, &str)] = &[("kanal", "flume"), ("std-mutex", "parking-lot")];

const BATCH: usize = 256;

static IMPL_NAME: OnceLock<String> = OnceLock::new();

fn name() -> &'static str {
    IMPL_NAME.get().map_or("tokio", String::as_str)
}

pub fn run_process(allocator: &str) {
    let args = Args::parse();
    let mut label = String::from("tokio");
    for part in [allocator].into_iter().filter(|a| *a != "system").chain(args.variants.iter().map(String::as_str)) {
        label.push('+');
        label.push_str(part);
    }
    IMPL_NAME.set(label).unwrap();

    if let Err(reason) = check_variants(&args) {
        Report::skipped(name(), &args, reason).print();
        return;
    }
    let rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(args.threads)
        .enable_all()
        .build()
        .unwrap_or_else(|e| fail(&format!("runtime: {e}")));
    let report = rt.block_on(async move { tokio::spawn(run(args)).await.expect("workload task panicked") });
    report.print();
}

fn check_variants(a: &Args) -> Result<(), String> {
    for v in &a.variants {
        let Some((_, workloads)) = VARIANTS.iter().find(|(known, _)| *known == v.as_str()) else {
            let known: Vec<&str> = VARIANTS.iter().map(|(k, _)| *k).collect();
            fail(&format!("unknown variant {v} (known: {})", known.join(", ")));
        };
        if !workloads.contains(&a.workload.as_str()) {
            return Err(format!("variant {v} does not apply to {}", a.workload));
        }
    }
    for (x, y) in CONFLICTS {
        if a.has(x) && a.has(y) {
            return Err(format!("variants {x} and {y} conflict"));
        }
    }
    Ok(())
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

// ---------------------------------------------------------------- helpers

/// `tokio::spawn`, wrapped in `unconstrained` when that variant is on.
fn spawn_on<F>(a: &Args, fut: F) -> JoinHandle<F::Output>
where
    F: Future + Send + 'static,
    F::Output: Send + 'static,
{
    if a.has("unconstrained") {
        tokio::spawn(tokio::task::unconstrained(fut))
    } else {
        tokio::spawn(fut)
    }
}

/// Runs two futures to completion: as two spawned tasks by default, or inside
/// the current task with `join!` for the `join` variant.
async fn pair<F1, F2>(a: &Args, f1: F1, f2: F2) -> (F1::Output, F2::Output)
where
    F1: Future + Send + 'static,
    F1::Output: Send + 'static,
    F2: Future + Send + 'static,
    F2::Output: Send + 'static,
{
    if a.has("join") {
        let joined = async move { tokio::join!(f1, f2) };
        if a.has("unconstrained") {
            tokio::task::unconstrained(joined).await
        } else {
            joined.await
        }
    } else {
        let (h1, h2) = (spawn_on(a, f1), spawn_on(a, f2));
        (h1.await.unwrap(), h2.await.unwrap())
    }
}

/// Just enough of an async channel for one workload body to run on several crates.
trait Tx: Clone + Send + 'static {
    /// Returns false once every receiver is gone.
    fn send_one(&self, v: u64) -> impl Future<Output = bool> + Send + '_;
}

trait Rx: Send + 'static {
    /// None once every sender is gone and the buffer is empty.
    fn recv_one(&mut self) -> impl Future<Output = Option<u64>> + Send + '_;

    fn try_recv_one(&mut self) -> Option<u64>;

    /// Waits for one message, then takes whatever else is already queued, up to `limit`.
    /// Returns 0 only when the channel is closed and empty.
    fn recv_batch<'a>(&'a mut self, buf: &'a mut Vec<u64>, limit: usize) -> impl Future<Output = usize> + Send + 'a {
        async move {
            let Some(v) = self.recv_one().await else { return 0 };
            buf.push(v);
            while buf.len() < limit {
                match self.try_recv_one() {
                    Some(v) => buf.push(v),
                    None => break,
                }
            }
            buf.len()
        }
    }
}

impl Tx for mpsc::Sender<u64> {
    fn send_one(&self, v: u64) -> impl Future<Output = bool> + Send + '_ {
        async move { self.send(v).await.is_ok() }
    }
}

impl Rx for mpsc::Receiver<u64> {
    fn recv_one(&mut self) -> impl Future<Output = Option<u64>> + Send + '_ {
        self.recv()
    }

    fn try_recv_one(&mut self) -> Option<u64> {
        self.try_recv().ok()
    }

    fn recv_batch<'a>(&'a mut self, buf: &'a mut Vec<u64>, limit: usize) -> impl Future<Output = usize> + Send + 'a {
        self.recv_many(buf, limit)
    }
}

impl Tx for async_channel::Sender<u64> {
    fn send_one(&self, v: u64) -> impl Future<Output = bool> + Send + '_ {
        async move { self.send(v).await.is_ok() }
    }
}

impl Rx for async_channel::Receiver<u64> {
    fn recv_one(&mut self) -> impl Future<Output = Option<u64>> + Send + '_ {
        async move { self.recv().await.ok() }
    }

    fn try_recv_one(&mut self) -> Option<u64> {
        self.try_recv().ok()
    }
}

impl Tx for kanal::AsyncSender<u64> {
    fn send_one(&self, v: u64) -> impl Future<Output = bool> + Send + '_ {
        async move { self.send(v).await.is_ok() }
    }
}

impl Rx for kanal::AsyncReceiver<u64> {
    fn recv_one(&mut self) -> impl Future<Output = Option<u64>> + Send + '_ {
        async move { self.recv().await.ok() }
    }

    fn try_recv_one(&mut self) -> Option<u64> {
        self.try_recv().ok().flatten()
    }
}

impl Tx for flume::Sender<u64> {
    fn send_one(&self, v: u64) -> impl Future<Output = bool> + Send + '_ {
        async move { self.send_async(v).await.is_ok() }
    }
}

impl Rx for flume::Receiver<u64> {
    fn recv_one(&mut self) -> impl Future<Output = Option<u64>> + Send + '_ {
        async move { self.recv_async().await.ok() }
    }

    fn try_recv_one(&mut self) -> Option<u64> {
        self.try_recv().ok()
    }
}

#[derive(Clone, Copy)]
enum Chan {
    Tokio,
    AsyncChannel,
    Kanal,
    Flume,
}

fn chan(a: &Args, default: Chan) -> Chan {
    if a.has("kanal") {
        Chan::Kanal
    } else if a.has("flume") {
        Chan::Flume
    } else {
        default
    }
}

macro_rules! make_channel {
    (Tokio, $cap:expr) => { mpsc::channel::<u64>($cap) };
    (AsyncChannel, $cap:expr) => { async_channel::bounded::<u64>($cap) };
    (Kanal, $cap:expr) => { kanal::bounded_async::<u64>($cap) };
    (Flume, $cap:expr) => { flume::bounded::<u64>($cap) };
}

/// Evaluates `$body` with bounded channel(s) from whichever crate `$kind` selects.
/// Only the listed kinds are generated, since not every crate supports every workload.
macro_rules! with_channel {
    ($kind:expr, [$($k:ident),+], $cap:expr, |$tx:ident, $rx:ident| $body:expr) => {
        match $kind {
            $(Chan::$k => {
                let ($tx, $rx) = make_channel!($k, $cap);
                $body
            })+
            #[allow(unreachable_patterns)]
            _ => unreachable!("channel kind not supported by this workload"),
        }
    };
    ($kind:expr, [$($k:ident),+], $cap:expr, |$tx:ident, $rx:ident, $tx2:ident, $rx2:ident| $body:expr) => {
        match $kind {
            $(Chan::$k => {
                let ($tx, $rx) = make_channel!($k, $cap);
                let ($tx2, $rx2) = make_channel!($k, $cap);
                $body
            })+
            #[allow(unreachable_patterns)]
            _ => unreachable!("channel kind not supported by this workload"),
        }
    };
}

async fn produce<T: Tx>(tx: T, values: Range<u64>) {
    for v in values {
        assert!(tx.send_one(v).await, "receiver dropped");
    }
}

async fn consume<R: Rx>(mut rx: R, batch: bool) -> u64 {
    let mut sum = 0u64;
    if batch {
        let mut buf = Vec::with_capacity(BATCH);
        while rx.recv_batch(&mut buf, BATCH).await > 0 {
            for v in buf.drain(..) {
                sum = sum.wrapping_add(v);
            }
        }
    } else {
        while let Some(v) = rx.recv_one().await {
            sum = sum.wrapping_add(v);
        }
    }
    sum
}

// ---------------------------------------------------------------- workloads

async fn spsc(a: Args) -> Report {
    let n = a.size;
    let batch = a.has("batch");
    let (sum, elapsed) = with_channel!(chan(&a, Chan::Tokio), [Tokio, Kanal, Flume], a.capacity, |tx, rx| {
        let start = Instant::now();
        let ((), sum) = pair(&a, produce(tx, 0..n), consume(rx, batch)).await;
        (sum, start.elapsed())
    });
    Report::ok(name(), &a, n, elapsed, sum)
}

/// Several senders, one receiver: `tokio::sync::mpsc` by default.
async fn many_to_one(a: Args) -> Report {
    let per = a.size / a.producers as u64;
    let batch = a.has("batch");
    let (sum, elapsed) = with_channel!(chan(&a, Chan::Tokio), [Tokio, Kanal, Flume], a.capacity, |tx, rx| {
        let mut producers = Vec::with_capacity(a.producers);
        let start = Instant::now();
        let consumer = spawn_on(&a, consume(rx, batch));
        for p in 0..a.producers as u64 {
            producers.push(spawn_on(&a, produce(tx.clone(), p * per..(p + 1) * per)));
        }
        drop(tx);
        for p in producers {
            p.await.unwrap();
        }
        (consumer.await.unwrap(), start.elapsed())
    });
    Report::ok(name(), &a, per * a.producers as u64, elapsed, sum)
}

/// Tokio's own mpsc has a single receiver, so MPMC defaults to `async-channel`.
async fn mpmc(a: Args) -> Report {
    let per = a.size / a.producers as u64;
    let batch = a.has("batch");
    let (sum, elapsed) = with_channel!(chan(&a, Chan::AsyncChannel), [AsyncChannel, Kanal, Flume], a.capacity, |tx, rx| {
        let mut producers = Vec::with_capacity(a.producers);
        let mut consumers = Vec::with_capacity(a.consumers);
        let start = Instant::now();
        for _ in 0..a.consumers {
            consumers.push(spawn_on(&a, consume(rx.clone(), batch)));
        }
        drop(rx);
        for p in 0..a.producers as u64 {
            producers.push(spawn_on(&a, produce(tx.clone(), p * per..(p + 1) * per)));
        }
        drop(tx);
        for p in producers {
            p.await.unwrap();
        }
        let mut sum = 0u64;
        for c in consumers {
            sum = sum.wrapping_add(c.await.unwrap());
        }
        (sum, start.elapsed())
    });
    Report::ok(name(), &a, per * a.producers as u64, elapsed, sum)
}

async fn pingpong(a: Args) -> Report {
    let (n, every) = (a.size, a.sample_every);
    let samples = Vec::with_capacity((n / every + 1) as usize);
    let ((token, mut samples), elapsed) = with_channel!(chan(&a, Chan::Tokio), [Tokio, Kanal, Flume], 1, |to_b, b_rx, to_a, a_rx| {
        let start = Instant::now();
        let b = async move {
            let mut b_rx = b_rx;
            while let Some(v) = b_rx.recv_one().await {
                if !to_a.send_one(v + 1).await {
                    break;
                }
            }
        };
        let a_side = async move {
            let (mut a_rx, mut samples) = (a_rx, samples);
            let mut token = 0u64;
            for i in 0..n {
                let t0 = (i % every == 0).then(Instant::now);
                assert!(to_b.send_one(token + 1).await, "ping receiver dropped");
                token = a_rx.recv_one().await.expect("pong sender dropped");
                if let Some(t0) = t0 {
                    samples.push(t0.elapsed().as_nanos() as u64);
                }
            }
            drop(to_b);
            (token, samples)
        };
        let ((), result) = pair(&a, b, a_side).await;
        (result, start.elapsed())
    });
    Report::ok(name(), &a, n, elapsed, token).with_latencies(&mut samples)
}

async fn spawn(a: Args) -> Report {
    if a.has("no-handles") {
        return spawn_without_handles(a).await;
    }
    // One untimed pass first, as in every implementation, so the timed pass runs in a warm process.
    spawn_join(a.size).await;
    let (elapsed, sum) = spawn_join(a.size).await;
    Report::ok(name(), &a, a.size, elapsed, sum)
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

struct Completion {
    slots: Box<[AtomicU64]>,
    done: AtomicU64,
    all_done: Notify,
}

/// Mirrors the Go version: each task writes its own slot and bumps a counter.
async fn spawn_without_handles(a: Args) -> Report {
    let n = a.size;
    // Leaked so tasks can borrow it as 'static without per-task Arc refcounting.
    let shared: &'static Completion = Box::leak(Box::new(Completion {
        slots: (0..n).map(|_| AtomicU64::new(0)).collect(),
        done: AtomicU64::new(0),
        all_done: Notify::new(),
    }));
    spawn_once(shared, n).await;
    shared.slots.iter().for_each(|slot| slot.store(0, Ordering::Relaxed));
    shared.done.store(0, Ordering::Relaxed);
    let (elapsed, sum) = spawn_once(shared, n).await;
    Report::ok(name(), &a, n, elapsed, sum)
}

async fn spawn_once(shared: &'static Completion, n: u64) -> (Duration, u64) {
    let start = Instant::now();
    for i in 0..n {
        tokio::spawn(async move {
            shared.slots[i as usize].store(i, Ordering::Relaxed);
            if shared.done.fetch_add(1, Ordering::Relaxed) + 1 == n {
                shared.all_done.notify_one();
            }
        });
    }
    while shared.done.load(Ordering::Relaxed) < n {
        shared.all_done.notified().await;
    }
    let sum = shared.slots.iter().fold(0u64, |acc, s| acc.wrapping_add(s.load(Ordering::Relaxed)));
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
    Report::ok(name(), &a, n, start.elapsed(), sum)
}

async fn select(a: Args) -> Report {
    let half = a.size / 2;
    let (batch, biased) = (a.has("batch"), a.has("biased"));
    let (tx1, rx1) = mpsc::channel::<u64>(a.capacity);
    let (tx2, rx2) = mpsc::channel::<u64>(a.capacity);
    let start = Instant::now();
    let p1 = spawn_on(&a, produce(tx1, 0..half));
    let p2 = spawn_on(&a, produce(tx2, half..2 * half));
    let consumer = spawn_on(&a, select_consume(rx1, rx2, batch, biased));
    p1.await.unwrap();
    p2.await.unwrap();
    let sum = consumer.await.unwrap();
    Report::ok(name(), &a, 2 * half, start.elapsed(), sum)
}

async fn select_consume(mut rx1: mpsc::Receiver<u64>, mut rx2: mpsc::Receiver<u64>, batch: bool, biased: bool) -> u64 {
    let (mut open1, mut open2) = (true, true);
    let mut sum = 0u64;
    let (mut buf1, mut buf2) = (Vec::with_capacity(BATCH), Vec::with_capacity(BATCH));
    match (batch, biased) {
        (false, false) => {
            while open1 || open2 {
                tokio::select! {
                    v = rx1.recv(), if open1 => take(v, &mut open1, &mut sum),
                    v = rx2.recv(), if open2 => take(v, &mut open2, &mut sum),
                }
            }
        }
        (false, true) => {
            while open1 || open2 {
                tokio::select! {
                    biased;
                    v = rx1.recv(), if open1 => take(v, &mut open1, &mut sum),
                    v = rx2.recv(), if open2 => take(v, &mut open2, &mut sum),
                }
            }
        }
        (true, false) => {
            while open1 || open2 {
                tokio::select! {
                    k = rx1.recv_many(&mut buf1, BATCH), if open1 => drain(k, &mut buf1, &mut open1, &mut sum),
                    k = rx2.recv_many(&mut buf2, BATCH), if open2 => drain(k, &mut buf2, &mut open2, &mut sum),
                }
            }
        }
        (true, true) => {
            while open1 || open2 {
                tokio::select! {
                    biased;
                    k = rx1.recv_many(&mut buf1, BATCH), if open1 => drain(k, &mut buf1, &mut open1, &mut sum),
                    k = rx2.recv_many(&mut buf2, BATCH), if open2 => drain(k, &mut buf2, &mut open2, &mut sum),
                }
            }
        }
    }
    sum
}

fn take(v: Option<u64>, open: &mut bool, sum: &mut u64) {
    match v {
        Some(v) => *sum = sum.wrapping_add(v),
        None => *open = false,
    }
}

fn drain(k: usize, buf: &mut Vec<u64>, open: &mut bool, sum: &mut u64) {
    if k == 0 {
        *open = false;
    }
    for v in buf.drain(..) {
        *sum = sum.wrapping_add(v);
    }
}

async fn mutex(a: Args) -> Report {
    let per = a.size / a.workers as u64;
    let (elapsed, total) = if a.has("std-mutex") {
        let counter = Arc::new(std::sync::Mutex::new(0u64));
        let elapsed = run_workers(&a, || {
            let counter = counter.clone();
            async move {
                for _ in 0..per {
                    *counter.lock().unwrap() += 1;
                }
            }
        })
        .await;
        let total = *counter.lock().unwrap();
        (elapsed, total)
    } else if a.has("parking-lot") {
        let counter = Arc::new(parking_lot::Mutex::new(0u64));
        let elapsed = run_workers(&a, || {
            let counter = counter.clone();
            async move {
                for _ in 0..per {
                    *counter.lock() += 1;
                }
            }
        })
        .await;
        let total = *counter.lock();
        (elapsed, total)
    } else {
        let counter = Arc::new(Mutex::new(0u64));
        let elapsed = run_workers(&a, || {
            let counter = counter.clone();
            async move {
                for _ in 0..per {
                    *counter.lock().await += 1;
                }
            }
        })
        .await;
        let total = *counter.lock().await;
        (elapsed, total)
    };
    Report::ok(name(), &a, per * a.workers as u64, elapsed, total)
}

async fn run_workers<F, Fut>(a: &Args, make: F) -> Duration
where
    F: Fn() -> Fut,
    Fut: Future<Output = ()> + Send + 'static,
{
    let mut handles = Vec::with_capacity(a.workers);
    let start = Instant::now();
    for _ in 0..a.workers {
        handles.push(spawn_on(a, make()));
    }
    for h in handles {
        h.await.unwrap();
    }
    start.elapsed()
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
    Report::ok(name(), &a, n, elapsed, finished.load(Ordering::Relaxed)).with_memory(before, after, n)
}
