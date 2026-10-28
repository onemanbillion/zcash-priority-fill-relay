import heapq, random, statistics as st

def build(N, out=8, seed=1):
    rng = random.Random(seed)
    adj = [set() for _ in range(N)]
    for u in range(N):
        while len([v for v in adj[u]]) < out and True:
            v = rng.randrange(N)
            if v != u:
                adj[u].add(v); adj[v].add(u)
            if len(adj[u]) >= out: break
    return [list(a) for a in adj]

def run(adj, mode, size_mbit, bw=50.0, lat=0.05, val=0.0, seed=2):
    rng = random.Random(seed)
    N = len(adj); t_per = size_mbit / bw
    recv = [float('inf')]*N
    src = 0; recv[src] = 0.0
    pq = [(0.0, src, -1)]
    done = set()
    while pq:
        t, u, frm = heapq.heappop(pq)
        if u in done or t > recv[u]: continue
        done.add(u)
        start = t + val
        peers = [v for v in adj[u] if v != frm]
        rng.shuffle(peers)
        if mode == 'parallel':
            need = [v for v in peers if recv[v] > start]  # peers lacking it at start
            k = len(need)
            for v in need:
                arr = start + k*t_per + lat
                if arr < recv[v]:
                    recv[v] = arr; heapq.heappush(pq, (arr, v, u))
        else:
            clock = start
            for v in peers:
                # skip peers that already got it (announce/inv check) before we'd start
                if recv[v] <= clock: continue
                clock += t_per
                arr = clock + lat
                if arr < recv[v]:
                    recv[v] = arr; heapq.heappush(pq, (arr, v, u))
    r = sorted(recv)
    return r[len(r)//2], r[int(len(r)*0.9)], r[-1]

N = 10000
adj = build(N)
print("avg degree", sum(map(len, adj))/N)
for label, mb in [("full block 1.5 MB", 12.0), ("compact block 20 KB", 0.16)]:
    for mode in ['parallel', 'sequential']:
        res = [run(adj, mode, mb, seed=s) for s in range(5)]
        m = [st.mean(x[i] for x in res) for i in range(3)]
        print(f"{label:22s} {mode:10s} median={m[0]:.2f}s p90={m[1]:.2f}s p100={m[2]:.2f}s")
