// Block propagation model: Zebra's current relay (fair-shared uploads) vs priority fill.
// An online engine: blocks can be added at any time (Poisson mining or a button), several
// blocks can be in flight at once and compete for bandwidth, and forks are tracked.
// Pure JS, no DOM: runs in the browser and in Node.

export function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Node classes used in the paper's testbed (upload / download in Mb/s).
export const CLASSES = [
  { id: 'dc', name: 'Datacenter', share: 0.30, up: 500, down: 500, accept: 1.0 },
  { id: 'fiber', name: 'Home fiber', share: 0.25, up: 100, down: 500, accept: 0.5 },
  { id: 'cable', name: 'Home cable', share: 0.35, up: 15, down: 150, accept: 0.2 },
  { id: 'rural', name: 'Rural / poor', share: 0.10, up: 3, down: 25, accept: 0.05 },
];

// Rough distribution of public nodes by region; positions on a unit plane.
export const REGIONS = [
  { name: 'North America', w: 0.32, x: -0.72, y: 0.5, r: 0.2 },
  { name: 'Europe', w: 0.34, x: -0.28, y: -0.42, r: 0.17 },
  { name: 'Asia', w: 0.20, x: 0.62, y: -0.6, r: 0.18 },
  { name: 'South America', w: 0.07, x: 0.08, y: 0.8, r: 0.12 },
  { name: 'Oceania', w: 0.07, x: 0.98, y: 0.02, r: 0.1 },
];

export const PARAMS = {
  n: 1000,
  outbound: 25, // Zebra's default outbound target
  maxInbound: 100,
  blockMbit: 2 * 8, // a full 2 MB block
  validateS: 0.05, // the testbed's fixed validation delay
  fanout: 1 / 3, // relayed blocks are announced to a random third of peers
  gossipDelayS: 7, // zebrad's PEER_GOSSIP_DELAY between tip broadcasts (mined blocks skip it)
  requestTimeoutS: 20, // zebra-network REQUEST_TIMEOUT; the node then fetches from another peer
  dt: 0.002,
  // priority fill
  fillThreshold: 0.85,
  fillIdleS: 0.1,
  admitGapS: 0.05,
  overdueS: 5,
  estNoise: 0.5, // ±50% error on each node's view of each peer
  demote: true, // cap a peer's rank at the rate it actually read a block response at
  demoteRatio: 0.25,
  minerCount: 40,
  intervalS: 25,
  attackers: 0, // slow-reading attackers: 500 Mb/s up (ranked first), 1 Mb/s down
};

