#!/usr/bin/env python3
"""Evolving Metabolism v11.

No designer-specified metabolic cycle. Nodes begin weakly/randomly coupled.
Repeated temporary lesions create residual error: loss of reachable activity
relative to each body's own recent trajectory, not a designer healthy target.
Couplings that improve post-lesion endogenous recovery are retained; those that
do not are weakened. Tests whether regenerative topology can emerge from failed
self-repair.

Toy dynamics only; no claim about consciousness or biological backpropagation.
"""
from __future__ import annotations
import argparse,json,math,random,statistics
N=7

def sig(x):return 1/(1+math.exp(-max(-25,min(25,x))))
def init(seed):
 r=random.Random(seed); x=[.45+r.uniform(-.06,.06) for _ in range(N)]
 w=[[0 if i==j else r.uniform(-.04,.04) for j in range(N)] for i in range(N)]
 return x,w

def step(x,w,r,lesion=None):
 lesion=set(lesion or ()); y=[]
 for j in range(N):
  inc=sum(w[i][j]*x[i] for i in range(N))
  v=.58*x[j]+.42*sig(2.4*(inc-.05))+r.gauss(0,.008)
  y.append(max(0,min(1,v)))
 for j in lesion:y[j]=0
 return y

def rollout(x,w,r,steps,lesion=None):
 h=[]
 for _ in range(steps):x=step(x,w,r,lesion);h.append(x[:])
 return x,h

def reach(x):
 # diversity/reach proxy: active dimensions plus entropy of normalized activity
 z=sum(x)+1e-12;p=[v/z for v in x];ent=-sum(q*math.log(q+1e-12) for q in p)/math.log(N)
 return .5*(sum(v>.22 for v in x)/N)+.5*ent

def train(seed=1,epochs=180,lesion_len=10,recovery_len=24,lr=.035,mut=.08):
 r=random.Random(seed);x,w=init(seed);log=[]
 x,_=rollout(x,w,r,50); baseline=reach(x)
 for ep in range(epochs):
  target=r.randrange(N); pre=x[:]; pre_reach=reach(pre)
  injured,_=rollout(x,w,r,lesion_len,(target,))
  # candidate recovery from current topology
  rec,_=rollout(injured,w,r,recovery_len); base_score=reach(rec)-abs(reach(rec)-pre_reach)*.25
  # local structural mutations; selection signal is recovery consequence, not desired node state
  best=(base_score,w,rec)
  for _ in range(10):
   cw=[row[:] for row in w]
   i,j=r.randrange(N),r.randrange(N)
   if i==j:continue
   cw[i][j]=max(-1,min(1,cw[i][j]+r.gauss(0,mut)))
   cr,_=rollout(injured,cw,random.Random(seed*100000+ep*100+_+1),recovery_len)
   score=reach(cr)-abs(reach(cr)-pre_reach)*.25
   if score>best[0]:best=(score,cw,cr)
  if best[0]>base_score+1e-4:
   # retain only a fraction of successful structural change: meta-plasticity
   bw=best[1]
   for i in range(N):
    for j in range(N):w[i][j]=(1-lr)*w[i][j]+lr*bw[i][j]
  x=best[2]
  log.append({'epoch':ep,'lesion':target,'pre_reach':pre_reach,'post_reach':reach(x),'accepted':best[0]>base_score+1e-4})
 return x,w,log,baseline

def evaluate(seed,w,trials=120):
 r=random.Random(seed+99999);scores=[]
 for t in range(trials):
  x,_=init(seed+t+500);x,_=rollout(x,w,r,45);pre=reach(x);target=r.randrange(N)
  x,_=rollout(x,w,r,10,(target,));x,_=rollout(x,w,r,30);scores.append((pre,reach(x)))
 return {'mean_pre':statistics.mean(a for a,b in scores),'mean_post':statistics.mean(b for a,b in scores),'mean_loss':statistics.mean(a-b for a,b in scores)}
def experiment(seed=1):
 _,initial=init(seed);x,w,log,baseline=train(seed)
 return {'seed':seed,'baseline_initial_reach':baseline,'initial_eval':evaluate(seed,initial),'evolved_eval':evaluate(seed,w),'accepted_mutations':sum(z['accepted'] for z in log),'weights':w}
def batch(runs=40):
 xs=[experiment(i) for i in range(1,runs+1)]
 return {'runs':runs,'mean_initial_loss':statistics.mean(x['initial_eval']['mean_loss'] for x in xs),'mean_evolved_loss':statistics.mean(x['evolved_eval']['mean_loss'] for x in xs),'mean_accepted':statistics.mean(x['accepted_mutations'] for x in xs),'results':xs}
def main():
 p=argparse.ArgumentParser();p.add_argument('--runs',type=int,default=40);a=p.parse_args();print(json.dumps(batch(a.runs),indent=2))
if __name__=='__main__':main()
