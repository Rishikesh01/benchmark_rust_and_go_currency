//! Shared harness for the Rust benchmark binaries.
//!
//! Everything here has a line-for-line counterpart in `go/harness.go` so the
//! CLI, the JSON result shape, the CPU kernel and the percentile maths are
//! identical across implementations.

use std::time::Duration;

/// Hard cap on concurrently live OS threads for thread-per-task workloads.
pub const MAX_OS_THREADS: u64 = 20_000;

#[derive(Clone, Debug)]
pub struct Args {
    pub workload: String,
    pub threads: usize,
    pub size: u64,
    pub capacity: usize,
    pub producers: usize,
    pub consumers: usize,
    pub workers: usize,
    pub tasks: usize,
    pub rounds: u32,
    pub sample_every: u64,
    pub settle_ms: u64,
    /// Implementation-specific tweaks (`--variant a,b`); empty means defaults.
    pub variants: Vec<String>,
}

impl Args {
    pub fn parse() -> Args {
        let mut a = Args {
            workload: String::new(),
            threads: std::thread::available_parallelism().map_or(1, |n| n.get()),
            size: 1_000_000,
            capacity: 1024,
            producers: 4,
            consumers: 4,
            workers: 8,
            tasks: 256,
            rounds: 32,
            sample_every: 16,
            settle_ms: 200,
            variants: Vec::new(),
        };
        let raw: Vec<String> = std::env::args().skip(1).collect();
        let mut i = 0;
        while i < raw.len() {
            let arg = raw[i].trim_start_matches('-');
            let (key, value) = match arg.split_once('=') {
                Some((k, v)) => (k.to_string(), v.to_string()),
                None => {
                    i += 1;
                    let v = raw.get(i).unwrap_or_else(|| fail(&format!("missing value for --{arg}")));
                    (arg.to_string(), v.clone())
                }
            };
            i += 1;
            match key.as_str() {
                "workload" => a.workload = value,
                "threads" => a.threads = num(&key, &value),
                "size" => a.size = num(&key, &value),
                "capacity" => a.capacity = num(&key, &value),
                "producers" => a.producers = num(&key, &value),
                "consumers" => a.consumers = num(&key, &value),
                "workers" => a.workers = num(&key, &value),
                "tasks" => a.tasks = num(&key, &value),
                "rounds" => a.rounds = num(&key, &value),
                "sample-every" => a.sample_every = num(&key, &value),
                "settle-ms" => a.settle_ms = num(&key, &value),
                "variant" => a.variants = value.split(',').filter(|v| !v.is_empty()).map(str::to_string).collect(),
                _ => fail(&format!("unknown flag --{key}")),
            }
        }
        if a.workload.is_empty() {
            fail("--workload is required");
        }
        if a.threads == 0 || a.producers == 0 || a.consumers == 0 || a.workers == 0 || a.tasks == 0 {
            fail("thread/worker/task counts must be >= 1");
        }
        a.sample_every = a.sample_every.max(1);
        a
    }

    pub fn has(&self, variant: &str) -> bool {
        self.variants.iter().any(|v| v == variant)
    }
}

fn num<T: std::str::FromStr>(key: &str, value: &str) -> T {
    value.replace('_', "").parse().unwrap_or_else(|_| fail(&format!("bad value for --{key}: {value}")))
}

pub fn fail(msg: &str) -> ! {
    eprintln!("error: {msg}");
    std::process::exit(2);
}

/// One benchmark result. Serialised as a single JSON line on stdout.
#[derive(Default)]
pub struct Report {
    pub implementation: String,
    pub workload: String,
    pub status: &'static str,
    pub reason: Option<String>,
    pub threads: usize,
    pub size: u64,
    pub ops: u64,
    pub wall_ns: u64,
    pub checksum: u64,
    pub lat_p50_ns: Option<u64>,
    pub lat_p99_ns: Option<u64>,
    pub lat_p999_ns: Option<u64>,
    pub rss_delta_kb: Option<u64>,
    pub bytes_per_task: Option<f64>,
}

impl Report {
    pub fn ok(implementation: &str, a: &Args, ops: u64, wall: Duration, checksum: u64) -> Report {
        Report {
            implementation: implementation.to_string(),
            workload: a.workload.clone(),
            status: "ok",
            threads: a.threads,
            size: a.size,
            ops,
            wall_ns: wall.as_nanos() as u64,
            checksum,
            ..Default::default()
        }
    }