function gauss(r) {
  let u = 0, v = 0;
  while (u === 0) u = r();
  while (v === 0) v = r();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function pick(r, items, key) {
  let x = r() * items.reduce((a, b) => a + b[key], 0);
  for (const it of items) if ((x -= it[key]) <= 0) return it;
  return items[items.length - 1];
}

export function makeNetwork(seed = 7, p = PARAMS) {
  const r = rng(seed);
  const nodes = [];
  for (let i = 0; i < p.n; i++) {
    const cls = pick(r, CLASSES, 'share');
    const reg = pick(r, REGIONS, 'w');
    const j = () => 0.65 + 0.7 * r();
    nodes.push({
      i, cls: cls.id, region: reg.name,
      x: reg.x + gauss(r) * reg.r * 0.45, y: reg.y + gauss(r) * reg.r * 0.45,
      up: cls.up * j(), down: cls.down * j(), accept: cls.accept, peers: [], inbound: 0,
    });
  }
  const accepting = nodes.filter(n => n.accept > 0);
  const totalW = accepting.reduce((a, n) => a + n.accept, 0);
  const has = new Set();
  const key = (a, b) => (a < b ? a * 100000 + b : b * 100000 + a);
  for (const n of nodes) {
    let tries = 0, made = 0;
    while (made < p.outbound && tries++ < 2000) {
      let x = r() * totalW, t = accepting[0];
      for (const c of accepting) if ((x -= c.accept) <= 0) { t = c; break; }
      if (t === n || t.inbound >= p.maxInbound || has.has(key(n.i, t.i))) continue;
      has.add(key(n.i, t.i));
      t.inbound++;
      made++;
      const d = Math.hypot(n.x - t.x, n.y - t.y);
      const lat = Math.min(0.16, Math.max(0.008, 0.006 + d * 0.075 + r() * 0.01));
      n.peers.push({ j: t.i, lat });
      t.peers.push({ j: n.i, lat });
    }
  }
  if (p.attackers) {
    const ar = rng(seed + 99);
    const cands = nodes.filter(n => n.cls === 'fiber' || n.cls === 'cable');
    for (let k = 0; k < p.attackers && cands.length; k++) {
      const n = cands.splice(Math.floor(ar() * cands.length), 1)[0];
      n.cls = 'attacker'; n.up = 500; n.down = 1;
    }
  }
  const edges = [];
  for (const n of nodes) for (const q of n.peers) if (n.i < q.j) edges.push([n.i, q.j]);
  const dcs = nodes.filter(n => n.cls === 'dc');
  const mr = rng(seed + 1);
  const miners = [];
  while (miners.length < Math.min(p.minerCount, dcs.length)) {
    const m = dcs[Math.floor(mr() * dcs.length)].i;
    if (!miners.includes(m)) miners.push(m);
  }
  for (const n of nodes) n.lat = new Map(n.peers.map(q => [q.j, q.lat]));
  return { nodes, edges, miners, seed };
}

class Heap {
  constructor() { this.a = []; }
  push(e) {
    const a = this.a; a.push(e);
    let i = a.length - 1;
    while (i > 0) { const q = (i - 1) >> 1; if (a[q][0] <= a[i][0]) break; [a[q], a[i]] = [a[i], a[q]]; i = q; }
  }
  pop() {
    const a = this.a, top = a[0], last = a.pop();
    if (a.length) {
      a[0] = last; let i = 0;
      for (;;) {
        const l = 2 * i + 1, rr = l + 1; let m = i;
        if (l < a.length && a[l][0] < a[m][0]) m = l;
        if (rr < a.length && a[rr][0] < a[m][0]) m = rr;
        if (m === i) break; [a[m], a[i]] = [a[i], a[m]]; i = m;
      }
    }
    return top;
  }
  peek() { return this.a[0]; }
  get size() { return this.a.length; }
}

function pairNoise(seed, a, b, amp) {
  let h = (seed * 2654435761) ^ (a * 40503) ^ (b * 2246822519);
  h = Math.imul(h ^ (h >>> 16), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909); h ^= h >>> 16;
  return 1 - amp + 2 * amp * ((h >>> 0) / 4294967296);
}

const INV = 0, GETDATA = 1, ARRIVE = 2, TIMEOUT = 3, VALID = 4, GOSSIP = 5;

// mode: 'fair' (Zebra today) or 'priority' (priority fill with learned rankings)
export class Sim {
  constructor(net, mode, seed = 1, p = PARAMS) {
    this.net = net; this.mode = mode; this.p = p;
    this.r = rng(seed * 7919 + 13);
    const N = net.nodes.length;
    this.t = 0;
    this.heap = new Heap();
    this.blocks = []; // {id, t, source, parent, height, recv, val, fetching}
    this.tip = new Int32Array(N).fill(-1); // best validated block per node
    this.lastGossip = new Float64Array(N).fill(-Infinity);
    this.gossipPending = new Uint8Array(N);
    this.lastAnnounced = new Int32Array(N).fill(-1);
    this.waitingParent = Array.from({ length: N }, () => []);
    this.S = net.nodes.map(() => ({ active: [], waiting: [], lastAdmit: -1, belowSince: -1 }));
    this.downActive = new Uint16Array(N);
    this.busy = new Set();
    this.caps = new Map(); // sender*N+peer -> demoted rate cap (Mb/s)
    this.recent = []; // completed or aborted transfers, for drawing
    this.demotions = 0;
  }

  heightOf(id) { return id < 0 ? 0 : this.blocks[id].height; }

  addBlock(t, source) {
    const N = this.net.nodes.length;
    const parent = this.tip[source];
    const b = { id: this.blocks.length, t, source, parent, height: this.heightOf(parent) + 1,
      recv: new Float64Array(N).fill(Infinity), val: new Float64Array(N).fill(Infinity),
      fetching: new Uint8Array(N) };
    this.blocks.push(b);
    b.recv[source] = t; b.val[source] = t;
    this.tip[source] = b.id;
    // zebrad sends a mined block at once, then its gossip loop sleeps PEER_GOSSIP_DELAY
    for (const q of this.net.nodes[source].peers) this.heap.push([t + q.lat, INV, source, q.j, b.id]);
    this.lastGossip[source] = t; this.lastAnnounced[source] = b.id;
    return b.id;
  }

  // The node now holds a validated block.
  validated(i, b, t) {
    const blk = this.blocks[b];
    if (blk.val[i] <= t) return;
    blk.val[i] = t;
    if (this.heightOf(b) > this.heightOf(this.tip[i])) {
      this.tip[i] = b;
      if (!this.gossipPending[i]) {
        this.gossipPending[i] = 1;
        this.heap.push([Math.max(t, this.lastGossip[i] + this.p.gossipDelayS), GOSSIP, i, 0, 0]);
      }
    }
    const kids = this.waitingParent[i];
    for (let k = kids.length - 1; k >= 0; k--) {
      const c = kids[k];
      if (this.blocks[c].parent === b) { kids.splice(k, 1); this.heap.push([t + this.p.validateS, VALID, i, 0, c]); }
    }
  }

  arrived(i, from, b, t) {
    const blk = this.blocks[b];
    if (blk.recv[i] !== Infinity) return;
    blk.recv[i] = t;
    const par = blk.parent;
    if (par < 0 || this.blocks[par].val[i] <= t) {
      this.heap.push([t + this.p.validateS, VALID, i, 0, b]);
    } else {
      this.waitingParent[i].push(b);
      // parent lookup: fetch the missing parent from the peer that sent the child
      const pb = this.blocks[par];
      if (pb.recv[i] === Infinity && !pb.fetching[i]) {
        pb.fetching[i] = 1;
        this.heap.push([t + this.net.nodes[i].lat.get(from), GETDATA, i, from, par]);
      }
    }
  }

  baseEst(sender, peer) {
    const n = this.net.nodes;
    return Math.min(n[peer].up, n[sender].down) * pairNoise(this.net.seed, sender, peer, this.p.estNoise);
  }

  est(sender, peer) {
    const base = this.baseEst(sender, peer);
    const cap = this.caps.get(sender * this.net.nodes.length + peer);
    return cap === undefined ? base : Math.min(base, cap);
  }

  event(e) {
    const [te, kind, a, b, x] = e;
    const p = this.p, nodes = this.net.nodes;
    if (kind === INV) { // a announced block x to b
      const blk = this.blocks[x];
      if (blk.recv[b] === Infinity && !blk.fetching[b]) { blk.fetching[b] = 1; this.heap.push([te + nodes[b].lat.get(a), GETDATA, b, a, x]); }
    } else if (kind === GETDATA) { // requester a asks sender b for block x
      const req = { blk: x, to: a, from: b, tReq: te, size: p.blockMbit, left: p.blockMbit, rate: 0, t0: -1,
        est: this.est(b, a), done: false };
      const s = this.S[b];
      if (this.mode === 'fair') this.start(req, te); else s.waiting.push(req);
      this.busy.add(b);
      this.heap.push([te + p.requestTimeoutS, TIMEOUT, a, b, req]);
    } else if (kind === ARRIVE) {
      this.arrived(a, b, x, te);
    } else if (kind === VALID) {
      this.validated(a, x, te);
    } else if (kind === GOSSIP) {
      this.gossipPending[a] = 0;
      const tip = this.tip[a];
      if (tip >= 0 && tip !== this.lastAnnounced[a]) {
        const peers = nodes[a].peers.slice();
        for (let k = peers.length - 1; k > 0; k--) { const m = Math.floor(this.r() * (k + 1)); [peers[k], peers[m]] = [peers[m], peers[k]]; }
        for (const q of peers.slice(0, Math.ceil(peers.length * p.fanout))) this.heap.push([te + q.lat, INV, a, q.j, tip]);
        this.lastGossip[a] = te; this.lastAnnounced[a] = tip;
      }
    } else if (kind === TIMEOUT) {
      const req = x;
      const blk = this.blocks[req.blk];
      if (req.done || blk.recv[a] !== Infinity) return;
      // The requester gives up. A response not started yet is dropped; one already being sent
      // runs to the end (Zebra does not cancel it), but its block is ignored on arrival.
      req.abandoned = true;
      const s = this.S[b];
      const k = s.waiting.indexOf(req);
      if (k >= 0) { s.waiting.splice(k, 1); req.done = true; }
      if (req.t0 >= 0) this.recent.push({ from: b, to: a, blk: req.blk, t1: te, aborted: true });
      const holders = nodes[a].peers.filter(q => q.j !== b && blk.val[q.j] <= te);
      const pool = holders.length ? holders : nodes[a].peers;
      const q = pool[Math.floor(this.r() * pool.length)];
      this.heap.push([te + q.lat, GETDATA, a, q.j, req.blk]);
    }
  }

  start(req, t) {
    req.t0 = t;
    this.S[req.from].active.push(req);
    this.downActive[req.to]++;
  }

  step() {
    const p = this.p, nodes = this.net.nodes, t = this.t;
    for (const i of this.busy) {
      const s = this.S[i], U = nodes[i].up;
      const cap = q => nodes[q.to].down / Math.max(1, this.downActive[q.to]);
      if (this.mode === 'priority') {
        // stall watchdog: a response still running when even a slow honest reader would have
        // finished gives up its slot and demotes the peer
        let live = 0;
        for (const q of s.active) {
          if (!q.released && p.demote && t - q.t0 >= Math.max(p.fillIdleS, q.size / (p.demoteRatio * Math.min(q.est, U)))) {
            q.released = true;
            this.caps.set(i * nodes.length + q.to, q.size / (t - q.t0));
            this.demotions++;
          }
          if (!q.released) live++;
        }
        const used = s.active.reduce((acc, q) => acc + Math.min(cap(q), U), 0);
        if (used < p.fillThreshold * U) { if (s.belowSince < 0) s.belowSince = t; } else s.belowSince = -1;
        const canAdmit = s.waiting.length && (live === 0 ||
          (s.belowSince >= 0 && t - s.belowSince >= p.fillIdleS && t - s.lastAdmit >= p.admitGapS));
        let k = -1;
        for (let m = 0; m < s.waiting.length; m++) if (t - s.waiting[m].tReq > p.overdueS) { k = m; break; }
        if (canAdmit || k >= 0) {
          if (k < 0) { k = 0; for (let m = 1; m < s.waiting.length; m++) if (s.waiting[m].est > s.waiting[k].est) k = m; }
          const q = s.waiting.splice(k, 1)[0];
          this.start(q, t); s.lastAdmit = t; s.belowSince = -1;
        }
        let rem = U;
        for (const q of s.active) if (!q.released) { q.rate = Math.min(cap(q), rem); rem -= q.rate; }
        for (const q of s.active) if (q.released) { q.rate = Math.min(cap(q), rem); rem -= q.rate; }
      } else {
        // TCP-like fair share, water-filling unused share
        const act = s.active.slice().sort((x, y) => cap(x) - cap(y));
        let rem = U, k = act.length;
        for (const q of act) { q.rate = Math.min(cap(q), rem / k); rem -= q.rate; k--; }
      }
      for (let m = s.active.length - 1; m >= 0; m--) {
        const q = s.active[m];
        q.left -= q.rate * p.dt;
        if (q.left <= 0) {
          s.active.splice(m, 1);
          q.done = true;
          this.downActive[q.to]--;
          const L = nodes[i].lat.get(q.to);
          if (!q.abandoned) {
            this.recent.push({ from: i, to: q.to, blk: q.blk, t1: t + L });
            this.heap.push([t + L, ARRIVE, q.to, i, q.blk]);
          }
          if (this.mode === 'priority' && p.demote) {
            const rate = q.size / Math.max(1e-6, t - q.t0);
            const key = i * nodes.length + q.to;
            if (rate < p.demoteRatio * Math.min(q.est, U)) { this.caps.set(key, rate); this.demotions++; } else this.caps.delete(key);
          }
        }
      }
      if (!s.active.length && !s.waiting.length) this.busy.delete(i);
    }
  }

  // Run the model forward to time tEnd.
  advance(tEnd) {
    while (this.t < tEnd) {
      while (this.heap.size && this.heap.peek()[0] <= this.t) this.event(this.heap.pop());
      if (!this.busy.size) {
        const nxt = this.heap.size ? this.heap.peek()[0] : Infinity;
        if (nxt > tEnd) { this.t = tEnd; break; }
        this.t = Math.max(this.t, Math.ceil(nxt / this.p.dt) * this.p.dt);
        continue;
      }
      this.step();
      this.t += this.p.dt;
    }
    if (this.recent.length > 4000) this.recent = this.recent.filter(x => x.t1 > this.t - 1);
  }

  // Transfers in flight now, with progress 0..1.
  inFlight() {
    const out = [];
    for (const i of this.busy) for (const q of this.S[i].active) if (!q.abandoned) out.push({ from: i, to: q.to, blk: q.blk, f: 1 - q.left / q.size });
    return out;
  }

  blockStats(b) {
    const blk = this.blocks[b], p = this.p;
    const xs = [], N = blk.recv.length;
    for (let i = 0; i < N; i++) if (i !== blk.source && isFinite(blk.recv[i])) xs.push(blk.recv[i] - blk.t);
    xs.sort((x, y) => x - y);
    const q = f => (xs.length ? xs[Math.min(xs.length - 1, Math.floor(f * (N - 1)))] : NaN);
    const ms = this.net.miners.filter(m => m !== blk.source).map(m => blk.val[m] - blk.t);
    const reachedMiners = ms.filter(isFinite);
    const sorted = ms.slice().sort((x, y) => x - y);
    const stale = ms.reduce((a, d) => a + (1 - Math.exp(-d / p.intervalS)), 0) / ms.length;
    return { reached: xs.length + 1, p50: xs.length >= (N - 1) / 2 ? q(0.5) : NaN, p90: xs.length >= 0.9 * (N - 1) ? q(0.9) : NaN,
      last: xs.length === N - 1 ? xs[xs.length - 1] : NaN, minersReached: reachedMiners.length, miners: ms.length,
      minerP50: sorted[Math.floor(sorted.length / 2)], stale: reachedMiners.length === ms.length ? stale : NaN };
  }

  // Blocks off the longest chain: the real orphan count under this model.
  orphans() {
    if (!this.blocks.length) return 0;
    let best = this.blocks[0];
    for (const b of this.blocks) if (b.height > best.height) best = b;
    let len = 0;
    for (let id = best.id; id >= 0; id = this.blocks[id].parent) len++;
    return this.blocks.length - len;
  }
}

// Convenience for tests and analysis: a Poisson block schedule.
export function poissonSchedule(net, count, seed, meanS = PARAMS.intervalS, start = 0) {
  const r = rng(seed);
  const out = [];
  let t = start;
  for (let k = 0; k < count; k++) {
    out.push({ t, source: net.miners[Math.floor(r() * net.miners.length)] });
    t += -Math.log(1 - r()) * meanS;
  }
  return out;
}
