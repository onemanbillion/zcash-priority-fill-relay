import math, statistics as st
exec(open('zcash_hetero.py').read().split('if __name__')[0])
exec(open('hybrid.py').read().split('_orig_seq')[0].split("exec(src)")[1])  # limited()

def priority_fill(reqs, U, key):
    """Admit streams in priority order; each runs at its full cap (receiver download)
    until the sender's upload is used up; the last admitted stream gets the leftover.
    No stream is ever slowed to make room for a lower-priority one."""
    pending = sorted(reqs); i = 0; t = pending[0][0]
    active, out = {}, {}
    while i < len(pending) or active:
        while i < len(pending) and pending[i][0] <= t + 1e-12:
            _, b, cap, k = pending[i]; active[k] = [b, cap]; i += 1
        if not active:
            t = pending[i][0]; continue
        rem, rates = U, {}
        for k in sorted(active, key=key):
            r = min(active[k][1], rem); rates[k] = r; rem -= r
        live = [k for k in active if rates[k] > 1e-12]
        dt = min(min(active[k][0]/rates[k] for k in live),
                 pending[i][0]-t if i < len(pending) else math.inf)
        t += dt
        for k in live:
            active[k][0] -= rates[k]*dt
            if active[k][0] <= 1e-9: out[k] = t; del active[k]
    return out

N=1000; up,down,cls = make_nodes(N); adj,lat = build(N, out=8)
STRATS = {
  "parallel":      None,
  "best-first c=2":lambda reqs,U,up_: limited(reqs,U,up_,2),
  "fill by down":  lambda reqs,U,up_: priority_fill(reqs,U,key=lambda k:-down[k]),
  "fill by up":    lambda reqs,U,up_: priority_fill(reqs,U,key=lambda k:-up[k]),
}
def p90(strat, mb, frac):
    global sequential
    if strat is None:
        return st.mean(run(adj,lat,up,down,cls,"parallel",mb,frac,seed=s)[1] for s in range(8))
    old = sequential
    sequential = lambda reqs,U,up_,f: strat(reqs,U,up_)
    try: return st.mean(run(adj,lat,up,down,cls,"seq_fastest",mb,frac,seed=s)[1] for s in range(8))
    finally: sequential = old

for frac,fl in [(1.0,"inv to all"),(1/3,"inv to 1/3")]:
    print(f"--- {fl}: p90 seconds ---")
    print(f"{'block':<8}"+"".join(f"{n:>16}" for n in STRATS))
    for label,mb in [("250 KB",2.0),("1 MB",8.0),("2 MB",16.0)]:
        print(f"{label:<8}"+"".join(f"{p90(s,mb,frac):>15.2f}s" for s in STRATS.values()))
    print()
