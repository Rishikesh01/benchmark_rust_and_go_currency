package main

// Line-for-line counterpart of rust/common/src/lib.rs: CLI flags, JSON result
// shape, CPU kernel and percentile maths must stay identical.

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"time"
)

type Args struct {
	Workload    string
	Threads     int
	Size        uint64
	Capacity    int
	Producers   int
	Consumers   int
	Workers     int
	Tasks       int
	Rounds      int
	SampleEvery uint64
	SettleMs    int
}

func parseArgs() Args {
	var a Args
	flag.StringVar(&a.Workload, "workload", "", "workload name")
	flag.IntVar(&a.Threads, "threads", runtime.NumCPU(), "GOMAXPROCS")
	flag.Uint64Var(&a.Size, "size", 1_000_000, "total operations")
	flag.IntVar(&a.Capacity, "capacity", 1024, "channel buffer size")
	flag.IntVar(&a.Producers, "producers", 4, "mpmc producers")
	flag.IntVar(&a.Consumers, "consumers", 4, "mpmc consumers")
	flag.IntVar(&a.Workers, "workers", 8, "mutex workers")
	flag.IntVar(&a.Tasks, "tasks", 256, "cpu chunks")
	flag.IntVar(&a.Rounds, "rounds", 32, "cpu mix rounds per item")
	flag.Uint64Var(&a.SampleEvery, "sample-every", 17, "pingpong latency sampling interval")
	flag.IntVar(&a.SettleMs, "settle-ms", 200, "idle settle time before reading RSS")
	flag.Parse()
	if a.Workload == "" {
		fail("--workload is required")
	}
	if a.Threads < 1 || a.Producers < 1 || a.Consumers < 1 || a.Workers < 1 || a.Tasks < 1 {
		fail("thread/worker/task counts must be >= 1")
	}
	a.SampleEvery = max(a.SampleEvery, 1)
	return a
}

func fail(msg string) {
	fmt.Fprintf(os.Stderr, "error: %s\n", msg)
	os.Exit(2)
}

type Report struct {
	Impl         string   `json:"impl"`
	Workload     string   `json:"workload"`
	Status       string   `json:"status"`
	Reason       *string  `json:"reason"`
	Threads      int      `json:"threads"`
	Size         uint64   `json:"size"`
	Params       Params   `json:"params"`
	Ops          uint64   `json:"ops"`
	WallNs       uint64   `json:"wall_ns"`
	OpsPerSec    float64  `json:"ops_per_sec"`
	Checksum     uint64   `json:"checksum"`
	LatP50Ns     *uint64  `json:"lat_p50_ns"`
	LatP99Ns     *uint64  `json:"lat_p99_ns"`
	LatP999Ns    *uint64  `json:"lat_p999_ns"`
	PeakRssKb    *uint64  `json:"peak_rss_kb"`
	RssDeltaKb   *uint64  `json:"rss_delta_kb"`
	BytesPerTask *float64 `json:"bytes_per_task"`
}

// Params echoes the workload parameters a run actually used, so the runner can check them.
type Params struct {
	Capacity    int    `json:"capacity"`
	Producers   int    `json:"producers"`
	Consumers   int    `json:"consumers"`
	Workers     int    `json:"workers"`
	Tasks       int    `json:"tasks"`
	Rounds      int    `json:"rounds"`
	SampleEvery uint64 `json:"sample-every"`
	SettleMs    int    `json:"settle-ms"`
}

const implName = "go"

func okReport(a Args, ops uint64, wall time.Duration, checksum uint64) *Report {
	return &Report{
		Impl: implName, Workload: a.Workload, Status: "ok", Threads: a.Threads, Size: a.Size,
		Params: Params{a.Capacity, a.Producers, a.Consumers, a.Workers, a.Tasks, a.Rounds, a.SampleEvery, a.SettleMs},
		Ops:    ops, WallNs: uint64(wall.Nanoseconds()), Checksum: checksum,
	}
}

func (r *Report) withLatencies(samples []uint64) *Report {
	if len(samples) > 0 {
		slices.Sort(samples)
		p50, p99, p999 := percentile(samples, 0.50), percentile(samples, 0.99), percentile(samples, 0.999)
		r.LatP50Ns, r.LatP99Ns, r.LatP999Ns = &p50, &p99, &p999
	}
	return r
}

func (r *Report) withMemory(beforeKb, afterKb, tasks uint64) *Report {
	var delta uint64
	if afterKb > beforeKb {
		delta = afterKb - beforeKb
	}
	perTask := float64(delta) * 1024.0 / float64(max(tasks, 1))
	r.RssDeltaKb, r.BytesPerTask = &delta, &perTask
	return r
}

func (r *Report) print() {
	if r.WallNs > 0 {
		r.OpsPerSec = float64(r.Ops) * 1e9 / float64(r.WallNs)
	}
	if hwm, ok := procStatusKb("VmHWM"); ok {
		r.PeakRssKb = &hwm
	}
	out, err := json.Marshal(r)
	if err != nil {
		fail(err.Error())
	}
	fmt.Println(string(out))
}

// Nearest-rank percentile on an already sorted slice.
func percentile(sorted []uint64, p float64) uint64 {
	idx := int(float64(len(sorted)) * p)
	return sorted[min(idx, len(sorted)-1)]
}

// Resident memory in kB. smaps_rollup is exact; VmRSS in /proc/self/status is updated in per-CPU batches
// (tens to hundreds of kB), which is too coarse for per-task memory at 10K tasks.
func procRssKb() (uint64, bool) {
	if data, err := os.ReadFile("/proc/self/smaps_rollup"); err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			if rest, found := strings.CutPrefix(line, "Rss:"); found {
				if fields := strings.Fields(rest); len(fields) > 0 {
					if v, err := strconv.ParseUint(fields[0], 10, 64); err == nil {
						return v, true
					}
				}
			}
		}
	}
	return procStatusKb("VmRSS")
}

// Reads a kB field (e.g. VmRSS, VmHWM) from /proc/self/status.
func procStatusKb(field string) (uint64, bool) {
	data, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return 0, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if rest, found := strings.CutPrefix(line, field+":"); found {
			fields := strings.Fields(rest)
			if len(fields) == 0 {
				return 0, false
			}
			v, err := strconv.ParseUint(fields[0], 10, 64)
			return v, err == nil
		}
	}
	return 0, false
}

// splitmix64 finaliser: the CPU-bound kernel shared with Rust.
func mix(z uint64) uint64 {
	z += 0x9E3779B97F4A7C15
	z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9
	z = (z ^ (z >> 27)) * 0x94D049BB133111EB
	return z ^ (z >> 31)
}

// Wrapping sum of mix^rounds(i) for i in [lo, hi).
func cpuRange(lo, hi uint64, rounds int) uint64 {
	var sum uint64
	for i := lo; i < hi; i++ {
		x := i
		for r := 0; r < rounds; r++ {
			x = mix(x)
		}
		sum += x
	}
	return sum
}

// Splits [0, n) into `chunks` contiguous ranges.
func chunkBounds(n uint64, chunks, c int) (uint64, uint64) {
	size := (n + uint64(chunks) - 1) / uint64(chunks)
	lo := min(uint64(c)*size, n)
	return lo, min(lo+size, n)
}
