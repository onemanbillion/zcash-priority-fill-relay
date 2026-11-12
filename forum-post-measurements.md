# Priority-fill relay: what mainnet measurement says, before and after NU7

*Follow-up to the ZECATHON "priority-fill block relay" submission. This post reports new measurements and tests done since then. It changes none of the original claims, but it puts real numbers behind them — and NU7 gave us a natural before/after that's worth sharing on its own.*

Since the submission I've been running a small passive measurement system on mainnet to check the proposal's assumptions against reality rather than a model. This writes up what it found, focused on the case the proposal is actually about — **larger blocks** — and where I think the research should go next, including how to make any relay change provably no less safe than today's "upload to everyone in parallel" behaviour.

## What I built

A set of passive monitor nodes (now 8, across US-West, US-East, Amsterdam and Singapore) that connect to as much of the reachable network as they can, never serve blocks, and record, for every block: which node announced it and when (timed from four regions), and how fast each node delivers a block when asked. To measure upload behaviour without being able to see other peers' traffic, each monitor periodically re-downloads a recent block from a node **twice** — once the instant that node is relaying it to its own peers ("busy"), and once in a quiet gap ("idle") — over the same connection. The ratio isolates the effect of the node's uplink being shared.

Caveats up front: these are **reachable** nodes only (NAT'd home nodes that never accept inbound connections can't be probed, and are probably slower than average), the monitors measure a node's upload *to us* as a proxy for what its real peers experience, and this is measurement, not a mainnet trial of priority fill. Numbers below are medians unless stated.

## Bonus: what NU7 did to propagation

NU7 activated on 5 November, taking the target block interval to 25 s. The proposal worried that shorter intervals make propagation delay a larger share of each block's "safe" window. In practice the **opposite** happened to everyday propagation — it got dramatically faster:

| Metric | Before NU7 (30 Oct) | After NU7 (now) |
|---|---|---|
| Block interval (median) | 52 s | 18.7 s |
| Nodes with a block by 0.5 s | 41% | 86% |
| …by 1 s / 10 s | 48% / 69% | 91% / 97% |
| Spread across nodes (p50 / p90) | 2.3 s / 36 s | 0.20 s / 0.73 s |
| Zakura announce delay (p50 / p90) | 9.0 s / 49 s | 0.16 s / 3.1 s |
| Reachable nodes | ~190 | ~400 |

Two things drove this. First, blocks stayed tiny — median block is **~1.7 kB**, 90th percentile ~30 kB. Second, and more striking: the dominant propagation tail before NU7 was Zakura's announcement queue (p90 of 49 s), and that is essentially gone now (p90 3.1 s). That lines up with a Zakura relay change around the NU7 window; if a Zakura dev can confirm what shipped, I'd like to cite it correctly. Zebra's behaviour is unchanged and fast throughout (announce p50 ~0.2 s), with the expected ~2.5 s bump on blocks that land within 7 s of the previous one (its gossip-interval rate limit).

So: **the 25 s upgrade went smoothly, and the everyday network is healthier than before it.** That is good news and worth stating plainly.

## This is exactly what the proposal predicted — because blocks are empty

The proposal's claim was never "25 s blocks cause orphans today." It was that the risk shows up with **larger blocks**, and that Zcash blocks are almost always near-empty so it isn't biting yet. The measurement confirms both halves: empty blocks propagate beautifully, and — as shown next — full blocks don't.

## Large blocks: the contention is real, and it lands early

Over the measurement period there have been **284 full (≈2 MB) blocks** — not organic traffic; someone filling blocks in bursts — giving **5,374 same-node busy-vs-idle pairs**. On these:

- **~20% of full-block relays were uplink-contended** (busy throughput below 70% of idle). The other ~80% showed no slowdown — fast, hosted nodes with uplink to spare.
- When it bites, it bites hard: the worst 10% of relays delivered at **21–42% of their idle speed** (a 2 MB block that takes ~0.5 s from an idle node takes several seconds from a saturated one).

The question I most wanted answered: **where in a block's propagation does this congestion fall** — the early hops that decide whether a block beats a competitor, or the late tail that barely matters? Bucketing each contended relay by how much of the network already had the block at that moment:

| Propagation phase | Share of relays contended | Worst-10% throughput ratio |
|---|---|---|
| **Early** (<25% of nodes have it) | **24.3%** | 0.36 |
| Mid (25–75%) | 9.7% | 0.71 |
| Late (>75%) | 14% | 0.59 |

**82% of all severely-contended relays fell in the early phase** — the critical path. So the congestion is not an irrelevant tail effect; it concentrates exactly where it raises orphan risk. This is the strongest evidence I have that the mechanism priority fill targets is real on mainnet, under the conditions (large blocks) the proposal is scoped to.

## Why it happens: TCP, not raw bandwidth

