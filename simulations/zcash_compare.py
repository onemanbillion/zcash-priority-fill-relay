"""Compare Zebra's current block relay against bandwidth-aware 'saturate' relay
using realistic, imperfect estimates of peer upload speed.

Discrete-event simulation. Per hop:
  sender validates (50 ms) -> inv to chosen peers -> each receiver requests the
  block from the FIRST peer whose inv reaches it (one in-flight request, like
  Zebra/Bitcoin) -> sender uploads -> receiver has block.

Sender upload scheduling is a fluid model, recomputed whenever a request
arrives or a transfer completes:
  fair      : max-min fair share of upload across all requesters (TCP-ish),
              each stream capped by the receiver's download   [Zebra today]
  fill:<k>  : priority fill - requesters sorted by a ranking key; each gets its
              full download rate until the sender's upload is used up; the
              next one gets the leftover. No stream slowed for a lower one.

Strategies (advertise rule + scheduler + ranking):
  zebra_today     inv to ceil(1/3) random peers (all if self-mined), fair
  inv_all_fair    inv to all peers, fair
  sat_learned     inv to all, fill ranked by who announced past blocks first
  sat_measured    inv to all, fill ranked by measured throughput (+-50% noise,
                  capped by own download - what you'd actually observe)
  sat_oracle      inv to all, fill ranked by true upload (upper bound)
"""
import heapq, math, random, statistics as st

CLASSES = [("datacenter", .30, 500, 500), ("fiber", .25, 100, 500),
           ("cable", .35, 15, 150), ("poor", .10, 3, 25)]

def make_net(N=1000, out=12, seed=1):
    rng = random.Random(seed)
    up, down, cls = [], [], []
    for _ in range(N):
        r, acc = rng.random(), 0
        for name, sh, u, d in CLASSES:
            acc += sh
            if r <= acc: break
        up.append(u * math.exp(rng.gauss(0, .35)))
        down.append(d * math.exp(rng.gauss(0, .35)))
        cls.append(name)
    adj = [set() for _ in range(N)]
    for u in range(N):
        while len(adj[u]) < out:
            v = rng.randrange(N)
            if v != u: adj[u].add(v); adj[v].add(u)
    lat = {}
    for u in range(N):
        for v in adj[u]:
            if (u, v) not in lat:
                lat[(u, v)] = lat[(v, u)] = rng.uniform(.02, .15)
    return up, down, cls, [sorted(a) for a in adj], lat

class Sender:
    """Fluid upload scheduler for one node."""
    def __init__(s, U):
        s.U, s.active, s.rates, s.t, s.ver = U, {}, {}, 0.0, 0
    def advance(s, t):
        dt = t - s.t
        fin = []
        if dt > 0:
            for k, r in s.rates.items():
                s.active[k][0] -= r * dt
        for k in list(s.active):
            if s.active[k][0] <= 1e-6:
                fin.append(k); del s.active[k]
        s.t = t
        return fin
    def recompute(s, sched, key):
        ks = list(s.active)
        rates = {}
        if sched == "fair":
            items = sorted(ks, key=lambda k: s.active[k][1])
            rem = s.U
            for i, k in enumerate(items):
                r = min(s.active[k][1], rem / (len(items) - i)); rates[k] = r; rem -= r
        else:
            rem = s.U
            for k in sorted(ks, key=key):
                r = min(s.active[k][1], rem); rates[k] = r; rem -= r
        s.rates = {k: r for k, r in rates.items() if r > 1e-12}
        s.ver += 1
        if not s.rates: return math.inf
        return s.t + min(s.active[k][0] / r for k, r in s.rates.items())

