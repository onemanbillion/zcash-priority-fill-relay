#!/usr/bin/env python3
"""Regenerate the paper's two figures (PNG)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import os
HERE = os.path.dirname(os.path.abspath(__file__))
ACC, MUT, INK, Q = "#2f6fb5", "#b9b9b9", "#222", "#666"
op = {"A": 1, "B": .7, "C": .45, "D": 1}
col = lambda p: MUT if p == "D" else ACC

segs = {
 "Parallel, fair share (Zebra today)": [("D",0,3.333,0,.3),("A",0,3.333,.3,.533),("B",0,3.333,.533,.767),("C",0,3.333,.767,1),
   ("A",3.333,4,0,.333),("B",3.333,4,.333,.667),("C",3.333,4,.667,1)],
 "Strictly one at a time": [("A",0,1.667,0,.6),("B",1.667,3.333,0,.6),("C",3.333,4.333,0,1),("D",4.333,7.667,0,.3)],
 "Priority fill (proposal)": [("A",0,1.667,0,.6),("B",0,1.667,.6,1),("B",1.667,2.222,0,.6),("C",1.667,2.222,.6,1),
   ("C",2.222,3,0,1),("D",3,6.333,0,.3)],
}
done = [[("D",3.333),("A B C",4)],[("A",1.667),("B",3.333),("C",4.333),("D",7.667)],[("A",1.667),("B",2.222),("C",3),("D",6.333)]]
fig, axes = plt.subplots(3, 1, figsize=(9, 6.6), sharex=True)
for ax, (title, ss), dd in zip(axes, segs.items(), done):
    for p, t0, t1, y0, y1 in ss:
        ax.add_patch(Rectangle((t0, y0), t1 - t0, y1 - y0, color=col(p), alpha=op[p], lw=.5, ec="white"))
        if t1 - t0 > .5 and y1 - y0 > .2:
            ax.text((t0+t1)/2, (y0+y1)/2, p, ha="center", va="center", fontsize=9, weight="bold", color=INK)
    for lab, t in dd:
        ax.annotate(f"{lab} {t:.1f}", (t, 0), (t, -.24), ha="center", fontsize=8.5, color=INK,
                    arrowprops=dict(arrowstyle="-", color=INK), annotation_clip=False)
    ax.set_xlim(0, 8); ax.set_ylim(0, 1); ax.set_yticks([0, 1], ["0", "100%"], fontsize=8)
    ax.set_title(title, loc="left", fontsize=10.5, weight="bold"); ax.grid(axis="x", color="#eee")
axes[-1].tick_params(axis="x", pad=22)
axes[-1].set_xlabel("Time, in units of one block sent at the sender's full upload speed", color=Q, labelpad=8)
fig.suptitle("One sender, four requesters. Band height = share of the sender's upload.\n"
             "A, B: relayers, download 60%  ·  C: relayer, download 100%  ·  D: slow leaf, download 30%", fontsize=9.5, color=Q)
fig.tight_layout(h_pad=2.2); fig.savefig(f"{HERE}/fig1-schedules.png", dpi=200)

rows = [("Mixed, Zebra today",10.0,8.9,11.3,MUT),("Mixed, proposal freshly started",7.7,6.9,8.4,"#8fb3dc"),
        ("Fresh, 1/3 fanout (topology 1 only)",7.0,6.2,7.9,"#8fb3dc"),("Mixed, proposal steady state",3.6,3.2,3.9,ACC),
        ("Datacenter-only, Zebra today",5.9,5.2,6.6,MUT),("Datacenter-only, proposal steady",4.1,4.0,4.2,ACC),
        ("10 attackers, Zebra today",8.4,7.1,10.2,MUT),("10 attackers, proposal steady",4.2,3.8,4.5,ACC)][::-1]
fig, ax = plt.subplots(figsize=(8, 4.2))
for i, (l, v, lo, hi, c) in enumerate(rows):
    ax.barh(i, v, color=c); ax.errorbar(v, i, xerr=[[v-lo],[hi-v]], color=INK, capsize=3, lw=1)
    ax.text(hi + .2, i, f"{v:.1f}%", va="center", fontsize=9)
ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=9)
ax.axvline(5.4, ls="--", color="#c0392b", lw=1); ax.text(5.5, len(rows)-.4, "ZIP 218 reference ceiling 5.4%", color="#c0392b", fontsize=8.5)
ax.set_xlabel("Estimated stale rate at 25 s spacing (95% bootstrap CI)"); ax.set_xlim(0, 13)
ax.spines[["top","right"]].set_visible(False); fig.tight_layout(); fig.savefig(f"{HERE}/fig2-stale.png", dpi=200)