The long-form measurements (≈37k download probes) show a single connection is limited by its congestion window over the round trip, not by the node's link: after slow-start, one connection delivers ~350 Mb/s at 20 ms RTT, ~120 Mb/s at 100 ms, ~75 Mb/s at 200 ms, and a 2 MB block takes ~7 round trips to arrive. Only **~15% of reachable nodes are genuinely uplink-limited** (median capacity ~39 Mb/s); the rest are fast. So contention arises when a slower-uplink node has to push a large block to several peers at once — its parallel uploads add up past its link, and today every peer's copy slows down together.

## Recalibrated model: priority fill helps for large blocks, not small

Feeding the measured capacities, RTT/window behaviour and Zebra/Zakura mix back into the 200-node model and rerunning Zebra-today vs priority fill (stale rate):

| Block size | Interval | Today | Priority fill | Δ |
|---|---|---|---|---|
| 12 kB (today's norm) | 25 s | 3.9% | 4.4% | **+0.4%** |
| 2 MB (full) | 75 s | 3.8% | 3.4% | −0.4% |
| 2 MB (full) | 25 s | 11.0% | 9.8% | **−1.2%** |
| 2 MB, slower network | 25 s | 12.3% | 9.7% | **−2.6%** |

Read honestly: for today's tiny blocks priority fill is **marginally negative** (its admission staging adds a little per-hop latency with no contention to fix); its benefit is confined to large-block periods, and grows at 25 s spacing and on slower networks. This suggests a concrete design rule — **priority fill should engage only above a block-size threshold**, serving small blocks immediately as today and prioritising the uplink only when there's actually contention to manage.

## Making it at least as safe as today's parallel uploads

Today's relay shares a sender's upload equally across all requesting peers. A nice property of that is that it has **no notion of peer quality to game** — it is maximally DoS-neutral, at the cost of making everyone wait when an uplink is full. Priority fill, by ranking peers, introduces an attack surface that today's design simply doesn't have. If priority fill can't be made no-less-safe than that baseline, it shouldn't ship.

I spent a good while red-teaming exactly this, in a 25-scenario adversarial model (slow-readers, black-holes that fetch but never relay, announce-then-withhold, Sybil clusters, attackers targeting miners and high-degree hubs, up to a third of the network malicious). Findings:

- **On stale rate — the security-relevant metric — priority fill beats today's relay in every one of the 25 scenarios**, typically by roughly half.
- Three changes were needed to get there: **reciprocity ranking** (favour peers that have actually delivered blocks to you, so a black-hole/withholder earns no standing), a **prompt stall-watchdog** (catch a slow-reader every block and drop a transfer that overruns the request timeout), and **faster back-fill of idle uplink** (so one slow reader can't briefly monopolise a slot).
- The only residual is honest-node **tail latency (p90)** under an extreme slow-reader flood (≈33% malicious, or 15% hub-targeted); after the fixes it's within run-to-run noise and flips sign across random seeds. I'd want this specific case re-checked on the Zebra-code testbed before trusting it.

I think "no worse than today's parallel model, and provably so" is the right bar, and the work so far says it's reachable — but it needs validation on real code, not just a model.

## Where I'd take the research next

1. **Size-gated triggering.** Make priority fill a no-op below a block-size threshold so it never costs latency in the common (empty-block) case. Measure the threshold that keeps the large-block benefit without the small-block penalty.
2. **Validate on the testbed with real TCP.** The model and the mainnet monitor agree, but both are indirect. Replay the large-block, early-hop contention on the Zebra-networking testbed (real sockets, emulated RTTs) and confirm the stale-rate benefit and the safety residual there.
3. **Controlled large-block experiments.** Full blocks only occur in bursts today. A coordinated fill (announced in advance, at a quiet time) with the monitors watching would give clean, repeatable measurements instead of relying on whoever is spamming.
4. **Reach the nodes we can't see.** Stand up an inbound-reachable monitor so NAT'd home nodes connect to us; they're likely slower and currently under-counted, which if anything understates the contention.
5. **Confirm and model the Zakura change.** The post-NU7 propagation jump is largely Zakura's doing. Worth understanding exactly what changed, and folding Zakura's all-peers announcement behaviour (vs Zebra's third) into the model properly.
6. **Harden and prove the safety bound.** Close the flooding p90 residual on the testbed, and aim for an argument that a ranked scheme cannot be gamed to do worse than today's parallel sharing, not just that it wasn't in 25 scenarios.

## Summary

- NU7 went well; 25 s blocks propagate faster than 52 s blocks did, mostly thanks to a Zakura relay improvement. No orphan problem today — because blocks are empty, exactly as the proposal said.
- On full 2 MB blocks, ~20% of relays are genuinely upload-contended, and **82% of the bad cases hit the early, critical hops** — real evidence for the mechanism priority fill addresses.
- A measurement-calibrated model says priority fill is neutral-to-slightly-negative for tiny blocks and helpful for large ones, which argues for size-gated triggering.
- Adversarially, priority fill can be made to beat today's relay on stale rate across 25 attack scenarios with a small, still-to-be-confirmed tail-latency residual — i.e. plausibly as safe as today's parallel uploads, pending testbed validation.

Happy to share the raw data, the monitor, the model and the adversarial harness with anyone who wants to poke holes. Corrections very welcome — especially from Zebra and Zakura devs on the relay internals.
