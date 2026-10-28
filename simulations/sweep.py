exec(open('sim.py').read().split("N = 10000")[0])
adj = build(10000)
for mb,label in [(12.0,'1.5MB'),(0.16,'20KB')]:
  for lat in [0.05,0.15]:
    for val in [0.0,0.1]:
      p=run(adj,'parallel',mb,lat=lat,val=val)[1]; s=run(adj,'sequential',mb,lat=lat,val=val)[1]
      print(f"{label} lat={lat*1000:.0f}ms val={val*1000:.0f}ms  p90 parallel={p:.2f}s sequential={s:.2f}s  ratio={p/s:.2f}x")
