# Priority-fill block relay for Zcash

> **Status: discussion draft. Not ready for implementation. Do not deploy.**
> This repository accompanies a discussion paper. The code is experimental testbed code that exists to produce the measurements in the paper. It changes peer transport and timeouts, is gated behind an off-by-default feature, and the relay binary refuses to run on non-loopback addresses.

When a Zebra node relays a new block, it answers every peer's request at the same time, so its upload is split evenly and nobody can start relaying onward until near the end. **Priority fill** serves the peers most likely to relay onward first, at their full download speed, and gives any spare upload to the next peer in line. It needs no protocol or consensus change.

In a 100-node testbed built on Zebra's own networking code, with 2 MB blocks every 25 s (ZIP 218), the estimated stale rate fell from 10.0% to 3.6% once nodes had learned their peers' throughput. The gain shrinks to about a quarter for freshly started nodes, the slowest 10% of nodes do not benefit, and slow-reading attackers can delay the network's tail by about 0.8 s. The paper sets out these risks, trade-offs, possible mitigations and the open questions.

**Read the paper:** [`paper/paper.pdf`](paper/paper.pdf) (source: [`paper/paper.md`](paper/paper.md))

**Discussion:** [Zcash Community Forum thread](https://forum.zcashcommunity.com/t/priority-fill-block-relay-fewer-orphans-under-25-s-blocks-no-fork-needed-zecathon-submission/58563) · **Live simulation:** https://web-production-b8358a.up.railway.app

## Contents

| Path | What it is |
| --- | --- |
| `paper/` | The paper (PDF and Markdown) and the script that draws its figures |
| `zebra-patches/` | Four commits against Zebra `main` at 1e03ee75 (`git am`): link emulation, the priority-fill scheduler with demotion of stalled readers, 16 regression tests, and the `zebra-relay` stateless relay binary |
| `testbed/` | `harness_attack.py` launches one 100-node experiment; `run_matrix.sh` reproduces every run in the paper; `analyze.py` / `summarize.py` compute the statistics; `--poisson SEED` mines with Poisson block arrivals and `poisson_analyze.py` counts forks |
| `model/` | The 1,000-node JavaScript model with Poisson block arrivals, overlapping blocks, orphan counting and demotion; `node model/analysis/poisson.mjs` reproduces section 6.1 |
| `simulations/` | The earlier discrete-event models (fair sharing vs sequential vs priority fill, ranking signals, Smith's rule) |
| `results/` | Summary statistics, per-run metadata and every node's log |

## Reproducing the testbed

Needs Linux (the nodes bind to 127.x.y.z loopback addresses), Rust stable, Python 3, and ideally 2+ cores and 8 GB RAM.

```bash
git clone https://github.com/ZcashFoundation/zebra && cd zebra
git checkout 1e03ee75
git am /path/to/this/repo/zebra-patches/*.patch

# regression tests for the scheduler and link emulation
cargo nextest run -p zebra-network --features testbed testbed   # 16 tests

# the relay binary is its own workspace, so the testbed feature never leaks into zebrad
cd zebra-relay && cargo build --release
export ZEBRA_RELAY_BIN=$PWD/target/release/zebra-relay

cd /path/to/this/repo/testbed
python3 harness_attack.py --n 100 --outbound 25 --mode prio_warm --topo-seed 1 --profile mixed \
  --blocks 8 --dilation 4 --stagger 0.02 --warmup 15 --out runs/example
./run_matrix.sh   # full matrix, 13 runs of about 15 minutes each
```

Raise the open-file limit (`ulimit -n 65536`) before running 100 nodes. Run one experiment at a time; concurrent runs on a small machine distort the timings.

## Licence

Dual-licensed under MIT or Apache-2.0, at your option, matching Zebra. The patches in `zebra-patches/` modify Zebra and remain under Zebra's licence terms (copyright Zcash Foundation).

## AI assistance

The analysis, simulations, testbed code and drafting were done with the assistance of an AI model (Claude, by Anthropic). The author is responsible for the content. Any future upstream contribution would follow Zebra's contribution process, starting with an issue discussed with the Zebra team.
