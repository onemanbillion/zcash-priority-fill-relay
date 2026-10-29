# How Zakura broadcasts blocks

Research notes for the priority-fill proposal. Status: findings from reading the source; nothing here has been run or measured.

- Zakura: <https://github.com/zakura-core/zakura>, read at commit `e5fa63e` (28 October 2026). Line references below are to that commit.
- Zebra comparison: `main` at commit `1e03ee75` (23 October 2026), the version the paper's testbed is built on.

## What Zakura is

Zakura is a Zcash full node forked from Zebra. It was released in July 2026 by Project Tachyon and Valar Group, and it supports the Ironwood upgrade. It is built for scale: faster sync, pruning, snapshots and a zcashd-compatible RPC mode. Gemini has moved its Zcash infrastructure to it, so it is a real part of the network, and the network now runs two node implementations rather than one.

It has two P2P stacks:

1. **Legacy**: the Zebra-derived inv/getdata protocol. This is the Mainnet default (`crates/zakura-network/src/config.rs:131-141`: "Mainnet defaults to `P2pStack::Legacy` until Zakura P2P v2 is proven there").
2. **Zakura P2P v2**: a new QUIC transport. It is on by default on other networks ("Dual") and off on Mainnet. Dogwood, its planned block-propagation protocol, exists only as a design document and spec.

## 1. Legacy block relay: what Zakura changed from Zebra

| | Zebra (1e03ee75) | Zakura (e5fa63e) |
| --- | --- | --- |
| Wait between tip announcements | `PEER_GOSSIP_DELAY` = 7 s (mined blocks skip it) | None |
| Who gets a relayed block's `inv` | A random third of ready peers | Every peer, paced by upload slots |
| Who gets a mined block's `inv` | Every peer | Every peer, lowest round-trip time first, with every 4th slot going to a random peer |
| Limit on concurrent new-block uploads | None (TCP shares the link) | 32 slots across all broadcasts; each slot is held until that peer's upload finishes |
| Serving a block request | Each connection serves its own getdata in parallel | Same |
| Early mined-block inventory | No | Yes: advertised and served before commit, cancelled if the block fails |

### No announcement delay

`crates/zakurad/src/components/sync/gossip.rs:141-142`:

> Block gossip has no delay between successive blocks: every relay hop that waits adds its delay to the block's propagation time.

`PEER_GOSSIP_DELAY` does not exist in Zakura. This is the change the paper's section 6.1 suggests for Zebra. In the 1,000-node model, removing the delay cut orphans from 16.2% to 13.4% with today's relay and from 6.0% to 3.9% with priority fill.

### Announce to everyone, in waves of 32

- `crates/zakura-network/src/peer_set/set.rs:1343-1382`, `route_block_broadcast`. Relayed and mined blocks are both advertised to every gossip peer at or above the minimum version, through `buffer_unordered(BLOCK_GOSSIP_CONCURRENCY)` and a shared semaphore.
- `crates/zakura-network/src/peer/block_gossip.rs:25`: `BLOCK_GOSSIP_CONCURRENCY: usize = 32`, documented as the "maximum outstanding legacy block advertisements across broadcasts".
- `BlockGossipPeer::advertise` (`block_gossip.rs:178-257`) acquires a slot before sending the `inv` and keeps it:
  - until the peer's block upload has been written, plus `BLOCK_WRITE_GRACE` (750 ms) for the kernel send queue to drain;
  - for up to `BLOCK_REQUEST_WAIT` (3 s) if the peer never sends a getdata ("Peers that already have a block might never request it");
  - for up to `BLOCK_UPLOAD_WAIT` (40 s) once the peer has requested the block.
- `PEER_FRACTION_TO_BROADCAST = 3` is now used only for transaction inventory.

### Order of announcements

`block_gossip.rs:264-296`, `order_peers`:

- Configured zcashd sidecars come first.
- **Relayed blocks:** random order.
- **Mined blocks:** ascending round-trip time, except every 4th position goes to a random remaining peer (`MINED_RANDOM_INTERVAL = 4`), because "peers with the lowest RTT could otherwise hold every slot without completing uploads".

### Serving block requests is unchanged

- Each connection still serves its own getdata in parallel with the others (`crates/zakura-network/src/peer/connection.rs:1325-1403`). Blocks in one response are written one after another.
- There is no rate limiting or ordering of block bytes. With up to 32 slots in use, up to 32 uploads share the node's link through TCP.
- The connection now reports upload progress (`advertised`, `requested`, `written`, `unavailable`, `request_finished`), which feeds the slot logic.
- Peer-message regulation (`docs/design/peer-message-regulation.md`) covers the v2 streams only. It explicitly leaves "prioritization, peer-slot policy" as "separate work" (line 366).

### Reacting to an announcement

This is the same as Zebra:

- One download per block (`crates/zakurad/src/components/inbound/downloads.rs:538-549`).
- The request is routed among the advertising peers.
- Requests time out after 20 s (`REQUEST_TIMEOUT`).

Two differences:

- Advertisements from native Zakura v2 peers are ignored on this path ("native block sync owns block bodies", `crates/zakurad/src/components/inbound.rs:848-855`).
- A Zakura source may have 5 downloads in flight.

### First-received mining

`docs/design/first-received-mining.md`: among equal-work tips, a Zakura miner builds on the block whose full body reached its verifier first. Receipt is recorded before verification. So when two blocks compete, the order in which miners receive the full block decides the fork, which is exactly what upload order controls.

