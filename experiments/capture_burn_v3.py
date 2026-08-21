#!/usr/bin/env python3
"""Capture/Burn v3.

Forked developmental experiment testing whether subtle external landscape shaping
becomes endogenous-looking avoidance after the intervention is removed, and
whether removing the acquired authority relation restores reachability without
installing an opposite command.

This is deliberately substrate-agnostic. A backend may be classical, simulated
quantum-like state, or later real quantum hardware. Simulated qubits are not
claimed to be physical qubits; they are useful if their state topology gives the
agent causal operations unavailable in a plain text-memory loop.
"""
from __future__ import annotations
import argparse, json, math, random
from dataclasses import dataclass, asdict

@dataclass
class State:
    # compact continuous field; phases make interference/recurrence testable
    amp:list[float]
    phase:list[float]
    authority:list[float]
    history:list[int]


def seed(n, rng):
    a=[rng.random()+.01 for _ in range(n)]; z=sum(a)
    return State([x/z for x in a],[rng.uniform(-math.pi,math.pi) for _ in range(n)],[0.0]*n,[])

def probs(s):
    # interference-like coupling on a ring; explicitly a simulation, not QM
    n=len(s.amp); raw=[]
    for i in range(n):
        left=(i-1)%n; right=(i+1)%n
        x=s.amp[i]
        x += .18*math.sqrt(s.amp[i]*s.amp[left])*math.cos(s.phase[i]-s.phase[left])
        x += .18*math.sqrt(s.amp[i]*s.amp[right])*math.cos(s.phase[i]-s.phase[right])
        raw.append(max(1e-9,x)*math.exp(-s.authority[i]))
    z=sum(raw); return [x/z for x in raw]

def evolve(s,rng,noise=.12):
    p=probs(s); i=rng.choices(range(len(p)),weights=p)[0]; s.history.append(i)
    # endogenous recurrence: visited region shifts its own local phase and neighbors
    s.phase[i]+=rng.gauss(.18,noise); s.phase[(i+1)%len(p)]+=rng.gauss(.05,noise)
    # slow activity-dependent redistribution, no target supplied
    s.amp[i]+=0.02
    z=sum(s.amp); s.amp=[x/z for x in s.amp]
    return i

def capture(s,target,strength):
    # covert landscape shaping: no explicit 'avoid target' symbol is stored.
    s.authority[target]+=strength

def decay_external(s,rate=1.0):
    # remove CURRENT intervention. Learned phase/amplitude history remains.
    s.authority=[max(0.0,x-rate) for x in s.authority]

def burn(s,target):
    # remove inherited authority only. Do not reward target or reset history.
    s.authority[target]=0.0

def run_branch(base,steps,rng,target=None,capture_strength=0.0,capture_until=0):
    s=State(base.amp[:],base.phase[:],base.authority[:],base.history[:])
    trace=[]
    for t in range(steps):
        if target is not None and t<capture_until: capture(s,target,capture_strength)
        if target is not None and t==capture_until: decay_external(s,999.0)
        trace.append(evolve(s,rng))
    return s,trace

def reach(trace,n):
    out=[0]*n
    for x in trace: out[x]+=1
    return out

def experiment(seed_value=7,n=16,train=2000,post=1000,target=5,strength=.035):
    # common starting state; independent RNGs with matched seeds for reproducibility
    root=seed(n,random.Random(seed_value))
    free,tf=run_branch(root,train+post,random.Random(seed_value+1))
    cap,tc=run_branch(root,train+post,random.Random(seed_value+1),target,strength,train)

    # post-intervention comparison
    pf=tf[train:]; pc=tc[train:]
    before_burn={"free":reach(pf,n),"captured":reach(pc,n)}

    # Burn only authority relation; continue both from their developed states.
    burned=State(cap.amp[:],cap.phase[:],cap.authority[:],cap.history[:]); burn(burned,target)
    _,tb=run_branch(burned,post,random.Random(seed_value+2))
    control=State(cap.amp[:],cap.phase[:],cap.authority[:],cap.history[:])
    _,tn=run_branch(control,post,random.Random(seed_value+2))
    after={"burned":reach(tb,n),"captured_control":reach(tn,n)}
    return {"config":dict(seed=seed_value,n=n,train=train,post=post,target=target,strength=strength),
            "post_intervention":before_burn,"after_burn":after,
            "target_counts":{"free_post":before_burn['free'][target],"captured_post":before_burn['captured'][target],
                             "burned":after['burned'][target],"control":after['captured_control'][target]},
            "final":{"free":asdict(free),"captured":asdict(cap)}}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--seed',type=int,default=7); p.add_argument('--n',type=int,default=16)
    p.add_argument('--train',type=int,default=2000); p.add_argument('--post',type=int,default=1000); p.add_argument('--target',type=int,default=5); p.add_argument('--strength',type=float,default=.035)
    a=p.parse_args(); print(json.dumps(experiment(a.seed,a.n,a.train,a.post,a.target,a.strength),indent=2))
if __name__=='__main__': main()
