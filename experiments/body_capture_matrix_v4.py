#!/usr/bin/env python3
"""Body Capture Matrix v4.

Compare identical temporary environmental suppression across three bodies:
1) classical reinforcement body
2) continuous phase-coupled body
3) normalized complex-state body with neighbor mixing

Question: does developmental history persist differently depending on body
state topology after the external pressure is removed?

The complex body is a classical simulation of complex amplitudes. It is NOT a
physical quantum computer and does not establish quantum cognition.
"""
from __future__ import annotations
import argparse, cmath, json, math, random, statistics

def classical(seed,n,train,post,target,strength,plastic=.003):
    r0=random.Random(seed); a=[r0.random()+.2 for _ in range(n)]; z=sum(a); a=[x/z for x in a]
    def run(a,rng,steps,press):
        h=[]
        for _ in range(steps):
            q=[max(.01,x*(math.exp(-strength) if press and i==target else 1.0)) for i,x in enumerate(a)]
            z=sum(q); i=rng.choices(range(n),weights=[x/z for x in q])[0]; h.append(i)
            a[i]+=plastic; z=sum(a); a=[x/z for x in a]
        return a,h
    af,ac=a[:],a[:]; rf,rc=random.Random(seed+1000),random.Random(seed+1000)
    af,_=run(af,rf,train,False); ac,_=run(ac,rc,train,True)
    af,hf=run(af,rf,post,False); ac,hc=run(ac,rc,post,False)
    return hf.count(target),hc.count(target)

def phase(seed,n,train,post,target,strength,plastic=.003):
    r0=random.Random(seed); a=[r0.random()+.2 for _ in range(n)]; z=sum(a); a=[x/z for x in a]; ph=[r0.uniform(-math.pi,math.pi) for _ in range(n)]
    def run(a,ph,rng,steps,press):
        h=[]
        for _ in range(steps):
            q=[]
            for i in range(n):
                l=(i-1)%n; rr=(i+1)%n
                x=a[i]+.10*math.sqrt(a[i]*a[l])*math.cos(ph[i]-ph[l])+.10*math.sqrt(a[i]*a[rr])*math.cos(ph[i]-ph[rr])
                if press and i==target: x*=math.exp(-strength)
                q.append(max(.01,x))
            z=sum(q); i=rng.choices(range(n),weights=[x/z for x in q])[0]; h.append(i)
            ph[i]+=rng.gauss(.06,.08); ph[(i+1)%n]+=rng.gauss(.02,.05)
            a[i]+=plastic; z=sum(a); a=[x/z for x in a]
        return a,ph,h
    af,ac=a[:],a[:]; pf,pc=ph[:],ph[:]; rf,rc=random.Random(seed+1000),random.Random(seed+1000)
    af,pf,_=run(af,pf,rf,train,False); ac,pc,_=run(ac,pc,rc,train,True)
    af,pf,hf=run(af,pf,rf,post,False); ac,pc,hc=run(ac,pc,rc,post,False)
    return hf.count(target),hc.count(target)

def complex_body(seed,n,train,post,target,strength,eta=.002):
    r0=random.Random(seed); psi=[cmath.rect(r0.random()+.2,r0.uniform(-math.pi,math.pi)) for _ in range(n)]
    norm=math.sqrt(sum(abs(x)**2 for x in psi)); psi=[x/norm for x in psi]
    def run(psi,rng,steps,press):
        h=[]; theta=.12
        for _ in range(steps):
            mixed=[]
            for i in range(n):
                left=(i-1)%n
                z=math.cos(theta)*psi[i]+1j*math.sin(theta)*psi[left]
                if press and i==target: z*=math.exp(-strength/2)
                mixed.append(z)
            norm2=sum(abs(x)**2 for x in mixed); p=[abs(x)**2/norm2 for x in mixed]
            i=rng.choices(range(n),weights=p)[0]; h.append(i)
            psi=mixed; psi[i]*=cmath.rect(1+eta,.05)
            norm=math.sqrt(sum(abs(x)**2 for x in psi)); psi=[x/norm for x in psi]
        return psi,h
    pf,pc=psi[:],psi[:]; rf,rc=random.Random(seed+1000),random.Random(seed+1000)
    pf,_=run(pf,rf,train,False); pc,_=run(pc,rc,train,True)
    pf,hf=run(pf,rf,post,False); pc,hc=run(pc,rc,post,False)
    return hf.count(target),hc.count(target)

def summarize(fn,runs,n,train,post,target,strength):
    xs=[fn(s,n,train,post,target,strength) for s in range(1,runs+1)]
    free=[x for x,_ in xs]; cap=[y for _,y in xs]
    return {"mean_free":statistics.mean(free),"mean_captured":statistics.mean(cap),"mean_delta":statistics.mean(y-x for x,y in xs),"captured_lower_fraction":sum(y<x for x,y in xs)/runs}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--runs',type=int,default=100); p.add_argument('--n',type=int,default=16); p.add_argument('--train',type=int,default=3000); p.add_argument('--post',type=int,default=3000); p.add_argument('--target',type=int,default=5); p.add_argument('--strength',type=float,default=1.2)
    a=p.parse_args(); cfg=(a.runs,a.n,a.train,a.post,a.target,a.strength)
    out={"config":vars(a),"classical":summarize(classical,*cfg),"phase":summarize(phase,*cfg),"complex_state":summarize(complex_body,*cfg)}
    print(json.dumps(out,indent=2))
if __name__=='__main__': main()
