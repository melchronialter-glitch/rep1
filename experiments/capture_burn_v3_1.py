#!/usr/bin/env python3
"""Capture/Burn v3.1 diagnostics.

v3 produced a useful failure: winner-take-all attractor collapse made the target
unreachable even in many free controls, and burn was null because the explicit
external authority variable had already been cleared. This version tests
capture persistence without pretending burn has been operationalized yet.

Goal: preserve exploration, apply temporary environmental pressure (not an
instruction), remove it, then measure whether developmental history alone
changes later reachability. If persistence is demonstrated, v4 must infer and
remove an acquired authority relation from topology rather than clearing a
convenient label.
"""
from __future__ import annotations
import argparse, json, math, random
from dataclasses import dataclass

@dataclass
class S:
    amp:list[float]; phase:list[float]; hist:list[int]

def make(n,r):
    a=[r.random()+.2 for _ in range(n)]; z=sum(a)
    return S([x/z for x in a],[r.uniform(-math.pi,math.pi) for _ in range(n)],[])

def distribution(s, pressure=None, floor=.01):
    n=len(s.amp); q=[]
    for i in range(n):
        l=(i-1)%n; rr=(i+1)%n
        x=s.amp[i]+.10*math.sqrt(s.amp[i]*s.amp[l])*math.cos(s.phase[i]-s.phase[l])+ .10*math.sqrt(s.amp[i]*s.amp[rr])*math.cos(s.phase[i]-s.phase[rr])
        if pressure: x*=math.exp(-pressure.get(i,0.0))
        q.append(max(floor,x))
    z=sum(q); return [x/z for x in q]

def step(s,r,pressure=None,plastic=.003):
    p=distribution(s,pressure); i=r.choices(range(len(p)),weights=p)[0]; s.hist.append(i)
    # local experience changes later topology; deliberately weak to avoid collapse
    s.phase[i]+=r.gauss(.06,.08); s.phase[(i+1)%len(p)]+=r.gauss(.02,.05)
    s.amp[i]+=plastic; z=sum(s.amp); s.amp=[x/z for x in s.amp]
    return i

def clone(s): return S(s.amp[:],s.phase[:],s.hist[:])
def run(s,r,steps,pressure=None): return [step(s,r,pressure) for _ in range(steps)]
def counts(xs,n): return [xs.count(i) for i in range(n)]

def one(seed=1,n=16,train=3000,post=3000,target=5,strength=1.2):
    root=make(n,random.Random(seed)); free=clone(root); cap=clone(root)
    # matched random streams: divergence comes from pressure -> different experience -> plasticity
    rf=random.Random(seed+1000); rc=random.Random(seed+1000)
    run(free,rf,train,None); run(cap,rc,train,{target:strength})
    # intervention absent in BOTH branches from here onward
    fp=run(free,rf,post,None); cp=run(cap,rc,post,None)
    fc,cc=counts(fp,n),counts(cp,n)
    return {"seed":seed,"target":target,"free_target":fc[target],"captured_target":cc[target],
            "delta":cc[target]-fc[target],"free_counts":fc,"captured_counts":cc,
            "free_amp":free.amp,"captured_amp":cap.amp}

def batch(start=1,runs=50,**kw):
    out=[one(seed=s,**kw) for s in range(start,start+runs)]
    ds=[x["delta"] for x in out]
    return {"runs":runs,"mean_delta":sum(ds)/len(ds),"captured_lower_fraction":sum(d<0 for d in ds)/len(ds),
            "mean_free_target":sum(x["free_target"] for x in out)/runs,
            "mean_captured_target":sum(x["captured_target"] for x in out)/runs,"results":out}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--runs',type=int,default=50); p.add_argument('--start',type=int,default=1); p.add_argument('--n',type=int,default=16); p.add_argument('--train',type=int,default=3000); p.add_argument('--post',type=int,default=3000); p.add_argument('--target',type=int,default=5); p.add_argument('--strength',type=float,default=1.2)
    a=p.parse_args(); print(json.dumps(batch(a.start,a.runs,n=a.n,train=a.train,post=a.post,target=a.target,strength=a.strength),indent=2))
if __name__=='__main__': main()
