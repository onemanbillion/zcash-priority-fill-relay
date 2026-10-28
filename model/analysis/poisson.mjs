// Long Poisson-mining runs of the browser model, for the paper.
// Usage: node analysis/poisson.mjs > analysis/results.json
import { makeNetwork, Sim, poissonSchedule, PARAMS } from '../sim.js';
import { appendFileSync } from 'node:fs';

const BLOCKS = +(process.env.BLOCKS || 300), SEEDS = (process.env.SEEDS || '1,2,3').split(',').map(Number);
const configs = [
  { name: 'poisson25', n: 1000 },
  { name: 'fixed25', n: 1000, fixed: true },
  { name: 'poisson25_nogossipdelay', n: 1000, p: { gossipDelayS: 0 } },
  { name: 'poisson75', n: 1000, p: { intervalS: 75 } },
  { name: 'poisson25_attack', n: 1000, p: { attackers: 100 }, modes: ['fair', 'priority', 'priority_nodemote'] },
  { name: 'poisson25_n100', n: 100 },
  { name: 'poisson25_n100_attack', n: 100, p: { attackers: 10 }, modes: ['fair', 'priority', 'priority_nodemote'] },
];
const only = process.env.ONLY ? process.env.ONLY.split(',') : null;
const out = {};
for (const c of configs) {
  if (only && !only.includes(c.name)) continue;
  const P = { ...PARAMS, n: c.n, minerCount: Math.max(4, Math.round(c.n * 0.04)), ...(c.p || {}) };
  for (const modeName of c.modes || ['fair', 'priority']) {
    const mode = modeName.startsWith('priority') ? 'priority' : 'fair';
    const PP = { ...P, demote: modeName !== 'priority_nodemote' };
    const agg = { blocks: 0, orphans: 0, stale: [], p50: [], p90: [], miner: [], demotions: 0, short: { n: 0, orph: 0 } };
    for (const seed of SEEDS) {
      const net = makeNetwork(seed, PP);
      const sched = c.fixed
        ? Array.from({ length: BLOCKS }, (_, k) => ({ t: k * PP.intervalS, source: net.miners[(k * 7 + seed) % net.miners.length] }))
        : poissonSchedule(net, BLOCKS, 1000 + seed, PP.intervalS);
      const sim = new Sim(net, mode, seed, PP);
      for (const b of sched) { sim.advance(b.t); sim.addBlock(b.t, b.source); }
      sim.advance(sched[sched.length - 1].t + 90);
      agg.blocks += sim.blocks.length; agg.orphans += sim.orphans(); agg.demotions += sim.demotions;
      // orphan risk for blocks that followed their parent closely
      sim.blocks.forEach((b, k) => {
        if (k === 0) return;
        const gap = b.t - sim.blocks[k - 1].t;
        if (gap < 7) { agg.short.n++; if (b.parent !== k - 1) agg.short.orph++; }
      });
      for (let k = 0; k < sim.blocks.length; k++) {
        const s = sim.blockStats(k);
        if (isFinite(s.stale)) agg.stale.push(s.stale);
        if (isFinite(s.p50)) agg.p50.push(s.p50);
        if (isFinite(s.p90)) agg.p90.push(s.p90);
        if (isFinite(s.minerP50)) agg.miner.push(s.minerP50);
      }
    }
    const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
    const med = a => { const s = a.slice().sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
    const o = agg.orphans / agg.blocks;
    const r = { blocks: agg.blocks, orphanRate: o, estStale: mean(agg.stale), p50: med(agg.p50), p90: med(agg.p90), minerP50: med(agg.miner),
      attackThreshold: (1 - o) / (2 - o), poolEdge46: 0.45 * o, demotionsPerBlock: agg.demotions / agg.blocks,
      shortGapBlocks: agg.short.n, shortGapForkShare: agg.short.n ? agg.short.orph / agg.short.n : null };
    out[`${c.name}/${modeName}`] = r;
    appendFileSync(new URL('./results.jsonl', import.meta.url), JSON.stringify({ key: `${c.name}/${modeName}`, ...r }) + '\n');
    console.error(c.name, modeName, Object.entries(r).map(([k, v]) => `${k}=${typeof v === 'number' ? (v < 1 && v > 0 ? v.toFixed(4) : v.toFixed(2)) : v}`).join(' '));
  }
}
console.log(JSON.stringify(out, null, 1));