## 2. Zakura P2P v2 and Dogwood

- **Today's v2 code path:**
  - A block hash is sent to every v2 session except the source (`crates/zakura-network/src/zakura/legacy_gossip.rs:1621-1640`).
  - The body is pulled whole with `BlocksByHash`, asking "the preferred peer first, then the others in random order".
  - On a Dual node, announcements fan out on both stacks.
- **Transport:** QUIC (`crates/zakura-quic`), Cubic congestion control by default, `send_fairness` on. Stream priorities exist in the QUIC layer (`stream.rs:143-148`), but no network code sets them.
- **Dogwood is design only.** No code under `crates/` mentions it.
  - **How it spreads a block** (`docs/design/dogwood.md`, `docs/specs/dogwood.md`, "protocol draft, second revision"):
    - It splits a block into 64 KiB erasure-coded parts (k ≤ 64 data parts per stripe plus ⌈k/3⌉ parity).
    - The proposer seeds parts through nearby entry peers, one part per peer in turn.
    - Each node forwards parts cut-through after checking proof of work and the part's Merkle proof, before full validation.
    - Receivers pull announced parts first. They then ask consistently fast neighbours to push, ranked by an EWMA of arrival lag.
  - **Target:** 90% of nodes within 500 ms, aiming for 400 ms, at a design load of 50,000 TPS.
  - **Results from an 80-node fleet:**
    - 32 MiB blocks reached 90% of nodes in 0.40 s.
    - At 256 MiB, learned push was slower than pull-only, at 2.16 s against 1.59 s, because "queueing dominated learned push as the busiest relay uploaded about four times the body".
  - **Sender side:** "A connection's data stream is one FIFO shared by all blocks. The sender SHOULD write parts in the order it queued them" (`docs/specs/dogwood.md:972-973`). A `CHILD_BUDGET` caps how many push subscriptions a node accepts; its value is still TBD.

## What this means for priority fill

1. **The network is now mixed.** The paper describes Zebra as the only full node. Anything on Mainnet relay needs to cover both Zebra and Zakura.
2. **Zakura already fixed the announcement delay.** This supports the paper's incidental finding and makes it a concrete, already-shipped change rather than a suggestion. Zebra at 1e03ee75 still waits 7 s.
3. **Zakura already controls who gets a block first, but not by relay value and not on the upload itself.** The 32-slot cap limits how many peers download at once. The `order_peers` order decides who goes first: random for relayed blocks, lowest round-trip time for mined ones. That differs from priority fill in four ways:
   - **Ranking:** priority fill ranks by measured throughput, a proxy for how fast a peer will relay onward; Zakura uses round-trip time or random order.
   - **Concurrency:** priority fill admits another transfer only when upload has spare capacity (under 85% for 100 ms). Zakura allows a fixed 32, and up to 32 uploads still split the link evenly.
   - **Where it acts:** priority fill acts on block requests that have already arrived, including from peers that heard the `inv` elsewhere. Zakura's slots pace its own announcements.
   - **Stalled peers:** Zakura releases a slot after 3 s with no request, or after the write plus 750 ms. Priority fill gives up a stalled upload's slot and demotes the peer.
4. **Zakura's slot mechanism is a natural place to try priority fill.** `order_peers` could rank relayed peers by measured upload throughput, and the slot count could adapt to upload utilisation instead of being fixed at 32. Zakura already tracks per-connection upload progress, which is the signal demotion needs.
5. **A possible cost in Zakura's design, worth modelling.** A slot held for up to 3 s by a peer that already has the block delays every peer queued behind it. With 25 s blocks, 3 s is 12% of an interval. Late in propagation most peers already have the block, so this could matter when a node has more than 32 peers. The code comment suggests the authors chose the timeout deliberately; the effect hasn't been measured here.
6. **First-received mining makes upload order matter even more on Zakura.** Ties go to whichever full block a miner received first.
7. **Dogwood moves the "who goes first" choice to receivers.** Priority fill could still apply at a sender's FIFO, for example by writing parts first to children that forward fastest, and the 256 MiB result suggests sender queueing is the bottleneck at large block sizes. Dogwood is a draft for much larger blocks than today's 2 MB, so this is further off.

## Suggested next steps

- Add a Zakura mode to the 1,000-node model:
  - no announcement delay;
  - all-peer announcements;
  - a 32-slot cap with the 750 ms grace and the 3 s no-request hold;
  - random order for relayed blocks and round-trip-time order for mined ones.
- Run a mixed network, for example with Zakura on hosted nodes and Zebra elsewhere.
- Compare four combinations: Zakura's slots alone, priority fill alone, priority fill inside Zakura's slots, and both with throughput ranking.
- Update the paper's background to describe both implementations and credit Zakura's removal of the announcement delay.

## Sources

- Zakura repository: <https://github.com/zakura-core/zakura> (commit `e5fa63e`)
- Zakura on docs.rs: <https://docs.rs/crate/zakura/1.3.0>
- Gemini, "Gemini preps for faster Zcash with move to Zakura": <https://www.gemini.com/blog/gemini-preps-for-faster-zcash-with-move-to-zakura>
- KuCoin, "Zcash new full node client Zakura launched": <https://www.kucoin.com/news/flash/zcash-new-full-node-client-zakura-launched-supports-ironwood-network-upgrade>
