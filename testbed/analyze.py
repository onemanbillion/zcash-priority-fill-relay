#!/usr/bin/env python3
"""Per-block propagation stats from testbed logs. Times are divided by the run's dilation."""
import glob, json, math, statistics as st, sys, collections

def load(run):
    meta = json.load(open(f"{run}/meta.json"))
    D = meta["dilation"]
    mined, recv, fails = {}, collections.defaultdict(dict), collections.Counter()
    valid = collections.defaultdict(dict)
    serve_waits = []
    lags = []
    for path in glob.glob(f"{run}/n*.log"):
        node = int(path.split("/n")[-1].split(".")[0])
        for line in open(path):
            f = line.split()
            if len(f) < 2:
                continue
            t = int(f[0]) / 1e6
            if f[1] == "MINED":
                mined[f[2]] = (t, node)
            elif f[1] == "RECV":
                recv[f[2]][node] = t
            elif f[1] == "VALID":
                valid[f[2]][node] = t
            elif f[1] == "DLFAIL":
                fails[f[3] if len(f) > 3 else "?"] += 1
            elif f[1] == "LAG":
                lags.append((t, int(f[2])))
            elif f[1] == "SERVE_START" and len(f) > 3:
                serve_waits.append(float(f[3]) / 1000)
    return meta, D, mined, recv, valid, fails, serve_waits, lags

def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]

def stats(run, skip=2, T=25.0):
    meta, D, mined, recv, valid, fails, waits, lags = load(run)
    n = len(meta["nodes"])
    order = sorted(mined, key=lambda h: mined[h][0])[skip:]
    rows = []
    for h in order:
        t0, miner = mined[h]
        attackers = {x["id"] for x in meta["nodes"] if x["cls"] == "attacker"}
        n = len(meta["nodes"]) - len(attackers)
        d = [(t - t0) / D for node, t in recv[h].items() if node != miner and node not in attackers]
        if not d:
            continue
        cover = (len(d) + 1) / n
        # all nodes, a node that never got the block counts as infinitely late
        full = d + [float("inf")] * (n - 1 - len(d))
        # stale-rate estimate: chance another (equal-hashrate) miner finds a competing block
        # before it has received and validated this one, at block interval T
        miners = [x["id"] for x in meta["nodes"] if x["cls"] == "datacenter" and x["id"] != miner]
        tv = [((valid[h][j] - t0) / D) if j in valid[h] else float("inf") for j in miners]
        stale = st.mean(1 - math.exp(-x / T) if x != float("inf") else 1.0 for x in tv)
        miner_p90 = pct(tv, .9)
        rows.append(dict(p50=pct(full, .5), p90=pct(full, .9), max=max(d), cover=cover,
                         stale=stale, miner_p50=pct(tv, .5), miner_p90=miner_p90))
    if not rows:
        return None
    first = mined[order[0]][0] if order else 0
    lv = sorted(l for t, l in lags if t >= first)
    agg_lag = dict(lag_p99_ms=lv[int(.99 * (len(lv) - 1))] if lv else None, lag_max_ms=lv[-1] if lv else None)
    agg = {k: st.mean(r[k] for r in rows) for k in ("p50", "p90", "max", "cover", "stale", "miner_p50", "miner_p90")}
    agg["rows"] = rows
    agg["blocks"] = len(rows)
    agg.update(agg_lag)
    agg["fails"] = dict(fails)
    agg["mode"] = meta["mode"]
    agg["topo"] = meta["topo_seed"]
    try:
        agg.update(json.load(open(f"{run}/run.json")))
    except FileNotFoundError:
        pass
    return agg

if __name__ == "__main__":
    for run in sys.argv[1:]:
        s = stats(run)
        print(run, json.dumps(s, default=str) if s else "no data")
