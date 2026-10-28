#!/usr/bin/env python3
"""Aggregate matrix runs: per scenario and mode, mean over measured blocks with a 95% bootstrap CI."""
import glob, json, random, statistics as st, sys
import analyze

ROOT = sys.argv[1] if len(sys.argv) > 1 else "runs"

def ci(xs, n=2000, seed=1):
    rng = random.Random(seed)
    xs = [x for x in xs if x == x and x != float("inf")]
    if len(xs) < 2:
        return (float("nan"),) * 3
    means = sorted(st.mean(rng.choice(xs) for _ in xs) for _ in range(n))
    return st.mean(xs), means[int(.025 * n)], means[int(.975 * n)]

def main():
    groups = {}
    for run in sorted(glob.glob(f"{ROOT}/m_*")):
        s = analyze.stats(run)
        if not s:
            continue
        meta = json.load(open(f"{run}/meta.json"))
        key = (meta["profile"], meta.get("attackers", 0), meta["mode"])
        g = groups.setdefault(key, {"rows": [], "runs": [], "lag": [], "fails": 0})
        g["rows"] += s["rows"]
        g["runs"].append(run)
        g["lag"].append(s["lag_p99_ms"])
        g["fails"] += sum(s["fails"].values())
    out = []
    for key, g in sorted(groups.items()):
        row = dict(profile=key[0], attackers=key[1], mode=key[2], blocks=len(g["rows"]),
                   runs=len(g["runs"]), lag_p99_ms=max(g["lag"]), dl_failures=g["fails"])
        for m in ("p50", "p90", "miner_p50", "miner_p90", "stale", "cover"):
            mean, lo, hi = ci([r[m] for r in g["rows"]])
            row[m] = round(mean, 3)
            row[m + "_ci"] = (round(lo, 3), round(hi, 3))
        out.append(row)
    json.dump(out, open(f"{ROOT}/summary.json", "w"), indent=1)
    for r in out:
        print(f"{r['profile']:6} att={r['attackers']:<2} {r['mode']:11} blocks={r['blocks']:<3} "
              f"p50={r['p50']:.2f} p90={r['p90']:.2f} minerP50={r['miner_p50']:.2f} "
              f"stale={r['stale']*100:.1f}% {tuple(round(x*100,1) for x in r['stale_ci'])} "
              f"cover={r['cover']:.3f} lag99={r['lag_p99_ms']} fails={r['dl_failures']}")

if __name__ == "__main__":
    main()