def simulate(net, strat, bits, src, rank=None, rng=None, record=None, val=.05):
    up, down, cls, adj, lat = net
    N = len(adj)
    rng = rng or random.Random(0)
    adv_all = strat != "zebra_today"
    sched = "fair" if strat in ("zebra_today", "inv_all_fair") else "fill"
    have = [math.inf] * N; requested = [False] * N
    senders = {}
    ev = [(0.0, 0, "recv", src, -1)]; seq = 1
    def push(t, kind, a, b):
        nonlocal seq; heapq.heappush(ev, (t, seq, kind, a, b)); seq += 1
    while ev:
        t, _, kind, a, b = heapq.heappop(ev)
        if kind == "recv":
            if have[a] <= t: continue
            have[a] = t; push(t + val, "valid", a, 0)
        elif kind == "valid":
            u = a; peers = adj[u][:]
            if not adv_all and u != src:
                rng.shuffle(peers); peers = peers[:math.ceil(len(peers) / 3)]
            for v in peers:
                push(t + lat[(u, v)], "inv", v, u)
        elif kind == "inv":
            v, u = a, b
            if record is not None: record.append((v, u, t))
            if have[v] < math.inf or requested[v]: continue
            requested[v] = True
            push(t + lat[(u, v)], "getdata", u, v)
        elif kind == "getdata":
            u, v = a, b
            S = senders.setdefault(u, Sender(up[u]))
            for k in S.advance(t): push(t + lat[(u, k)], "recv", k, 0)
            S.active[v] = [bits, down[v]]
            key = (lambda k, u=u: rank[u][k]) if rank else None
            tn = S.recompute(sched, key)
            if tn < math.inf: push(tn, "done", u, S.ver)
        elif kind == "done":
            u = a; S = senders[u]
            if b != S.ver: continue
            for k in S.advance(t): push(t + lat[(u, k)], "recv", k, 0)
            key = (lambda k, u=u: rank[u][k]) if rank else None
            tn = S.recompute(sched, key)
            if tn < math.inf: push(tn, "done", u, S.ver)
    r = sorted(have)
    return r[len(r) // 2], r[int(len(r) * .9)]

def rankings(net, seed=7, warm=12, warm_bits=8.0):
    up, down, cls, adj, lat = net
    N = len(adj); rng = random.Random(seed)
    # oracle: true upload, high first
    oracle = [{v: -up[v] for v in adj[u]} for u in range(N)]
    # measured: what u observes of v's sends: min(v up, u down) with +-50% noise
    measured = [{v: -min(up[v], down[u]) * math.exp(rng.gauss(0, .5)) for v in adj[u]}
                for u in range(N)]
    # learned: run warm-up blocks under Zebra today; score each peer by how late
    # its inv arrived relative to the first inv (never announced = 2 s penalty)
    score = [{v: 0.0 for v in adj[u]} for u in range(N)]
    dcs = [i for i in range(N) if cls[i] == "datacenter"]
    for w in range(warm):
        rec = []
        simulate(net, "zebra_today", warm_bits, rng.choice(dcs),
                 rng=random.Random(1000 + w), record=rec)
        first, seen = {}, {}
        for v, u, t in rec:
            first[v] = min(first.get(v, math.inf), t)
            d = seen.setdefault(v, {})
            d[u] = min(d.get(u, math.inf), t)
        for v in range(N):
            for u in adj[v]:
                tt = seen.get(v, {}).get(u)
                score[v][u] += (tt - first[v]) if tt is not None else 2.0
    learned = score  # lower = announced earlier on average
    return {"sat_oracle": oracle, "sat_measured": measured, "sat_learned": learned}

if __name__ == "__main__":
    net = make_net()
    up, down, cls, adj, lat = net
    N = len(adj)
    print(f"nodes={N}  avg peers={sum(map(len, adj))/N:.1f}")
    R = rankings(net)
    # how good are the estimates? Spearman-ish: fraction of peer pairs ordered correctly
    def pair_acc(rk):
        good = tot = 0
        for u in range(N):
            ps = adj[u]
            for i in range(len(ps)):
                for j in range(i + 1, len(ps)):
                    a, b = ps[i], ps[j]
                    if up[a] == up[b]: continue
                    tot += 1
                    good += (rk[u][a] < rk[u][b]) == (up[a] > up[b])
        return good / tot
    for k in ("sat_measured", "sat_learned"):
        print(f"  {k}: orders peer pairs by true upload correctly {pair_acc(R[k])*100:.0f}% of the time")
    print()
    strats = ["zebra_today", "inv_all_fair", "sat_learned", "sat_measured", "sat_oracle"]
    dcs = [i for i in range(N) if cls[i] == "datacenter"]
    srcs = random.Random(99).sample(dcs, 10)
    print(f"{'block':<8}" + "".join(f"{s:>15}" for s in strats) + "   (p90 seconds; p50 below)")
    for label, mb in [("20 KB", .16), ("250 KB", 2.), ("1 MB", 8.), ("2 MB", 16.)]:
        p50s, p90s = [], []
        for s in strats:
            res = [simulate(net, s, mb, src, rank=R.get(s), rng=random.Random(i))
                   for i, src in enumerate(srcs)]
            p50s.append(st.mean(x[0] for x in res)); p90s.append(st.mean(x[1] for x in res))
        print(f"{label:<8}" + "".join(f"{x:>14.2f}s" for x in p90s))
        print(f"{'':<8}" + "".join(f"{x:>14.2f}s" for x in p50s))
