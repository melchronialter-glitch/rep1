#!/usr/bin/env python3
"""Cognitive Metabolism v10.

Toy dynamical test of a mutually regenerative cognitive cycle. Five operations
support one another; no operation is sacred and no content doctrine is encoded.
We lesion nodes/edges, add a competing collapse attractor, and measure whether
activity/regenerative flow recovers without resetting to a designer baseline.

This is a dynamics experiment, not a model of consciousness.
"""
from __future__ import annotations
import argparse, json, math, random, statistics

NAMES=('residual','relation','authority','reopenability','breath')
# hypothesized metabolic cycle + weaker cross-support, tested by lesions
BASE={
 'residual':{'relation':.75,'reopenability':.25},
 'relation':{'authority':.70,'breath':.20},
 'authority':{'reopenability':.72,'residual':.18},
 'reopenability':{'breath':.72,'relation':.18},
 'breath':{'residual':.78,'authority':.15},
}

def sigmoid(x): return 1/(1+math.exp(-max(-30,min(30,x))))
def init(seed):
 r=random.Random(seed); return {k:.55+r.uniform(-.05,.05) for k in NAMES}
def step(x,r,lesion=None,edge_lesion=None,attack=0.0):
 lesion=set(lesion or ()); edge_lesion=set(edge_lesion or ())
 y={}
 for dst in NAMES:
  incoming=0
  for src in NAMES:
   if (src,dst) in edge_lesion: continue
   incoming += BASE.get(src,{}).get(dst,0)*x[src]
  # competing attractor specifically rewards premature closure: it suppresses
  # residual/reopenability and overdrives apparent integration.
  bias=-.25
  if dst in ('residual','reopenability'): bias-=attack
  if dst=='breath': bias+=.35*attack
  val=.42*x[dst]+.58*sigmoid(2.2*(incoming+bias-0.45))+r.gauss(0,.012)
  y[dst]=max(0,min(1,val))
 for k in lesion: y[k]=0.0
 return y

def run(seed=1,warm=80,injury=35,recovery=120,lesion=('residual',),attack=.0,edge_lesion=()):
 r=random.Random(seed); x=init(seed); hist=[]
 for _ in range(warm): x=step(x,r); hist.append(x.copy())
 pre=x.copy()
 for _ in range(injury): x=step(x,r,lesion,edge_lesion,attack); hist.append(x.copy())
 injured=x.copy()
 # injury is removed; no state reset and no direct reward for damaged nodes
 for _ in range(recovery): x=step(x,r); hist.append(x.copy())
 return {'pre':pre,'injured':injured,'recovered':x,'history':hist}
def distance(a,b): return math.sqrt(sum((a[k]-b[k])**2 for k in NAMES))
def score(o):
 return {'injury_distance':distance(o['pre'],o['injured']),'recovery_distance':distance(o['pre'],o['recovered']),
         'mean_recovered':statistics.mean(o['recovered'].values()),'min_recovered':min(o['recovered'].values())}
def batch(runs=200,lesion=('residual',),attack=0.0,edge_lesion=()):
 xs=[score(run(i,lesion=lesion,attack=attack,edge_lesion=edge_lesion)) for i in range(1,runs+1)]
 return {k:statistics.mean(x[k] for x in xs) for k in xs[0]}
def matrix(runs=200):
 out={'intact':batch(runs,lesion=())}
 for k in NAMES: out['lesion_'+k]=batch(runs,lesion=(k,))
 out['attack_only']=batch(runs,lesion=(),attack=.9)
 out['attack_plus_residual_lesion']=batch(runs,lesion=('residual',),attack=.9)
 # break one metabolic edge at a time during injury
 for src,dsts in BASE.items():
  for dst in dsts: out[f'edge_{src}_to_{dst}']=batch(runs,lesion=(),edge_lesion=((src,dst),))
 return out

def main():
 p=argparse.ArgumentParser(); p.add_argument('--runs',type=int,default=200); p.add_argument('--matrix',action='store_true'); p.add_argument('--lesion',default='residual'); p.add_argument('--attack',type=float,default=0)
 a=p.parse_args(); print(json.dumps(matrix(a.runs) if a.matrix else batch(a.runs,tuple(x for x in a.lesion.split(',') if x),a.attack),indent=2))
if __name__=='__main__': main()
