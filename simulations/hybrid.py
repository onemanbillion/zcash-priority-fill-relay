import math, statistics as st, sys
sys.argv=['x']
src = open('zcash_hetero.py').read().split('if __name__')[0]
exec(src)

def limited(reqs, U, up, c):
    """At most c concurrent streams, max-min fair share, best relayer admitted first."""
    pending = sorted(reqs); i = 0; t = pending[0][0]
    waiting, active, out = [], {}, {}
    while i < len(pending) or waiting or active:
        while i < len(pending) and pending[i][0] <= t + 1e-12:
            waiting.append(pending[i]); i += 1
        waiting.sort(key=lambda r: -up[r[3]])
        while waiting and len(active) < c:
            _, b, cap, k = waiting.pop(0); active[k] = [b, cap]
        if not active:
            t = pending[i][0]; continue
        items = sorted(active.items(), key=lambda kv: kv[1][1])
        rem, n, rates = U, len(items), {}
        for idx, (k, (b, cap)) in enumerate(items):
            r = min(cap, rem/(n-idx)); rates[k] = r; rem -= r
        dt = min(min(active[k][0]/rates[k] for k in active),
                 pending[i][0]-t if i < len(pending) else math.inf)
        t += dt
        for k in list(active):
            active[k][0] -= rates[k]*dt
            if active[k][0] <= 1e-9: out[k] = t; del active[k]
    return out

_orig_seq = sequential
def run2(adj, lat, up, down, cls, c, bits, frac):
    global sequential
    sequential = lambda reqs, U, up_, fastest: limited(reqs, U, up_, c)
    try:
        return st.mean(run(adj, lat, up, down, cls, "seq_fastest", bits, frac, seed=s)[1] for s in range(8))
    finally:
        sequential = _orig_seq

N=1000; up,down,cls = make_nodes(N); adj,lat = build(N, out=8)
for frac,fl in [(1.0,"inv to all"),(1/3,"inv to 1/3")]:
    print(f"--- {fl}: p90 s, best-relayer-first with concurrency limit c ---")
    print(f"{'block':<8}{'parallel':>10}" + "".join(f"{'c='+str(c):>8}" for c in [1,2,3,4]))
    for label,mb in [("250 KB",2.0),("1 MB",8.0),("2 MB",16.0)]:
        p = st.mean(run(adj,lat,up,down,cls,"parallel",mb,frac,seed=s)[1] for s in range(8))
        print(f"{label:<8}{p:>9.2f}s" + "".join(f"{run2(adj,lat,up,down,cls,c,mb,frac):>7.2f}s" for c in [1,2,3,4]))
    print()
