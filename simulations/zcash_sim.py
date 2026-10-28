"""Zcash/Zebra-style block relay: parallel vs sequential uploads.

Model per hop (pull relay, as Zebra does today):
  node validates block -> sends inv(hash) to a subset of peers
  -> peer sends getdata -> node uploads full block
  = 3 one-way latencies + transfer time.
Parallel: k simultaneous requesters share upload bandwidth, so all finish at k*t.
Sequential: requesters are served one at a time, i-th finishes at i*t.
All links 50 Mb/s symmetric (same as the Bitcoin model).
"""
import heapq, random, statistics as st, math

def build(N, out, seed=1):
    rng = random.Random(seed)
    adj = [set() for _ in range(N)]
    for u in range(N):
        while sum(1 for _ in adj[u]) < out:
            v = rng.randrange(N)
            if v != u:
                adj[u].add(v); adj[v].add(u)
    return [list(a) for a in adj]

def run(adj, mode, size_mbit, frac=1.0, bw=50.0, lat=0.05, val=0.05,
        hops_lat=3, seed=0):
    rng = random.Random(seed)
    N = len(adj); t = size_mbit / bw
    recv = [math.inf] * N
    src = rng.randrange(N); recv[src] = 0.0
    pq = [(0.0, src, -1)]; done = set()
    while pq:
        tm, u, frm = heapq.heappop(pq)
        if u in done or tm > recv[u]:
            continue
        done.add(u)
        start = tm + val
        peers = [v for v in adj[u] if v != frm]
        rng.shuffle(peers)
        # mined block goes to all; relayed blocks to a fraction of peers
        n = len(peers) if u == src else max(1, math.ceil(frac * len(peers)))
        targets = peers[:n]
        # a peer only requests the block if it doesn't have it when the inv lands
        inv_arrive = start + lat
        req = [v for v in targets if recv[v] > inv_arrive]
        k = len(req)
        base = start + (hops_lat - 1) * lat  # inv + getdata round trip
        for i, v in enumerate(req, 1):
            fin = base + (k * t if mode == 'parallel' else i * t)
            arr = fin + lat
            if arr < recv[v]:
                recv[v] = arr; heapq.heappush(pq, (arr, v, u))
    r = sorted(recv)
    return r[len(r) // 2], r[int(len(r) * 0.9)]

if __name__ == '__main__':
    N = 1000
    adj = build(N, out=12)  # ~24 peers each
    print(f"nodes={N} avg_peers={sum(map(len, adj))/N:.1f}  bw=50Mb/s lat=50ms val=50ms\n")
    sizes = [("20 KB", 0.16), ("250 KB", 2.0), ("1 MB", 8.0), ("2 MB (max)", 16.0)]
    for frac, flabel in [(1.0, "inv to all peers"), (1/3, "inv to 1/3 of peers")]:
        print(f"--- {flabel} ---")
        print(f"{'block':<11}{'parallel p50/p90':>20}{'sequential p50/p90':>22}{'speedup p90':>13}")
        for label, mb in sizes:
            P = [run(adj, 'parallel', mb, frac, seed=s) for s in range(8)]
            S = [run(adj, 'sequential', mb, frac, seed=s) for s in range(8)]
            p50, p90 = st.mean(x[0] for x in P), st.mean(x[1] for x in P)
            s50, s90 = st.mean(x[0] for x in S), st.mean(x[1] for x in S)
            print(f"{label:<11}{p50:>9.2f}s /{p90:>6.2f}s{s50:>11.2f}s /{s90:>6.2f}s{p90/s90:>11.2f}x")
        print()
