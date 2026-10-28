# Results

`summary.txt` / `summary.json` aggregate the main matrix (`runs/m_*`): per scenario and mode, the mean over measured blocks with a 95% bootstrap CI. These are the numbers in the paper.

Run names: `m_<profile>_t<topology seed>_<mode>_a<attackers>`.

| Mode | Meaning |
| --- | --- |
| `zebra` | Current Zebra behaviour: fair sharing, one-third announcement fanout |
| `prio` | Priority fill, freshly started (no throughput estimates), announce to all peers |
| `prio_third` | Priority fill, freshly started, one-third fanout |
| `prio_warm` | Priority fill, steady state (each node seeded with its own ±50%-noisy view of every peer) |

`runs/f_*` are confirmation runs made after the code-review fixes (patch 0002–0003): steady state 3.1% stale on topology 1 (same as before the fixes) and 4.2% with ten attackers.

Each run directory has `meta.json` (configuration and node rates), `run.json` (per-block receive times), `schedule.txt` (mining schedule) and `logs.tar.gz` (every node's log). To recompute: extract the logs in place and run `python3 ../testbed/summarize.py runs` from this directory.
