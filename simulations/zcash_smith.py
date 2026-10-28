"""Smith's-rule ranking (peer count x receive speed) vs measured-throughput ranking
vs Zebra today, on a topology where peer counts vary realistically.

Topology: every node opens 8 outbound connections to random *reachable* nodes.
Reachability (accepts inbound): datacenter 100%, fiber 50%, cable 20%, poor 5%.
Inbound caps: datacenter 125, others 40. So hosted nodes end up with many
peers and NATed home nodes with ~8.

Rankings (lower key = served first; all use priority fill, inv to all peers):
  measured        : -(observed throughput from peer), +-50% noise   [previous winner]
  smith_degree    : -(k_j - 1) * min(U, D_j)                         [true k, D]
  smith_capped    : -min(k_j - 1, u_j*T/B) * min(U, D_j), T = 2 s    [true k, u, D]
  smith_waiting   : like smith_capped but counts only j's peers that don't
                    have the block yet, re-evaluated at every scheduling step
  smith_estimated : smith_capped with every input estimated with +-50% noise
                    (k inferred, u and D from measured throughput)
"""
import math, random, statistics as st
src = open("zcash_compare.py").read().split("if __name__")[0]
src = src.replace("(lambda k, u=u: rank[u][k])",
                  "(lambda k, u=u: rank(u, k, have) if callable(rank) else rank[u][k])")
exec(src)

REACH = {"datacenter": 1.0, "fiber": .5, "cable": .2, "poor": .05}
INCAP = {"datacenter": 125, "fiber": 40, "cable": 40, "poor": 40}

def make_net2(N=1000, out=8, seed=1):
    up, down, cls, _, _ = make_net(N, out=1, seed=seed)  # reuse bandwidth draw
    rng = random.Random(seed + 1)
    reachable = [i for i in range(N) if rng.random() < REACH[cls[i]]]
    adj = [set() for _ in range(N)]; inbound = [0] * N
    for u in range(N):
        tries = 0
        while sum(1 for v in adj[u]) < out and tries < 5000:
            tries += 1
            v = rng.choice(reachable)
            if v == u or v in adj[u] or inbound[v] >= INCAP[cls[v]]:
                continue
            adj[u].add(v); adj[v].add(u); inbound[v] += 1
    lat = {}
    for u in range(N):
        for v in adj[u]:
            if (u, v) not in lat:
                lat[(u, v)] = lat[(v, u)] = rng.uniform(.02, .15)
    return up, down, cls, [sorted(a) for a in adj], lat

def build_ranks(net, bits, T=2.0, seed=7):
    up, down, cls, adj, lat = net
    N = len(adj); rng = random.Random(seed)
    k = [len(a) for a in adj]
    noise = lambda: math.exp(rng.gauss(0, .5))
    R = {}
    R["measured"] = [{v: -min(up[v], down[u]) * noise() for v in adj[u]} for u in range(N)]
    R["smith_degree"] = [{v: -(k[v] - 1) * min(up[u], down[v]) for v in adj[u]} for u in range(N)]
    cap_w = lambda kv, uv: min(kv - 1, uv * T / bits)
    R["smith_capped"] = [{v: -cap_w(k[v], up[v]) * min(up[u], down[v]) for v in adj[u]}
                         for u in range(N)]
    est = []
    for u in range(N):
        d = {}
        for v in adj[u]:
            k_e = max(2.0, k[v] * noise())
            u_e = min(up[v], down[u]) * noise()      # what u can observe
            d_e = down[v] * noise()
            d[v] = -cap_w(k_e, u_e) * min(up[u], d_e)
        est.append(d)
    R["smith_estimated"] = est
    def waiting(u, v, have):
        lacking = sum(1 for x in adj[v] if have[x] == math.inf and x != u)
        return -min(lacking, up[v] * T / bits) * min(up[u], down[v])
    R["smith_waiting"] = waiting
    return R

if __name__ == "__main__":
    net = make_net2()
    up, down, cls, adj, lat = net
    N = len(adj)
    print(f"nodes={N}")
    for c, *_ in CLASSES:
        ks = [len(adj[i]) for i in range(N) if cls[i] == c]
        print(f"  {c:<11}{len(ks):>4} nodes  peers: median {st.median(ks):>4.0f}  max {max(ks):>4}")
    dcs = [i for i in range(N) if cls[i] == "datacenter"]
    srcs = random.Random(99).sample(dcs, 10)
    strats = ["zebra_today", "measured", "smith_degree", "smith_capped",
              "smith_waiting", "smith_estimated"]
    print("\np90 seconds (p50 underneath), mean over 10 miners")
    print(f"{'block':<8}" + "".join(f"{s:>16}" for s in strats))
    for label, mb in [("20 KB", .16), ("250 KB", 2.), ("1 MB", 8.), ("2 MB", 16.)]:
        R = build_ranks(net, mb)
        p50s, p90s = [], []
        for s in strats:
            mode = "zebra_today" if s == "zebra_today" else "sat_oracle"  # sat_* = fill, inv all
            res = [simulate(net, mode, mb, sc, rank=R.get(s), rng=random.Random(i))
                   for i, sc in enumerate(srcs)]
            p50s.append(st.mean(x[0] for x in res)); p90s.append(st.mean(x[1] for x in res))
        print(f"{label:<8}" + "".join(f"{x:>15.2f}s" for x in p90s))
        print(f"{'':<8}" + "".join(f"{x:>15.2f}s" for x in p50s))
