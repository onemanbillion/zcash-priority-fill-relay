#!/usr/bin/env python3
"""Observed forks and short-gap blocks in testbed runs mined on a Poisson schedule.

A fork is counted when the miner of the next block had not yet received and validated the
previous block at the moment it mined: it would have mined a competing block instead.
"""
import json, math, statistics as st, sys
import analyze

def run_stats(run, skip=2, T=25.0, short=7.0):
    meta, D, mined, recv, valid, fails, waits, lags = analyze.load(run)
    order = sorted(mined, key=lambda h: mined[h][0])
    forks = pairs = 0
    short_rows, all_rows = [], []
    s = analyze.stats(run, skip=skip, T=T)
    rows = s["rows"]
    for k in range(skip, len(order)):
        h = order[k]
        t0, miner = mined[h]
        gap = (t0 - mined[order[k - 1]][0]) / D if k else None
        all_rows.append(rows[k - skip]["stale"])
        if gap is not None and gap < short:
            short_rows.append(rows[k - skip]["stale"])
        if k + 1 < len(order):
            t1, m1 = mined[order[k + 1]]
            pairs += 1
            if valid[h].get(m1, float("inf")) > t1 and m1 != miner:
                forks += 1
    lv = s.get("lag_p99_ms")
    return dict(run=run, mode=meta["mode"], blocks=len(all_rows), est_stale=st.mean(all_rows),
                short_gap_blocks=len(short_rows), short_gap_est_stale=st.mean(short_rows) if short_rows else None,
                observed_forks=forks, pairs=pairs, p50=s["p50"], p90=s["p90"], miner_p50=s["miner_p50"], lag_p99_ms=lv)

if __name__ == "__main__":
    out = [run_stats(r) for r in sys.argv[1:]]
    for o in out:
        print(" ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in o.items()))
    json.dump(out, open("runs/poisson_summary.json", "w"), indent=1)
