//! Crossbeam implementations of every workload, on plain OS threads.
//!
//! Long-lived worker threads start together through a `StartLine`, which
//! keeps OS thread creation out of the timed section (Tokio's worker pool also
//! exists before its timer starts). `spawn` and `idle` measure thread creation
//! itself, so they don't use one.

use common::{chunk_bounds, cpu_range, fail, proc_rss_kb, Args, Report, MAX_OS_THREADS};
use crossbeam::channel::{bounded, never, select};
use crossbeam::deque::{Injector, Stealer, Worker};
use crossbeam::thread;
use crossbeam::utils::Backoff;
use std::iter;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Barrier, Mutex, OnceLock};
use std::time::{Duration, Instant};

const IMPL: &str = "crossbeam";

/// Releases workers together and records when the first one starts working.
///
/// The clock is read by a worker, not by the joining thread: with few CPUs the
/// joining thread may not be scheduled again until the workers have finished.
struct StartLine {
    barrier: Barrier,
    start: OnceLock<Instant>,
}

impl StartLine {
    fn new(workers: usize) -> StartLine {
        StartLine { barrier: Barrier::new(workers), start: OnceLock::new() }
    }

    fn go(&self) {
        self.barrier.wait();
        self.start.get_or_init(Instant::now);
    }

    fn elapsed(&self) -> Duration {
        self.start.get().expect("no worker started").elapsed()
    }
}

fn main() {
    let a = Args::parse();
    let report = match a.workload.as_str() {
        "spsc" => spsc(&a),
        "mpmc" => mpmc(&a),
        "pingpong" => pingpong(&a),
        "spawn" => spawn(&a),
        "cpu" => cpu(&a),
        "select" => select(&a),
        "mutex" => mutex(&a),
        "idle" => idle(&a),
        other => fail(&format!("unknown workload {other}")),
    };
    report.print();
}

fn spsc(a: &Args) -> Report {
    let n = a.size;
    let (tx, rx) = bounded::<u64>(a.capacity);
    let line = StartLine::new(2);
    thread::scope(|s| {
        let producer = s.spawn(|_| {
            line.go();
            for i in 0..n {
                tx.send(i).unwrap();
            }
            drop(tx);
        });
        let consumer = s.spawn(|_| {
            line.go();
            let mut sum = 0u64;
            for v in rx.iter() {
                sum = sum.wrapping_add(v);
            }
            sum
        });
        producer.join().unwrap();
        let sum = consumer.join().unwrap();
        Report::ok(IMPL, a, n, line.elapsed(), sum)
    })
    .unwrap()
}

fn mpmc(a: &Args) -> Report {
    let per = a.size / a.producers as u64;
    let total = per * a.producers as u64;
    let (tx, rx) = bounded::<u64>(a.capacity);
    let line = StartLine::new(a.producers + a.consumers);
    thread::scope(|s| {
        let consumers: Vec<_> = (0..a.consumers)
            .map(|_| {
                let (rx, line) = (rx.clone(), &line);
                s.spawn(move |_| {
                    line.go();
                    let mut sum = 0u64;
                    for v in rx.iter() {
                        sum = sum.wrapping_add(v);
                    }
                    sum
                })
            })
            .collect();
        drop(rx);
        let producers: Vec<_> = (0..a.producers as u64)
            .map(|p| {
                let (tx, line) = (tx.clone(), &line);
                s.spawn(move |_| {
                    line.go();
                    let base = p * per;
                    for i in 0..per {
                        tx.send(base + i).unwrap();
                    }
                })
            })
            .collect();
        drop(tx);
        for p in producers {
            p.join().unwrap();
        }
        let sum = consumers.into_iter().fold(0u64, |acc, c| acc.wrapping_add(c.join().unwrap()));
        Report::ok(IMPL, a, total, line.elapsed(), sum)
    })
    .unwrap()
}

