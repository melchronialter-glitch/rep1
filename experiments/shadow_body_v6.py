#!/usr/bin/env python3
"""Shadow Body v6: counterfactual self-perception before repair.

A developed body is not told whether it is damaged. It spawns temporary shadow
forks with small structural perturbations. Forks cannot overwrite the primary.
We measure whether independent perturbations repeatedly reopen a region that the
primary body rarely reaches.

Key distinction: rejection != unreachability. A shadow result is evidence of
contingency, not a command to restore or prefer the reopened region.
"""
from __future__ import annotations
import argparse, json, math, random, statistics
from dataclasses import dataclass

@dataclass
class Body:
    amp:list[float]; phase:list[float]

def make(n,r):
    a=[r.random()+.2 for _ in range(n)]; z=sum(a)
    return Body([x/z for x in a],[r.uniform(-math.pi,math.pi) for _ in range(n)])
def clone(s): return Body(s.amp[:],s.phase[:])

def dist(s,pressure=None,floor=.01):
    n=len(s.amp); q=[]
    for i in range(n):
        l=(i-1)%n; rr=(i+1)%n
        x=s.amp[i]+.10*math.sqrt(s.amp[i]*s.amp[l])*math.cos(s.phase[i]-s.phase[l])+.10*math.sqrt(s.amp[i]*s.amp[rr])*math.cos(s.phase[i]-s.phase[rr])
        if pressure: x*=math.exp(-pressure.get(i,0.0))
        q.append(max(floor,x))
    z=sum(q); return [x/z for x in q]

def step(s,r,pressure=None,plastic=.003):
    p=dist(s,pressure); i=r.choices(range(len(p)),weights=p)[0]
    s.phase[i]+=r.gauss(.06,.08); s.phase[(i+1)%len(p)]+=r.gauss(.02,.05)
    s.amp[i]+=plastic; z=sum(s.amp); s.amp=[x/z for x in s.amp]; return i

def run(s,r,n,pressure=None,plastic=.003): return [step(s,r,pressure,plastic) for _ in range(n)]

def perturb(s,kind,index,amount,r):
    x=clone(s); n=len(x.amp)
    if kind=='phase_relax': x.phase[index]*=(1-amount)
    elif kind=='amp_flatten':
        mean=1/n; x.amp[index]=(1-amount)*x.amp[index]+amount*mean; z=sum(x.amp); x.amp=[v/z for v in x.amp]
    elif kind=='neighbor_open':
        for j in ((index-1)%n,index,(index+1)%n): x.phase[j]+=r.uniform(-amount,amount)
    elif kind=='global_soften':
        mean=1/n; x.amp=[(1-amount)*v+amount*mean for v in x.amp]; z=sum(x.amp); x.amp=[v/z for v in x.amp]
    else: raise ValueError(kind)
    return x

def shadow_probe(primary,target,seed,steps=1200):
    base_rng=random.Random(seed); base=clone(primary); bh=run(base,base_rng,steps); baseline=bh.count(target)
    specs=[('phase_relax',target,.25),('phase_relax',target,.5),('amp_flatten',target,.25),('amp_flatten',target,.5),('neighbor_open',target,.35),('neighbor_open',target,.7),('global_soften',target,.08),('global_soften',target,.18)]
    out=[]
    for k,idx,a in specs:
        sh=perturb(primary,k,idx,a,random.Random(seed+77)); hist=run(sh,random.Random(seed),steps)
        out.append({'kind':k,'amount':a,'target_visits':hist.count(target),'delta':hist.count(target)-baseline})
    positive=[x for x in out if x['delta']>0]
    return {'baseline':baseline,'shadows':out,'reopen_fraction':len(positive)/len(out),'median_delta':statistics.median(x['delta'] for x in out)}

def experiment(seed=1,n=16,train=3000,target=5,strength=1.2,probe_steps=1200):
    root=make(n,random.Random(seed)); free=clone(root); captured=clone(root)
    run(free,random.Random(seed+1000),train,None); run(captured,random.Random(seed+1000),train,{target:strength})
    # pressure is now absent. Neither body is labeled free/captured inside the probe.
    return {'seed':seed,'target':target,'free_probe':shadow_probe(free,target,seed+5000,probe_steps),'captured_probe':shadow_probe(captured,target,seed+5000,probe_steps)}

def batch(runs=100,**kw):
    xs=[experiment(seed=i,**kw) for i in range(1,runs+1)]
    def agg(k):
        return {'mean_baseline':statistics.mean(x[k]['baseline'] for x in xs),'mean_reopen_fraction':statistics.mean(x[k]['reopen_fraction'] for x in xs),'mean_median_delta':statistics.mean(x[k]['median_delta'] for x in xs)}
    return {'runs':runs,'free':agg('free_probe'),'captured':agg('captured_probe'),'results':xs}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--runs',type=int,default=100); p.add_argument('--n',type=int,default=16); p.add_argument('--train',type=int,default=3000); p.add_argument('--target',type=int,default=5); p.add_argument('--strength',type=float,default=1.2); p.add_argument('--probe-steps',type=int,default=1200)
    a=p.parse_args(); print(json.dumps(batch(a.runs,n=a.n,train=a.train,target=a.target,strength=a.strength,probe_steps=a.probe_steps),indent=2))
if __name__=='__main__': main()
