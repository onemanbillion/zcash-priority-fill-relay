# Priority fill recalibrated on 24 h of mainnet measurement

The relay monitor (four to eight passive nodes across four regions) collected ~24 h
of mainnet data. This note recalibrates the propagation model with what it measured
and reruns Zebra-today vs priority fill. **The headline: on the real network as it
is today, priority fill does not help; its benefit is confined to full (≈2 MB)
blocks, and grows under NU7's 25 s spacing.** This revises the paper's original
model, which assumed every block was 2 MB on a slower network.

## What the monitor measured (24 h)

- **Reachable network:** 190 distinct Zcash nodes — 107 Zebra, 81 Zakura, 2 zcashd.
- **Blocks are tiny:** median 12.6 kB, p90 64.6 kB; only a brief burst of full 2 MB
  blocks. New-block delivery was no slower than idle at every size — **no upload
  contention at today's block sizes.**
- **Per connection is window/RTT-limited, not uplink-limited:** after TCP slow-start,
  one connection delivers ~334 Mb/s at 22 ms RTT, ~128 Mb/s at 105 ms, ~78 Mb/s at
  217 ms (max 1.7 Gb/s). A 2 MB block takes ~7 round trips.
- **Only ~10–18 % of reachable nodes are genuinely uplink-limited**, median ~78 Mb/s.
  (Reachable nodes skew hosted; NAT'd home nodes, likely slower, can't be probed.)
- **Zakura's announcement queue is the propagation tail:** announce delay p50 9.0 s /
  p90 49 s, vs Zebra p50 0.21 s / p90 1.1 s. Zebra's 7 s gossip gap confirmed.

## Recalibrated model

Opt-in flags in `sim.js` (`measured: true`, `rttModel: true`): per-connection rate =
min(uplink share, congestion-window / RTT) with slow-start (`maxWinKB` tuned to the
measured delivery); node upload capacities from `MEASURED_CLASSES`; per-node fanout
for the 57/43 Zebra/Zakura mix. Hardened priority config (reciprocity + fillIdleS
0.02). 200 nodes, 60 blocks, seeds [1,2]. Stale rate, honest miners.

| Block size | Interval | Today | Priority fill | Δ |
|---|---|---|---|---|
| 12 kB (today) | 75 s | 1.00 % | 1.24 % | **+0.24 %** |
| 12 kB (today) | 25 s (NU7) | 3.93 % | 4.36 % | **+0.44 %** |
| 2 MB (full) | 75 s | 3.77 % | 3.40 % | −0.36 % |
| 2 MB (full) | 25 s (NU7) | 11.04 % | 9.81 % | **−1.23 %** |
| 2 MB, slower network* | 25 s (NU7) | 12.32 % | 9.74 % | **−2.58 %** |

*Original (more pessimistic) capacity classes, standing in for the home/NAT nodes
the monitor can't reach.

## Reading

- **Today (12 kB blocks): priority fill is marginally worse** (+0.2–0.4 % stale).
  With no contention to resolve, its admission staging only adds per-hop latency.
- **Full 2 MB blocks: priority fill helps**, more at 25 s than 75 s (propagation is a
  larger share of the interval), and more on slower networks.
- **NU7 (25 s) does not by itself enlarge blocks**, so the everyday case stays the
  12 kB row. Priority fill matters during spam/large-block periods, or if a future
  block-size increase makes large blocks routine.
- The earlier model overstated the gain (16 %→6 %) by assuming all blocks are 2 MB on
  a slow network; neither holds on the measured network today.

**Design implication:** priority fill should engage only above a block-size
threshold — serve small blocks immediately (as today) and prioritise the uplink only
for large ones — so it never adds latency in the common case.

## Caveats

Approximate: one modelling pass, two seeds, a simplified TCP model, and a reachable-
node sample that misses NAT'd home nodes. Zakura's slot-queue delay is not modelled
(only its all-peer fanout), so the real propagation tail is worse than shown. This is
a model informed by measurement, not a mainnet trial.