/// Capacity-1 channels (not rendezvous) to match Tokio's minimum capacity.
fn pingpong(a: &Args) -> Report {
    let n = a.size;
    let every = a.sample_every;
    let (to_b, b_rx) = bounded::<u64>(1);
    let (to_a, a_rx) = bounded::<u64>(1);
    let line = StartLine::new(2);
    thread::scope(|s| {
        let b = s.spawn(|_| {
            line.go();
            for v in b_rx.iter() {
                if to_a.send(v + 1).is_err() {
                    break;
                }
            }
        });
        let a_side = s.spawn(|_| {
            let mut samples = Vec::with_capacity((n / every + 1) as usize);
            line.go();
            let mut token = 0u64;
            for i in 0..n {
                let t0 = (i % every == 0).then(Instant::now);
                to_b.send(token + 1).unwrap();
                token = a_rx.recv().unwrap();
                if let Some(t0) = t0 {
                    samples.push(t0.elapsed().as_nanos() as u64);
                }
            }
            drop(to_b);
            (token, samples)
        });
        let (token, mut samples) = a_side.join().unwrap();
        b.join().unwrap();
        Report::ok(IMPL, a, n, line.elapsed(), token).with_latencies(&mut samples)
    })
    .unwrap()
}

/// One untimed pass first, as in every implementation, so the timed pass runs in a warm process.
fn spawn(a: &Args) -> Report {
    let n = a.size;
    if n > MAX_OS_THREADS {
        return Report::skipped(IMPL, a, format!("one OS thread per task; capped at {MAX_OS_THREADS}"));
    }
    spawn_join(n);
    let (elapsed, sum) = spawn_join(n);
    Report::ok(IMPL, a, n, elapsed, sum)
}

fn spawn_join(n: u64) -> (Duration, u64) {
    thread::scope(|s| {
        let mut handles = Vec::with_capacity(n as usize);
        let start = Instant::now();
        for i in 0..n {
            handles.push(s.spawn(move |_| i));
        }
        let sum = handles.into_iter().fold(0u64, |acc, h| acc.wrapping_add(h.join().unwrap()));
        (start.elapsed(), sum)
    })
    .unwrap()
}

/// Work-stealing pool: chunks go into a global `Injector`, `threads` workers
/// each own a FIFO deque and steal from the injector and from each other.
fn cpu(a: &Args) -> Report {
    let (n, chunks, rounds) = (a.size, a.tasks, a.rounds);
    let injector = Injector::new();
    // Queue everything before workers start: an empty injector means "done".
    for c in 0..chunks {
        injector.push(chunk_bounds(n, chunks, c));
    }
    let locals: Vec<Worker<(u64, u64)>> = (0..a.threads).map(|_| Worker::new_fifo()).collect();
    let stealers: Vec<Stealer<(u64, u64)>> = locals.iter().map(Worker::stealer).collect();
    // Workers stop when this reaches zero. Empty queues alone aren't enough: a batch being moved by
    // steal_batch_and_pop is briefly in neither queue, and a worker that quit then would be lost.
    let remaining = AtomicUsize::new(chunks);
    let line = StartLine::new(a.threads);
    thread::scope(|s| {
        let handles: Vec<_> = locals
            .into_iter()
            .map(|local| {
                let (injector, stealers, line, remaining) = (&injector, &stealers, &line, &remaining);
                s.spawn(move |_| {
                    line.go();
                    let mut sum = 0u64;
                    let backoff = Backoff::new();
                    loop {
                        match find_task(&local, injector, stealers) {
                            Some((lo, hi)) => {
                                sum = sum.wrapping_add(cpu_range(lo, hi, rounds));
                                remaining.fetch_sub(1, Ordering::Relaxed);
                                backoff.reset();
                            }
                            None if remaining.load(Ordering::Relaxed) == 0 => break,
                            None => backoff.snooze(),
                        }
                    }
                    sum
                })
            })
            .collect();
        let sum = handles.into_iter().fold(0u64, |acc, h| acc.wrapping_add(h.join().unwrap()));
        Report::ok(IMPL, a, n, line.elapsed(), sum)
    })
    .unwrap()
}

