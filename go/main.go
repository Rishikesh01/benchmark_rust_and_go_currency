// Go implementations of every workload, using goroutines and channels.
//
// Every goroutine runs a named function, so flame graphs show main.produce,
// main.consume and so on instead of anonymous main.spsc.func1-style closures.
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
	case "mpsc":
		r = manyToOne(a)
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
	go produce(ch, 0, n, true, &wg)
	go consume(ch, &sum, &wg)
	wg.Wait()
	return okReport(a, n, time.Since(start), sum)
}

// Sends lo..hi-1, then closes the channel if it is the only sender.
func produce(ch chan<- uint64, lo, hi uint64, closeWhenDone bool, wg *sync.WaitGroup) {
	defer wg.Done()
	for i := lo; i < hi; i++ {
		ch <- i
	}
	if closeWhenDone {
		close(ch)
	}
}

// Sums everything received until the channel is closed.
func consume(ch <-chan uint64, sum *uint64, wg *sync.WaitGroup) {
	defer wg.Done()
	var s uint64
	for v := range ch {
		s += v
	}
	*sum = s
}

// Several senders, one receiver.
func manyToOne(a Args) *Report {
	per := a.Size / uint64(a.Producers)
	total := per * uint64(a.Producers)
	ch := make(chan uint64, a.Capacity)
	var sum uint64
	var producers, consumer sync.WaitGroup
	start := time.Now()
	consumer.Add(1)
	go consume(ch, &sum, &consumer)
	producers.Add(a.Producers)
	for p := uint64(0); p < uint64(a.Producers); p++ {
		go produce(ch, p*per, (p+1)*per, false, &producers)
	}
	producers.Wait()
	close(ch)
	consumer.Wait()
	return okReport(a, total, time.Since(start), sum)
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
		go consume(ch, &sums[c], &consumers)
	}
	producers.Add(a.Producers)
	for p := uint64(0); p < uint64(a.Producers); p++ {
		go produce(ch, p*per, (p+1)*per, false, &producers)
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
	go pong(toB, toA, &wg)
	go ping(toB, toA, n, every, &token, &samples, &wg)
	wg.Wait()
	return okReport(a, n, time.Since(start), token).withLatencies(samples)
}

// Sends the token n times, waiting for each reply; times every every-th round trip.
func ping(toB chan<- uint64, toA <-chan uint64, n, every uint64, token *uint64, samples *[]uint64, wg *sync.WaitGroup) {
	defer wg.Done()
	var t uint64
	s := *samples
	for i := uint64(0); i < n; i++ {
		sample := i%every == 0
		var t0 time.Time
		if sample {
			t0 = time.Now()
		}
		toB <- t + 1
		t = <-toA
		if sample {
			s = append(s, uint64(time.Since(t0).Nanoseconds()))
		}
	}
	close(toB)
	*token, *samples = t, s
}

// Replies to every token with token + 1 until ping closes its channel.
func pong(toB <-chan uint64, toA chan<- uint64, wg *sync.WaitGroup) {
	defer wg.Done()
	for v := range toB {
		toA <- v + 1
	}
}

// One untimed pass first, as in every implementation, so the timed pass runs in a warm process
// (goroutine stacks, OS threads, heap) instead of paying first-touch costs.
func spawn(a Args) *Report {
	results := make([]uint64, a.Size)
	spawnOnce(results)
	clear(results)
	elapsed, sum := spawnOnce(results)
	return okReport(a, a.Size, elapsed, sum)
}

func spawnOnce(results []uint64) (time.Duration, uint64) {
	n := uint64(len(results))
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(int(n))
	for i := uint64(0); i < n; i++ {
		go record(results, i, &wg)
	}
	wg.Wait()
	var sum uint64
	for _, v := range results {
		sum += v
	}
	return time.Since(start), sum
}

// The spawned goroutine: writes its own index into its slot.
func record(results []uint64, i uint64, wg *sync.WaitGroup) {
	results[i] = i
	wg.Done()
}

func cpu(a Args) *Report {
	n, chunks, rounds := a.Size, a.Tasks, a.Rounds
	results := make([]uint64, chunks)
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(chunks)
	for c := 0; c < chunks; c++ {
		lo, hi := chunkBounds(n, chunks, c)
		go hashChunk(&results[c], lo, hi, rounds, &wg)
	}
	wg.Wait()
	var sum uint64
	for _, v := range results {
		sum += v
	}
	return okReport(a, n, time.Since(start), sum)
}

func hashChunk(result *uint64, lo, hi uint64, rounds int, wg *sync.WaitGroup) {
	*result = cpuRange(lo, hi, rounds)
	wg.Done()
}

func selectWorkload(a Args) *Report {
	half := a.Size / 2
	ch1 := make(chan uint64, a.Capacity)
	ch2 := make(chan uint64, a.Capacity)
	var sum uint64
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(3)
	go produce(ch1, 0, half, true, &wg)
	go produce(ch2, half, 2*half, true, &wg)
	go selectSum(ch1, ch2, &sum, &wg)
	wg.Wait()
	return okReport(a, 2*half, time.Since(start), sum)
}

// Sums everything from both channels, taking whichever is ready, until both close.
func selectSum(r1, r2 <-chan uint64, sum *uint64, wg *sync.WaitGroup) {
	defer wg.Done()
	var s uint64
	for r1 != nil || r2 != nil {
		select {
		case v, ok := <-r1:
			if !ok {
				r1 = nil
			} else {
				s += v
			}
		case v, ok := <-r2:
			if !ok {
				r2 = nil
			} else {
				s += v
			}
		}
	}
	*sum = s
}

func mutex(a Args) *Report {
	per := a.Size / uint64(a.Workers)
	var mu sync.Mutex
	var counter uint64
	var wg sync.WaitGroup
	start := time.Now()
	wg.Add(a.Workers)
	for w := 0; w < a.Workers; w++ {
		go increment(&mu, &counter, per, &wg)
	}
	wg.Wait()
	elapsed := time.Since(start)
	mu.Lock()
	total := counter
	mu.Unlock()
	return okReport(a, per*uint64(a.Workers), elapsed, total)
}

// Adds 1 to the shared counter times times, taking the lock each time.
func increment(mu *sync.Mutex, counter *uint64, times uint64, wg *sync.WaitGroup) {
	defer wg.Done()
	for i := uint64(0); i < times; i++ {
		mu.Lock()
		*counter++
		mu.Unlock()
	}
}

// Memory per parked goroutine. Goroutines wait on a channel that is closed
// once RSS has been sampled.
func idle(a Args) *Report {
	n := a.Size
	gate := make(chan struct{})
	var parked, finished atomic.Uint64
	var wg sync.WaitGroup
	before, _ := procRssKb()
	start := time.Now()
	wg.Add(int(n))
	for i := uint64(0); i < n; i++ {
		go park(gate, &parked, &finished, &wg)
	}
	for parked.Load() < n {
		time.Sleep(time.Millisecond)
	}
	elapsed := time.Since(start)
	time.Sleep(time.Duration(a.SettleMs) * time.Millisecond)
	after, _ := procRssKb()
	close(gate)
	wg.Wait()
	return okReport(a, n, elapsed, finished.Load()).withMemory(before, after, n)
}

// An idle goroutine: counts itself as parked, waits for the gate to close, then counts itself as finished.
func park(gate <-chan struct{}, parked, finished *atomic.Uint64, wg *sync.WaitGroup) {
	parked.Add(1)
	<-gate
	finished.Add(1)
	wg.Done()
}
