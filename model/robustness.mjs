// Robustness evaluation of priority-fill block relay against non-cooperative nodes,
// run entirely inside the propagation model in sim.js. Nothing here touches a real network.
//
// For every scenario we run the SAME network, block schedule and misbehaving nodes under:
//   fair      Zebra today (TCP-like fair sharing of a sender's upload)
//   priority  priority fill, with whichever candidate defences are switched on
// and report metrics computed over HONEST nodes only. The question for each scenario is
// simply: is priority fill, under this behaviour, worse for honest nodes than today's
// relay is under the same behaviour? That gap is the exposure the ranking adds.

import { Sim, makeNetwork, PARAMS, rng, poissonSchedule } from './sim.js';

// A scenario sets how the misbehaving nodes behave. Fields:
//   frac       fraction of (non-miner) nodes that misbehave
//   up, down   their link speeds (Mb/s); `up` is what honest peers measure, so it sets rank
//   beh        { noRelay, noServe } behaviour flags passed through to the model
//   extraConn  extra connections each opens to random honest nodes (inbound there), widening reach
export const SCENARIOS = {
  none:       { frac: 0 },
  slowread:   { frac: 0.10, up: 500, down: 1,   beh: {} },                         // rank first, then read slowly to hold a slot
  blackhole:  { frac: 0.10, up: 500, down: 500, beh: { noRelay: true } },          // fetch fast, never relay onward
  withhold:   { frac: 0.10, up: 500, down: 500, beh: { noServe: true } },          // announce, then refuse to serve
  capture:    { frac: 0.10, up: 500, down: 500, beh: { noRelay: true }, extraConn: 40 }, // widely connected dead end
  slowcapture:{ frac: 0.10, up: 500, down: 1,   beh: {}, extraConn: 40 },          // slow reader, widely connected
};

function shuffle(r, a) { for (let k = a.length - 1; k > 0; k--) { const m = Math.floor(r() * (k + 1)); [a[k], a[m]] = [a[m], a[k]]; } return a; }

function applyScenario(net, sc, seed) {
  if (!sc.frac) return new Set();
  const r = rng(seed + 9001), nodes = net.nodes;
  const bad = new Set(shuffle(r, nodes.filter(n => !net.miners.includes(n.i)).map(n => n.i)).slice(0, Math.round(sc.frac * nodes.length)));
  for (const i of bad) {
    Object.assign(nodes[i], { cls: 'bad', up: sc.up, down: sc.down, beh: { ...sc.beh } });
    if (sc.extraConn) {
      const have = new Set(nodes[i].peers.map(q => q.j));
      const honest = shuffle(r, nodes.filter(n => !bad.has(n.i) && n.i !== i).map(n => n.i));
      for (const h of honest.slice(0, sc.extraConn)) {
        if (have.has(h)) continue;
        const lat = 0.02 + r() * 0.1;
        nodes[i].peers.push({ j: h, lat }); nodes[h].peers.push({ j: i, lat });
        nodes[i].outPeers.add(h); // i dialled h, so from h's view i is inbound
      }
    }
  }
  for (const n of nodes) n.lat = new Map(n.peers.map(q => [q.j, q.lat])); // rebuild after adding edges
  return bad;
}

// Honest-only metrics: stale rate miners actually see, and how long honest nodes wait for blocks.
function measure(sim, bad) {
  const stales = [], p50s = [], p90s = [];
  for (let b = 0; b < sim.blocks.length; b++) {
    const blk = sim.blocks[b];
    if (bad.has(blk.source)) continue; // only blocks honest miners produced
    const xs = [];
    for (let i = 0; i < blk.recv.length; i++)
      if (i !== blk.source && !bad.has(i) && isFinite(blk.recv[i])) xs.push(blk.recv[i] - blk.t);
    xs.sort((u, v) => u - v);
    const honest = sim.net.nodes.filter(n => !bad.has(n.i)).length - 1;
    if (xs.length < 0.5 * honest) continue;
    p50s.push(xs[Math.floor(0.5 * (xs.length - 1))]);
    if (xs.length >= 0.9 * honest) p90s.push(xs[Math.floor(0.9 * (xs.length - 1))]);
    // stale exposure for honest miners
    const ms = sim.net.miners.filter(m => m !== blk.source && !bad.has(m)).map(m => blk.val[m] - blk.t);
    if (ms.every(isFinite)) stales.push(ms.reduce((a, d) => a + (1 - Math.exp(-d / sim.p.intervalS)), 0) / ms.length);
  }
  const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN;
  return { stale: mean(stales) * 100, p50: mean(p50s), p90: mean(p90s), demotions: sim.demotions };
}

export function runScenario(scName, { n = 200, seeds = [1, 2, 3], blocks = 80, defences = {}, meanS, dt = 0.01 } = {}) {
  const sc = SCENARIOS[scName];
  const out = { fair: [], priority: [] };
  for (const seed of seeds) {
    for (const mode of ['fair', 'priority']) {
      const p = { ...PARAMS, n, dt, ...(mode === 'priority' ? defences : {}) };
      const net = makeNetwork(seed, { ...p, attackers: 0 });
      const bad = applyScenario(net, sc, seed);
      const sim = new Sim(net, mode, seed, p);
      const sched = poissonSchedule(net, blocks, seed + 5, meanS || p.intervalS, 2);
      for (const ev of sched) { sim.advance(ev.t); sim.addBlock(ev.t, ev.source); }
      sim.advance(sched[sched.length - 1].t + 90);
      out[mode].push(measure(sim, bad));
    }
  }
  const agg = rows => {
    const k = key => rows.map(r => r[key]).filter(isFinite);
    const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN;
    return { stale: mean(k('stale')), p50: mean(k('p50')), p90: mean(k('p90')), demotions: mean(k('demotions')) };
  };
  return { fair: agg(out.fair), priority: agg(out.priority) };
}

// CLI: node robustness.mjs [n] [blocks]  -> table across all scenarios, no defences
if (import.meta.url === `file://${process.argv[1]}`) {
  const n = Number(process.argv[2] || 200), blocks = Number(process.argv[3] || 80);
  const defs = process.argv[4] ? JSON.parse(process.argv[4]) : {};
  const f = x => (isFinite(x) ? x.toFixed(x < 10 ? 2 : 1) : '  - ');
  console.log(`n=${n}, ${blocks} blocks, defences=${JSON.stringify(defs)}`);
  console.log('scenario      | today stale  p50  p90 | PF stale  p50  p90  demote | PF−today stale');
  for (const name of Object.keys(SCENARIOS)) {
    const r = runScenario(name, { n, blocks, defences: defs });
    const d = r.priority.stale - r.fair.stale;
    console.log(
      `${name.padEnd(13)} |  ${f(r.fair.stale).padStart(5)}% ${f(r.fair.p50)} ${f(r.fair.p90)} ` +
      `| ${f(r.priority.stale).padStart(5)}% ${f(r.priority.p50)} ${f(r.priority.p90)} ${f(r.priority.demotions).padStart(5)} ` +
      `| ${(d >= 0 ? '+' : '') + d.toFixed(2)}%`);
  }
}
