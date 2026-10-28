"""Zcash/Zebra-style pull relay with heterogeneous node bandwidth and link latency.

Node bandwidth classes (upload / download, Mb/s), roughly reflecting a mix of
home and hosted nodes:
  datacenter / VPS    30%  up 500  down 500  (lognormal spread)
  residential fiber   25%  up 100  down 500
  residential cable   35%  up  15  down 150
  poor / rural        10%  up   3  down  25
Each class gets +/-50% lognormal jitter per node. Link one-way latency is
uniform 20-150 ms. Validation 50 ms per hop. Miners are datacenter nodes.

Per hop: inv -> getdata -> block. A sender's upload is shared max-min fairly
across concurrent streams, each capped by the receiver's download.
Modes:
  parallel     : serve every request as it arrives, concurrently (fair share)
  seq_arrival  : one upload at a time, in request-arrival order
  seq_fastest  : one upload at a time, best relayer (highest upload) first
"""
import heapq, random, statistics as st, math

CLASSES = [  # name, share, up, down
    ("datacenter", 0.30, 500, 500),
    ("fiber",      0.25, 100, 500),
    ("cable",      0.35,  15, 150),
    ("poor",       0.10,   3,  25),
]

def make_nodes(N, seed=1):
    rng = random.Random(seed)
    up, down, cls = [], [], []
    for _ in range(N):
        r, acc = rng.random(), 0
        for name, share, u, d in CLASSES:
            acc += share
            if r <= acc:
                break
        j = lambda: math.exp(rng.gauss(0, 0.35))
        up.append(u * j()); down.append(d * j()); cls.append(name)
    return up, down, cls

def build(N, out, seed=1):
    rng = random.Random(seed)
    adj = [set() for _ in range(N)]
    for u in range(N):
        tries = 0
        while len(adj[u]) < out and tries < 1000:
            v = rng.randrange(N); tries += 1
            if v != u:
                adj[u].add(v); adj[v].add(u)
    lat = {}
    for u in range(N):
        for v in adj[u]:
            if (v, u) not in lat:
                lat[(u, v)] = lat[(v, u)] = rng.uniform(0.020, 0.150)
    return [list(a) for a in adj], lat

def fair_share(reqs, U):
    """reqs: list of (arrive_time, bits, cap, id). Max-min fair sharing of U.
    Returns {id: finish_time}."""
    pending = sorted(reqs)
    active = {}  # id -> [remaining, cap]
    t = pending[0][0] if pending else 0
    out, i = {}, 0
    while i < len(pending) or active:
        while i < len(pending) and pending[i][0] <= t + 1e-12:
            _, b, c, k = pending[i]; active[k] = [b, c]; i += 1
        if not active:
            t = pending[i][0]; continue
        # max-min rates
        items = sorted(active.items(), key=lambda kv: kv[1][1])
        rem, n, rates = U, len(items), {}
        for idx, (k, (b, c)) in enumerate(items):
            r = min(c, rem / (n - idx)); rates[k] = r; rem -= r
        dt_fin = min(active[k][0] / rates[k] for k in active)
        dt_arr = pending[i][0] - t if i < len(pending) else math.inf
        dt = min(dt_fin, dt_arr)
        t += dt
        for k in list(active):
            active[k][0] -= rates[k] * dt
            if active[k][0] <= 1e-9:
                out[k] = t; del active[k]
    return out

def sequential(reqs, U, up, fastest):
    """One stream at a time at rate min(U, cap)."""
    pending = sorted(reqs)
    t, out, waiting, i = 0.0, {}, [], 0
    while i < len(pending) or waiting:
        if not waiting:
            t = max(t, pending[i][0])
        while i < len(pending) and pending[i][0] <= t + 1e-12:
            waiting.append(pending[i]); i += 1
        if fastest:
            waiting.sort(key=lambda r: -up[r[3]])
        a, b, c, k = waiting.pop(0)
        t = max(t, a) + b / min(U, c)
        out[k] = t
    return out

def run(adj, lat, up, down, cls, mode, bits, frac, val=0.05, seed=0):
    rng = random.Random(seed)
    N = len(adj)
    dcs = [i for i in range(N) if cls[i] == "datacenter"]
    src = rng.choice(dcs)
    recv = [math.inf] * N; recv[src] = 0.0
    pq = [(0.0, src, -1)]; done = set()
    while pq:
        tm, u, frm = heapq.heappop(pq)
        if u in done or tm > recv[u]:
            continue
        done.add(u)
        start = tm + val
        peers = [v for v in adj[u] if v != frm]
        rng.shuffle(peers)
        n = len(peers) if u == src else max(1, math.ceil(frac * len(peers)))
        reqs = []
        for v in peers[:n]:
            L = lat[(u, v)]
            if recv[v] > start + L:            # peer lacks it when inv lands
                reqs.append((start + 2 * L, bits, down[v], v))  # getdata arrives
        if not reqs:
            continue
        if mode == "parallel":
            fin = fair_share(reqs, up[u])
        else:
            fin = sequential(reqs, up[u], up, mode == "seq_fastest")
        for v, f in fin.items():
            arr = f + lat[(u, v)]
            if arr < recv[v]:
                recv[v] = arr; heapq.heappush(pq, (arr, v, u))
    r = sorted(recv)
    return r[len(r) // 2], r[int(len(r) * 0.9)]

if __name__ == "__main__":
    N = 1000
    up, down, cls = make_nodes(N)
    adj, lat = build(N, out=8)
    print(f"nodes={N} avg_peers={sum(map(len, adj))/N:.1f}")
    for name, *_ in CLASSES:
        idx = [i for i in range(N) if cls[i] == name]
        print(f"  {name:<11}{len(idx):>4} nodes  median up {st.median(up[i] for i in idx):6.1f} Mb/s")
    print()
    sizes = [("20 KB", 0.16), ("250 KB", 2.0), ("1 MB", 8.0), ("2 MB", 16.0)]
    modes = ["parallel", "seq_arrival", "seq_fastest"]
    for frac, flabel in [(1.0, "inv to all peers"), (1/3, "inv to 1/3 of peers")]:
        print(f"--- {flabel}  (p90 seconds, mean of 8 runs) ---")
        print(f"{'block':<8}" + "".join(f"{m:>14}" for m in modes) + f"{'best gain':>11}")
        for label, mb in sizes:
            res = {m: st.mean(run(adj, lat, up, down, cls, m, mb, frac, seed=s)[1]
                              for s in range(8)) for m in modes}
            gain = res["parallel"] / min(res["seq_arrival"], res["seq_fastest"])
            print(f"{label:<8}" + "".join(f"{res[m]:>13.2f}s" for m in modes) + f"{gain:>10.2f}x")
        print()
