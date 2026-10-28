#!/usr/bin/env python3
"""Run one testbed experiment: N zebra-relay nodes on loopback IPs, a topology and bandwidth
mix drawn from --topo-seed, blocks mined every --interval seconds by random datacenter nodes.

Time dilation (--dilation D) divides every bandwidth by D and multiplies latency, validation
time, block interval, gossip delay and timeouts by D. Results are divided by D afterwards, so
they read in real seconds. It keeps the machine's CPU from becoming the bottleneck.
"""
import argparse, json, math, os, random, signal, subprocess, sys, time

BIN = "/home/claude/zebra/zebra-relay/target/release/zebra-relay"
CLASSES = [("datacenter", .30, 500, 500), ("fiber", .25, 100, 500),
           ("cable", .35, 15, 150), ("poor", .10, 3, 25)]
REACH = {"datacenter": 1.0, "fiber": .5, "cable": .2, "poor": .05}

def make_topology(n, seed, outbound=8, profile="mixed"):
    rng = random.Random(seed)
    classes = CLASSES if profile == "mixed" else [("datacenter", 1.0, 500, 500)]
    nodes = []
    for i in range(n):
        r, acc = rng.random(), 0
        for name, sh, u, d in classes:
            acc += sh
            if r <= acc:
                break
        nodes.append(dict(id=i + 1, cls=name,
                          up=round(u * math.exp(rng.gauss(0, .35)), 2),
                          down=round(d * math.exp(rng.gauss(0, .35)), 2)))
    reachable = [x["id"] for x in nodes if rng.random() < REACH[x["cls"]]]
    edges = set()          # undirected, stored (min, max)
    out = {x["id"]: [] for x in nodes}
    for x in nodes:
        i, tries = x["id"], 0
        while len(out[i]) < outbound and tries < 2000:
            tries += 1
            j = rng.choice(reachable)
            if j == i or (min(i, j), max(i, j)) in edges:
                continue
            edges.add((min(i, j), max(i, j)))
            out[i].append(j)
    return nodes, out

IP_BASE = 0

def ip(i):
    return f"127.{IP_BASE}.{1 + (i - 1) // 250}.{1 + (i - 1) % 250}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--mode", default="zebra")
    ap.add_argument("--topo-seed", type=int, default=1)
    ap.add_argument("--blocks", type=int, default=10)
    ap.add_argument("--interval", type=float, default=25)
    ap.add_argument("--dilation", type=float, default=1)
    ap.add_argument("--warmup", type=float, default=60)
    ap.add_argument("--stagger", type=float, default=1.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=28000)
    ap.add_argument("--outbound", type=int, default=25)
    ap.add_argument("--ip-base", type=int, default=0)
    ap.add_argument("--profile", default="mixed")
    ap.add_argument("--attackers", type=int, default=0)
    ap.add_argument("--poisson", type=int, default=0,
                    help="if non-zero, draw block intervals from an exponential distribution with this seed")
    a = ap.parse_args()
    global IP_BASE
    IP_BASE = a.ip_base
    D = a.dilation
    os.makedirs(a.out, exist_ok=True)
    nodes, out = make_topology(a.n, a.topo_seed, a.outbound, a.profile)
    # Slow-reading attackers: fast upload earns them a high throughput ranking at their
    # peers, then they download blocks at 1 Mb/s to hold the victims' first upload slot.
    arng = random.Random(a.topo_seed * 7919)
    reach_ids = {j for l in out.values() for j in l}
    cands = [x for x in nodes if x["id"] in reach_ids and x["cls"] in ("fiber", "cable")]
    for x in arng.sample(cands, min(a.attackers, len(cands))):
        x.update(cls="attacker", up=500.0, down=1.0)
    rng = random.Random(a.topo_seed * 1000 + 7)
    miners = [x["id"] for x in nodes if x["cls"] == "datacenter"]
    t0 = int(time.time() * 1000) + int((a.n * a.stagger + a.warmup * D) * 1000)
    sched = []
    prng = random.Random(a.poisson)
    t_rel = 0.0
    for b in range(a.blocks):
        sched.append((t0 + int(t_rel * D * 1000), rng.choice(miners), rng.getrandbits(48)))
        t_rel += prng.expovariate(1.0 / a.interval) if a.poisson else a.interval
    with open(f"{a.out}/schedule.txt", "w") as f:
        for t, m, s in sched:
            f.write(f"{t} {m} {s}\n")
    meta = dict(vars(a), nodes=nodes, outbound=out, schedule=sched)
    json.dump(meta, open(f"{a.out}/meta.json", "w"))
    duration = a.n * a.stagger + a.warmup * D + (sched[-1][0] - t0) / 1000 + a.interval * D + 15 * D
    procs = []
    byid = {x["id"]: x for x in nodes}
    peers_of = {x["id"]: set(out[x["id"]]) for x in nodes}
    for i, l in out.items():
        for j in l:
            peers_of[j].add(i)
    erng = random.Random(a.topo_seed * 31337)
    for x in nodes:
        i = x["id"]
        extra = []
        relay_mode = a.mode
        if a.mode == "prio_warm":
            # A long-running node's state: a throughput estimate for every peer, as it would
            # have measured it (capped by its own download), with +-50% error.
            relay_mode = "prio"
            with open(f"{a.out}/est{i}.txt", "w") as f:
                for j in sorted(peers_of[i]):
                    est = min(byid[j]["up"], x["down"]) * math.exp(erng.gauss(0, .5))
                    f.write(f"{ip(j)} {est / D:.3f}\n")
            extra = ["--estimates", f"{a.out}/est{i}.txt"]
        cmd = [BIN, "--id", str(i), "--ip", ip(i), "--port", str(a.port),
               "--peers", ",".join(f"{ip(j)}:{a.port}" for j in out[i]),
               "--up", str(x["up"] / D), "--down", str(x["down"] / D), "--mode", relay_mode,
               "--schedule", f"{a.out}/schedule.txt", "--log", f"{a.out}/n{i}.log",
               "--seed", str(a.topo_seed), "--validate-ms", str(int(50 * D)),
               "--target", str(max(1, len(out[i]))),
               "--lat-min", str(20 * D), "--lat-max", str(150 * D),
               "--gossip-delay-ms", str(int(7000 * D)), "--dl-timeout-s", str(int(40 * D)),
               "--duration-s", str(int(duration)), "--time-scale", str(D)] + extra
        procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, env=dict(os.environ, MALLOC_ARENA_MAX="2"),
                                      stderr=open(f"{a.out}/n{i}.err", "w")))
        time.sleep(a.stagger)
    start = time.time()
    cpu_before = os.times()
    try:
        for p in procs:
            p.wait(timeout=duration + 60)
    except subprocess.TimeoutExpired:
        for p in procs:
            p.kill()
    wall = time.time() - start
    c = os.times()
    cpu = (c.children_user - cpu_before.children_user) + (c.children_system - cpu_before.children_system)
    json.dump(dict(wall=wall, cpu=cpu, cpu_util=cpu / wall / os.cpu_count()),
              open(f"{a.out}/run.json", "w"))
    print(f"done {a.out}: wall {wall:.0f}s, cpu {cpu:.0f}s, utilization {cpu/wall/os.cpu_count():.0%}")

if __name__ == "__main__":
    main()