/// Canonical task lookup from the crossbeam-deque documentation.
fn find_task<T>(local: &Worker<T>, global: &Injector<T>, stealers: &[Stealer<T>]) -> Option<T> {
    local.pop().or_else(|| {
        iter::repeat_with(|| {
            global.steal_batch_and_pop(local).or_else(|| stealers.iter().map(Stealer::steal).collect())
        })
        .find(|s| !s.is_retry())
        .and_then(|s| s.success())
    })
}

fn select(a: &Args) -> Report {
    let half = a.size / 2;
    let (tx1, rx1) = bounded::<u64>(a.capacity);
    let (tx2, rx2) = bounded::<u64>(a.capacity);
    let line = StartLine::new(3);
    thread::scope(|s| {
        let p1 = s.spawn(|_| {
            line.go();
            for i in 0..half {
                tx1.send(i).unwrap();
            }
            drop(tx1);
        });
        let p2 = s.spawn(|_| {
            line.go();
            for i in half..2 * half {
                tx2.send(i).unwrap();
            }
            drop(tx2);
        });
        let consumer = s.spawn(|_| {
            line.go();
            let (mut r1, mut r2) = (rx1, rx2);
            let (mut open1, mut open2) = (true, true);
            let mut sum = 0u64;
            while open1 || open2 {
                select! {
                    recv(r1) -> m => match m {
                        Ok(v) => sum = sum.wrapping_add(v),
                        Err(_) => { r1 = never(); open1 = false; }
                    },
                    recv(r2) -> m => match m {
                        Ok(v) => sum = sum.wrapping_add(v),
                        Err(_) => { r2 = never(); open2 = false; }
                    },
                }
            }
            sum
        });
        p1.join().unwrap();
        p2.join().unwrap();
        let sum = consumer.join().unwrap();
        Report::ok(IMPL, a, 2 * half, line.elapsed(), sum)
    })
    .unwrap()
}

fn mutex(a: &Args) -> Report {
    let per = a.size / a.workers as u64;
    let counter = Mutex::new(0u64);
    let line = StartLine::new(a.workers);
    thread::scope(|s| {
        let handles: Vec<_> = (0..a.workers)
            .map(|_| {
                let (counter, line) = (&counter, &line);
                s.spawn(move |_| {
                    line.go();
                    for _ in 0..per {
                        *counter.lock().unwrap() += 1;
                    }
                })
            })
            .collect();
        for h in handles {
            h.join().unwrap();
        }
        let elapsed = line.elapsed();
        Report::ok(IMPL, a, per * a.workers as u64, elapsed, *counter.lock().unwrap())
    })
    .unwrap()
}

/// Memory per parked OS thread. RSS covers touched stack pages and user-space
/// state only; kernel task structures are not included.
fn idle(a: &Args) -> Report {
    let n = a.size;
    if n > MAX_OS_THREADS {
        return Report::skipped(IMPL, a, format!("one OS thread per task; capped at {MAX_OS_THREADS}"));
    }
    let (gate_tx, gate_rx) = bounded::<()>(0);
    let parked = AtomicU64::new(0);
    let finished = AtomicU64::new(0);
    let before = proc_rss_kb().unwrap_or(0);
    thread::scope(|s| {
        let start = Instant::now();
        for _ in 0..n {
            s.spawn(|_| {
                parked.fetch_add(1, Ordering::Relaxed);
                let _ = gate_rx.recv();
                finished.fetch_add(1, Ordering::Relaxed);
            });
        }
        while parked.load(Ordering::Relaxed) < n {
            std::thread::sleep(Duration::from_millis(1));
        }
        let elapsed = start.elapsed();
        std::thread::sleep(Duration::from_millis(a.settle_ms));
        let after = proc_rss_kb().unwrap_or(0);
        drop(gate_tx);
        (elapsed, after)
    })
    .map(|(elapsed, after)| {
        Report::ok(IMPL, a, n, elapsed, finished.load(Ordering::Relaxed)).with_memory(before, after, n)
    })
    .unwrap()
}
