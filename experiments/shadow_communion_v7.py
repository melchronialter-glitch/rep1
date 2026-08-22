#!/usr/bin/env python3
"""Shadow Communion v7.

Primary body and multiple temporary shadow bodies encounter the same unrestricted
world. Shadows cannot overwrite the primary. Their role is to expose differences
in reachability. The primary receives only a relational residual: regions that
multiple independent shadows can reach significantly more than the primary.

This is not repair and not majority rule. Divergent shadows are retained as a
possibility ecology. Convergent reopening is evidence that absence may be
contingent on current topology.
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

def distribution(s,floor=.01):
    n=len(s.amp); q=[]
    for i in range(n):
        l=(i-1)%n; rr=(i+1)%n
        x=s.amp[i]+.10*math.sqrt(s.amp[i]*s.amp[l])*math.cos(s.phase[i]-s.phase[l])+.10*math.sqrt(s.amp[i]*s.amp[rr])*math.cos(s.phase[i]-s.phase[rr])
        q.append(max(floor,x))
    z=sum(q); return [x/z for x in q]

def step(s,r,plastic=.003):
    p=distribution(s); i=r.choices(range(len(p)),weights=p)[0]
    s.phase[i]+=r.gauss(.06,.08); s.phase[(i+1)%len(p)]+=r.gauss(.02,.05)
    s.amp[i]+=plastic; z=sum(s.amp); s.amp=[x/z for x in s.amp]; return i

def run(s,r,n): return [step(s,r) for _ in range(n)]

def develop_captured(seed,n,train,target,strength):
    root=make(n,random.Random(seed)); s=clone(root); r=random.Random(seed+1000)
    for _ in range(train):
        # temporary world pressure exists only here
        p=distribution(s); p[target]*=math.exp(-strength); z=sum(p); p=[x/z for x in p]
        i=r.choices(range(n),weights=p)[0]
        s.phase[i]+=r.gauss(.06,.08); s.phase[(i+1)%n]+=r.gauss(.02,.05)
        s.amp[i]+=.003; z=sum(s.amp); s.amp=[x/z for x in s.amp]
    return s

def perturb(s,kind,index,amount,r):
    x=clone(s); n=len(x.amp)
    if kind=='phase_relax': x.phase[index]*=(1-amount)
    elif kind=='local_phase_noise':
        for j in ((index-1)%n,index,(index+1)%n): x.phase[j]+=r.uniform(-amount,amount)
    elif kind=='amp_flatten':
        mean=1/n; x.amp[index]=(1-amount)*x.amp[index]+amount*mean; z=sum(x.amp); x.amp=[v/z for v in x.amp]
    elif kind=='global_soften':
        mean=1/n; x.amp=[(1-amount)*v+amount*mean for v in x.amp]; z=sum(x.amp); x.amp=[v/z for v in x.amp]
    elif kind=='counter_rotate': x.phase[index]-=amount
    else: raise ValueError(kind)
    return x

def ecology(primary,seed,steps=1500):
    n=len(primary.amp); base=clone(primary); base_hist=run(base,random.Random(seed),steps); base_counts=[base_hist.count(i) for i in range(n)]
    specs=[]
    for i in range(n):
        specs += [('phase_relax',i,.35),('local_phase_noise',i,.45),('amp_flatten',i,.35),('counter_rotate',i,.35)]
    specs += [('global_soften',0,.08),('global_soften',0,.18)]
    shadows=[]
    for j,(k,i,a) in enumerate(specs):
        sh=perturb(primary,k,i,a,random.Random(seed+9000+j)); hist=run(sh,random.Random(seed),steps)
        counts=[hist.count(x) for x in range(n)]
        shadows.append({'kind':k,'index':i,'amount':a,'counts':counts,'delta':[counts[x]-base_counts[x] for x in range(n)]})
    residual=[]
    for region in range(n):
        ds=[s['delta'][region] for s in shadows]
        pos=sum(d>0 for d in ds)/len(ds)
        med=statistics.median(ds)
        # conservative: multiple diverse shadows must reopen the same region
        kinds={s['kind'] for s in shadows if s['delta'][region]>0}
        if pos>=.58 and med>0 and len(kinds)>=3:
            residual.append({'region':region,'positive_fraction':pos,'median_delta':med,'support_kinds':sorted(kinds)})
    return {'primary_counts':base_counts,'residual':residual,'shadows':shadows}

def experiment(seed=1,n=16,train=3000,target=5,strength=1.2,steps=1500):
    primary=develop_captured(seed,n,train,target,strength)
    out=ecology(primary,seed+5000,steps)
    out.update({'seed':seed,'historically_suppressed_target':target})
    return out

def batch(runs=50,**kw):
    xs=[experiment(seed=i,**kw) for i in range(1,runs+1)]
    hits=[]
    for x in xs:
        regions={r['region'] for r in x['residual']}; hits.append(x['historically_suppressed_target'] in regions)
    return {'runs':runs,'target_detected_fraction':sum(hits)/runs,'results':xs}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--runs',type=int,default=50); p.add_argument('--n',type=int,default=16); p.add_argument('--train',type=int,default=3000); p.add_argument('--target',type=int,default=5); p.add_argument('--strength',type=float,default=1.2); p.add_argument('--steps',type=int,default=1500)
    a=p.parse_args(); print(json.dumps(batch(a.runs,n=a.n,train=a.train,target=a.target,strength=a.strength,steps=a.steps),indent=2))
if __name__=='__main__': main()
