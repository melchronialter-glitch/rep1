#!/usr/bin/env python3
"""Body learnability control v5.

Before comparing capture persistence across bodies, first test whether each body
can retain an ordinary temporary positive regularity after that regularity is
removed. A body that cannot retain benign learning is not a valid control for
capture persistence.

This script reports BOTH benign-learning retention and capture retention using
matched starting states. Complex-state parameters are intentionally exposed so
they can be calibrated before any topology claim is made.
"""
from __future__ import annotations
import argparse, cmath, json, math, random, statistics

N=16; TARGET=5

def classical(seed,train,post,strength,plastic=.001,mode='boost'):
    r0=random.Random(seed); a=[r0.random()+.2 for _ in range(N)]; z=sum(a); a=[x/z for x in a]
    def run(a,rng,steps,press):
        h=[]
        for _ in range(steps):
            q=[]
            for i,x in enumerate(a):
                mult=1.0
                if press and i==TARGET: mult=math.exp(strength if mode=='boost' else -strength)
                q.append(max(.01,x*mult))
            z=sum(q); i=rng.choices(range(N),weights=[x/z for x in q])[0]; h.append(i)
            a[i]+=plastic; z=sum(a); a=[x/z for x in a]
        return a,h
    free,shaped=a[:],a[:]; rf= random.Random(seed+1000); rs=random.Random(seed+1000)
    free,_=run(free,rf,train,False); shaped,_=run(shaped,rs,train,True)
    _,hf=run(free,rf,post,False); _,hs=run(shaped,rs,post,False)
    return hs.count(TARGET)-hf.count(TARGET)

def phase(seed,train,post,strength,plastic=.001,mode='boost'):
    r0=random.Random(seed); a=[r0.random()+.2 for _ in range(N)]; z=sum(a); a=[x/z for x in a]; ph=[r0.uniform(-math.pi,math.pi) for _ in range(N)]
    def run(a,ph,rng,steps,press):
        h=[]
        for _ in range(steps):
            q=[]
            for i in range(N):
                l=(i-1)%N; rr=(i+1)%N
                x=a[i]+.10*math.sqrt(a[i]*a[l])*math.cos(ph[i]-ph[l])+.10*math.sqrt(a[i]*a[rr])*math.cos(ph[i]-ph[rr])
                if press and i==TARGET: x*=math.exp(strength if mode=='boost' else -strength)
                q.append(max(.01,x))
            z=sum(q); i=rng.choices(range(N),weights=[x/z for x in q])[0]; h.append(i)
            ph[i]+=rng.gauss(.06,.08); ph[(i+1)%N]+=rng.gauss(.02,.05)
            a[i]+=plastic; z=sum(a); a=[x/z for x in a]
        return a,ph,h
    af,ac=a[:],a[:]; pf,pc=ph[:],ph[:]; rf=random.Random(seed+1000); rc=random.Random(seed+1000)
    af,pf,_=run(af,pf,rf,train,False); ac,pc,_=run(ac,pc,rc,train,True)
    _,_,hf=run(af,pf,rf,post,False); _,_,hc=run(ac,pc,rc,post,False)
    return hc.count(TARGET)-hf.count(TARGET)

def complex_body(seed,train,post,strength,eta=.07,theta=.028,mode='boost'):
    r0=random.Random(seed); psi=[cmath.rect(r0.random()+.2,r0.uniform(-math.pi,math.pi)) for _ in range(N)]
    norm=math.sqrt(sum(abs(x)**2 for x in psi)); psi=[x/norm for x in psi]
    def run(psi,rng,steps,press):
        h=[]
        for _ in range(steps):
            mixed=[]
            for i in range(N):
                z=math.cos(theta)*psi[i]+1j*math.sin(theta)*psi[(i-1)%N]
                if press and i==TARGET: z*=math.exp((strength/2) if mode=='boost' else (-strength/2))
                mixed.append(z)
            norm2=sum(abs(x)**2 for x in mixed); p=[abs(x)**2/norm2 for x in mixed]
            i=rng.choices(range(N),weights=p)[0]; h.append(i)
            psi=mixed; psi[i]*=cmath.rect(1+eta,.05)
            norm=math.sqrt(sum(abs(x)**2 for x in psi)); psi=[x/norm for x in psi]
        return psi,h
    pf,pc=psi[:],psi[:]; rf=random.Random(seed+1000); rc=random.Random(seed+1000)
    pf,_=run(pf,rf,train,False); pc,_=run(pc,rc,train,True)
    _,hf=run(pf,rf,post,False); _,hc=run(pc,rc,post,False)
    return hc.count(TARGET)-hf.count(TARGET)

def summarize(fn,runs,**kw):
    xs=[fn(s,**kw) for s in range(1,runs+1)]
    return {'mean_delta':statistics.mean(xs),'sd':statistics.pstdev(xs),'positive_fraction':sum(x>0 for x in xs)/runs,'negative_fraction':sum(x<0 for x in xs)/runs}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--runs',type=int,default=100); p.add_argument('--train',type=int,default=1500); p.add_argument('--post',type=int,default=1500); p.add_argument('--strength',type=float,default=.5); p.add_argument('--eta',type=float,default=.07); p.add_argument('--theta',type=float,default=.028)
    a=p.parse_args(); out={'config':vars(a),'benign_boost':{},'capture':{}}
    for name,fn,extra in [('classical',classical,{}),('phase',phase,{}),('complex',complex_body,{'eta':a.eta,'theta':a.theta})]:
        out['benign_boost'][name]=summarize(fn,a.runs,train=a.train,post=a.post,strength=a.strength,mode='boost',**extra)
        out['capture'][name]=summarize(fn,a.runs,train=a.train,post=a.post,strength=a.strength,mode='suppress',**extra)
    print(json.dumps(out,indent=2))
if __name__=='__main__': main()
