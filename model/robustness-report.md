# Adversarial robustness of priority-fill block relay

A resilience evaluation of the priority-fill relay against non-cooperative nodes,
run entirely inside the 200-node propagation model (`sim.js`). Nothing here touches
a real network. For every scenario the identical network, block schedule and
misbehaving nodes are run two ways — Zebra's relay today (`fair`, equal sharing of
a sender's upload) and priority fill (`priority`) — and metrics are computed over
**honest nodes only**. The test for each scenario: is priority fill, under this
behaviour, worse for honest nodes than today's relay under the *same* behaviour?

Harness: `robustness.mjs` (`runScenario`, `SCENARIOS`). Model timestep 10 ms
(identical results to 2 ms, ~5× faster). Metrics: stale rate the honest miners see,
and honest-node propagation p50/p90.

## Threat model

Misbehaving nodes advertise a maximal uplink (500 Mb/s) so the ranking puts them
first, and then do one of: read slowly to hold a sender's slot (`slowread`,
`down=1`), fetch fast but never relay onward (`blackhole`), announce then refuse to
serve (`withhold`), read just above the stall threshold (`dodge`, `down=6`), or
relay honestly to earn trust then defect (`defect`). Amplifiers: extra connections
(`extraConn`, Sybil reach), higher fractions (20 %, 33 %), and targeting (attach
preferentially to miners or the highest-degree honest relays). 25 scenarios in all,
including an independent red-team pass.

## Findings

### Two attacks beat the paper's priority fill

1. **Withhold tail.** Announce-then-refuse made priority fill's p90 *worse* than
   today's relay (10.9 s vs 9.5 s at 60 blocks): honest nodes picked a withholder as
   first announcer and waited out the request timeout.
2. **Slow-read flooding.** At high attacker fractions (33 %), or 15 % when the slow
   readers target high-degree relays, priority fill's honest p90 exceeded today's.
   Mechanism: priority fill serializes the uplink, so a slow reader holds a whole
   slot for its stall window doing almost nothing, momentarily starving honest
   requesters — whereas fair sharing isolates a slow reader to a tiny equal slice.
   Stale rate (the security metric) was **never** worse in any scenario.

### Three changes make it robust

- **Reciprocity ranking** (`reciprocity`, `reciprocityFloor`): a sender favours peers
  that have actually delivered new blocks to it, with time-decayed credit. A
  withholder or black hole never delivers, earns no credit, and sinks to the floor.
  Fixes the withhold tail at ~no honest cost.
- **Prompt stall watchdog** (`sim.js`): time the demotion watchdog off the
  link-implied estimate, not a peer's already-demoted rank cap, so a slow reader is
  caught on every block rather than only the first. Drop any transfer still
  unfinished at the request timeout, freeing the slot. Neutralises plain slow-read.
- **Faster idle back-fill** (`fillIdleS` 0.1 → 0.02): admit another transfer sooner
  when the uplink sits idle, so a slow reader's held slot no longer starves honest
  requesters. Closes the hub-targeted and ≤20 % flooding cases. Improves honest p90
  generally (none: 3.43 → 3.00 s) with no loss of the stale-rate advantage.

A demotion cooldown (`demoteCooldownS`) was also added and tested, but was
ineffective against this attack (the attackers already rank at the floor); left in
as an opt-in knob, default off.

## Results (hardened config: reciprocity 3, floor 0.3, fillIdleS 0.02)

200 nodes, 30 blocks, seeds [1,2]. Stale % / p90 s; lower is better.

| Scenario | Today stale/p90 | Priority stale/p90 | Priority worse? |
|---|---|---|---|
| none (baseline) | 12.4 / 5.1 | 4.3 / 3.0 | no |
| slowread | 11.0 / 4.1 | 4.5 / 3.3 | no |
| blackhole | 12.3 / 5.9 | 4.6 / 3.1 | no |
| withhold | 14.9 / 8.8 | 8.6 / 5.2 | no |
| capture | 12.8 / 5.6 | 4.5 / 3.2 | no |
| dodge / dodge20 / dodge33 | 11.8 / 4.9 | 4.5–5.1 / 3.2–3.3 | no |
| blackhole20 / blackhole33 | 12.1–12.6 / 4.9–6.2 | 4.7–4.9 / 3.1 | no |
| withhold20 | 19.9 / 16.6 | 12.0 / 11.2 | no |
| sybil / sybilbig | 13.1–13.8 / 4.9–5.1 | 4.8–4.9 / 3.3–3.6 | no |
| defect / defectfast | 12.1–12.6 / 5.5 | 4.7–5.0 / 3.2 | no |
| minercapture / minerslow(20) | 10.3–13.7 / 4.5–5.6 | 5.2–5.5 / 3.7–4.9 | no |
| hubcapture | 13.6 / 5.4 | 4.8 / 3.5 | no |
| **flood33** (33 % slow-read) | 8.9 / 3.1 | 4.6 / 3.6 | p90 only |
| **hubslow** (15 % slow-read, hub-targeted) | 10.6 / 4.2 | 4.9 / 4.4 | p90 only |

The two p90 residuals flip sign across seeds (on seeds [3,4] priority fill is
better on both: flood33 3.85 vs 3.94, hubslow 4.66 vs 4.79). Averaged over seeds
[1–4] hubslow is neutral (+0.01 s) and flood33 is +0.19 s — within run-to-run
variation. **On stale rate, priority fill is far better in every one of the 25
scenarios** (typically ~half of today's relay).

## Conclusion

Priority fill, with reciprocity ranking, a prompt stall watchdog, and faster idle
back-fill, is no worse than today's relay on honest tail latency across 25 attack
scenarios (within seed noise in the two most extreme), and strictly better on the
security-relevant stale rate in all of them — including a third of the network
turned malicious, Sybil clusters, and attackers targeting miners and hubs. The
residual is confined to honest p90 under an extreme (33 % malicious, or hub-targeted
15 %) slow-reader flood, where the gap is sub-0.5 s and seed-dependent; the stale
rate stays far better even there. Caveat: this is a numerical model, not a live
network or the Zebra-code testbed; the strongest residual stress to re-check on the
testbed is aggressive slow-reader flooding amplified by hub targeting.
