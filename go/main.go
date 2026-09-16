// Go implementations of every workload, using goroutines and channels.
package main

import (
	"runtime"
	"sync"
	"sync/atomic"
	"time"
)

func main() {
	a := parseArgs()
	// Setting GOMAXPROCS explicitly also disables Go's automatic adjustment.
	runtime.GOMAXPROCS(a.Threads)
	var r *Report
	switch a.Workload {
	case "spsc":
		r = spsc(a)
	case "mpmc":
		r = mpmc(a)
	case "pingpong":
		r = pingpong(a)
	case "spawn":
		r = spawn(a)
	case "cpu":
		r = cpu(a)
	case "select":
		r = selectWorkload(a)
	case "mutex":
		r = mutex(a)
	case "idle":
		r = idle(a)
	default:
		fail("unknown workload " + a.Workload)
	}
	r.print()
}

func spsc(a Args) *Report {
	n := a.Size
	ch := make(chan uint64, a.Capacity)
	var sum uint64
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(2)
	go func() {
		defer wg.Done()
		for i := uint64(0); i < n; i++ {
			ch <- i
		}
		close(ch)
	}()
	go func() {
		defer wg.Done()
		for v := range ch {
			sum += v
		}
	}()
	wg.Wait()
	return okReport(a, n, time.Since(start), sum)
}

func mpmc(a Args) *Report {
	per := a.Size / uint64(a.Producers)
	total := per * uint64(a.Producers)
	ch := make(chan uint64, a.Capacity)
	sums := make([]uint64, a.Consumers)
	var producers, consumers sync.WaitGroup
	start := time.Now()
	consumers.Add(a.Consumers)
	for c := 0; c < a.Consumers; c++ {
		go func(c int) {
			defer consumers.Done()
			var s uint64
			for v := range ch {
				s += v
			}
			sums[c] = s
		}(c)
	}
	producers.Add(a.Producers)
	for p := 0; p < a.Producers; p++ {
		go func(p uint64) {
			defer producers.Done()
			base := p * per
			for i := uint64(0); i < per; i++ {
				ch <- base + i
			}
		}(uint64(p))
	}
	producers.Wait()
	close(ch)
	consumers.Wait()
	var sum uint64
	for _, s := range sums {
		sum += s
	}
	return okReport(a, total, time.Since(start), sum)
}

// Capacity-1 channels (not unbuffered) to match Tokio's minimum capacity.
func pingpong(a Args) *Report {
	n, every := a.Size, a.SampleEvery
	toB := make(chan uint64, 1)
	toA := make(chan uint64, 1)
	samples := make([]uint64, 0, n/every+1)
	var token uint64
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(2)
	go func() {
		defer wg.Done()
		for v := range toB {
			toA <- v + 1
		}
	}()
	go func() {
		defer wg.Done()
		for i := uint64(0); i < n; i++ {
			sample := i%every == 0
			var t0 time.Time
			if sample {
				t0 = time.Now()
			}
			toB <- token + 1
			token = <-toA
			if sample {
				samples = append(samples, uint64(time.Since(t0).Nanoseconds()))
			}
		}
		close(toB)
	}()
	wg.Wait()
	return okReport(a, n, time.Since(start), token).withLatencies(samples)
}

func spawn(a Args) *Report {
	n := a.Size
	results := make([]uint64, n)
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(int(n))
	for i := uint64(0); i < n; i++ {
		go func(i uint64) {
			results[i] = i
			wg.Done()
		}(i)
	}
	wg.Wait()
	var sum uint64
	for _, v := range results {
		sum += v
	}
	return okReport(a, n, time.Since(start), sum)
}

func cpu(a Args) *Report {
	n, chunks, rounds := a.Size, a.Tasks, a.Rounds
	results := make([]uint64, chunks)
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(chunks)
	for c := 0; c < chunks; c++ {
		lo, hi := chunkBounds(n, chunks, c)
		go func(c int) {
			results[c] = cpuRange(lo, hi, rounds)
			wg.Done()
		}(c)
	}
	wg.Wait()
	var sum uint64
	for _, v := range results {
		sum += v
	}
	return okReport(a, n, time.Since(start), sum)
}

func selectWorkload(a Args) *Report {
	half := a.Size / 2
	ch1 := make(chan uint64, a.Capacity)
	ch2 := make(chan uint64, a.Capacity)
	var sum uint64
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(3)
	go func() {
		defer wg.Done()
		for i := uint64(0); i < half; i++ {
			ch1 <- i
		}
		close(ch1)
	}()
	go func() {
		defer wg.Done()
		for i := half; i < 2*half; i++ {
			ch2 <- i
		}
		close(ch2)
	}()
	go func() {
		defer wg.Done()
		var r1, r2 <-chan uint64 = ch1, ch2
		for r1 != nil || r2 != nil {
			select {
			case v, ok := <-r1:
				if !ok {
					r1 = nil
				} else {
					sum += v
				}
			case v, ok := <-r2:
				if !ok {
					r2 = nil
				} else {
					sum += v
				}
			}
		}
	}()
	wg.Wait()
	return okReport(a, 2*half, time.Since(start), sum)
}

func mutex(a Args) *Report {
	per := a.Size / uint64(a.Workers)
	var mu sync.Mutex
	var counter uint64
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(a.Workers)
	for w := 0; w < a.Workers; w++ {
		go func() {
			defer wg.Done()
			for i := uint64(0); i < per; i++ {
				mu.Lock()
				counter++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	elapsed := time.Since(start)
	mu.Lock()
	total := counter
	mu.Unlock()
	return okReport(a, per*uint64(a.Workers), elapsed, total)
}

// Memory per parked goroutine. Goroutines wait on a channel that is closed
// once RSS has been sampled.
func idle(a Args) *Report {
	n := a.Size
	gate := make(chan struct{})
	var parked, finished atomic.Uint64
	var wg sync.WaitGroup
	before, _ := procStatusKb("VmRSS")
	start := time.Now()
	wg.Add(int(n))
	for i := uint64(0); i < n; i++ {
		go func() {
			parked.Add(1)
			<-gate
			finished.Add(1)
			wg.Done()
		}()
	}
	for parked.Load() < n {
		time.Sleep(time.Millisecond)
	}
	elapsed := time.Since(start)
	time.Sleep(time.Duration(a.SettleMs) * time.Millisecond)
	after, _ := procStatusKb("VmRSS")
	close(gate)
	wg.Wait()
	return okReport(a, n, elapsed, finished.Load()).withMemory(before, after, n)
}