    pub fn skipped(implementation: &str, a: &Args, reason: String) -> Report {
        Report {
            implementation: implementation.to_string(),
            workload: a.workload.clone(),
            status: "skipped",
            reason: Some(reason),
            threads: a.threads,
            size: a.size,
            ..Default::default()
        }
    }

    pub fn with_latencies(mut self, samples: &mut [u64]) -> Report {
        if !samples.is_empty() {
            samples.sort_unstable();
            self.lat_p50_ns = Some(percentile(samples, 0.50));
            self.lat_p99_ns = Some(percentile(samples, 0.99));
            self.lat_p999_ns = Some(percentile(samples, 0.999));
        }
        self
    }

    pub fn with_memory(mut self, before_kb: u64, after_kb: u64, tasks: u64) -> Report {
        let delta = after_kb.saturating_sub(before_kb);
        self.rss_delta_kb = Some(delta);
        self.bytes_per_task = Some(delta as f64 * 1024.0 / tasks.max(1) as f64);
        self
    }

    pub fn print(&self) {
        let ops_per_sec = if self.wall_ns > 0 { self.ops as f64 * 1e9 / self.wall_ns as f64 } else { 0.0 };
        let opt = |v: Option<u64>| v.map_or("null".to_string(), |v| v.to_string());
        let optf = |v: Option<f64>| v.map_or("null".to_string(), |v| format!("{v:.1}"));
        let s = |v: &str| format!("\"{}\"", v.replace('\\', "\\\\").replace('"', "\\\""));
        println!(
            "{{\"impl\":{},\"workload\":{},\"status\":{},\"reason\":{},\"threads\":{},\"size\":{},\"ops\":{},\
             \"wall_ns\":{},\"ops_per_sec\":{:.1},\"checksum\":{},\"lat_p50_ns\":{},\"lat_p99_ns\":{},\
             \"lat_p999_ns\":{},\"peak_rss_kb\":{},\"rss_delta_kb\":{},\"bytes_per_task\":{}}}",
            s(&self.implementation),
            s(&self.workload),
            s(self.status),
            self.reason.as_deref().map_or("null".to_string(), s),
            self.threads,
            self.size,
            self.ops,
            self.wall_ns,
            ops_per_sec,
            self.checksum,
            opt(self.lat_p50_ns),
            opt(self.lat_p99_ns),
            opt(self.lat_p999_ns),
            opt(proc_status_kb("VmHWM")),
            opt(self.rss_delta_kb),
            optf(self.bytes_per_task),
        );
    }
}

/// Nearest-rank percentile on an already sorted slice.
pub fn percentile(sorted: &[u64], p: f64) -> u64 {
    let idx = ((sorted.len() as f64) * p) as usize;
    sorted[idx.min(sorted.len() - 1)]
}

/// Reads a `kB` field (e.g. `VmRSS`, `VmHWM`) from /proc/self/status.
pub fn proc_status_kb(field: &str) -> Option<u64> {
    let status = std::fs::read_to_string("/proc/self/status").ok()?;
    status
        .lines()
        .find(|l| l.starts_with(field) && l[field.len()..].starts_with(':'))
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|v| v.parse().ok())
}

/// splitmix64 finaliser: the CPU-bound kernel shared with Go.
#[inline]
pub fn mix(mut z: u64) -> u64 {
    z = z.wrapping_add(0x9E37_79B9_7F4A_7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

/// Wrapping sum of `mix^rounds(i)` for i in [lo, hi).
pub fn cpu_range(lo: u64, hi: u64, rounds: u32) -> u64 {
    let mut sum = 0u64;
    for i in lo..hi {
        let mut x = i;
        for _ in 0..rounds {
            x = mix(x);
        }
        sum = sum.wrapping_add(x);
    }
    sum
}

/// Splits [0, n) into `chunks` contiguous ranges.
pub fn chunk_bounds(n: u64, chunks: usize, c: usize) -> (u64, u64) {
    let size = n.div_ceil(chunks as u64);
    let lo = (c as u64 * size).min(n);
    (lo, (lo + size).min(n))
}
