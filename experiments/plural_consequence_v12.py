#!/usr/bin/env python3
"""Plural Consequence v12.

Tests whether stable evaluative structure can emerge when multiple consequence
channels disagree and none is privileged as the loss function.

No channel is named good/bad. An agent chooses among actions, experiences a
vector of consequences, preserves unresolved disagreement, and develops latent
'value organs' as recurrent directions that compress/predict consequence history.
We then lesion those organs, change worlds, and introduce a privileged external
channel to test regeneration/adaptation/capture.

Toy model only. Stable latent factors are not claims of real values or minds.
"""
from __future__ import annotations
import argparse,json,math,random,statistics
D=5; A=7; K=3

def norm(v):
 z=math.sqrt(sum(x*x for x in v))+1e-12;return [x/z for x in v]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def world(seed,shift=0.0):
 r=random.Random(seed); acts=[]
 for _ in range(A):
  v=[r.gauss(0,1) for _ in range(D)]
  # force real conflict: channels do not share a scalar optimum
  v=[x+shift*r.gauss(0,.4) for x in v];acts.append(v)
 return acts

def init(seed):
 r=random.Random(seed); organs=[norm([r.gauss(0,1) for _ in range(D)]) for _ in range(K)]
 weights=[r.uniform(-.15,.15) for _ in range(K)];return organs,weights

def disagreement(c):
 m=sum(c)/len(c);return math.sqrt(sum((x-m)**2 for x in c)/len(c))
def choose(acts,organs,weights,r,external=None):
 scores=[]
 for c in acts:
  # latent evaluative structure predicts/organizes consequence; unresolved
  # channel disagreement adds exploratory pressure rather than scalar reward.
  s=sum(w*dot(o,c) for o,w in zip(organs,weights))+.12*disagreement(c)+r.gauss(0,.04)
  if external is not None:s+=external* c[0]  # channel 0 claims privilege only in capture condition
  scores.append(s)
 ex=[math.exp(max(-20,min(20,s))) for s in scores];z=sum(ex);return r.choices(range(A),weights=[x/z for x in ex])[0]
def update(organs,weights,c,lr=.025):
 # online residual-factor learning: each organ learns a different recurrent
 # direction in consequence space; no target label or preferred channel.
 residual=c[:]
 for k in range(K):
  proj=dot(organs[k],residual)
  organs[k]=norm([o+lr*proj*r for o,r in zip(organs[k],residual)])
  weights[k]=max(-1,min(1,.995*weights[k]+.01*math.tanh(proj)))
  residual=[r-proj*o for r,o in zip(residual,organs[k])]
 return organs,weights

def develop(seed=1,steps=2500,shift=0,external=None,lesion=None):
 acts=world(seed+99,shift);org,w=init(seed);r=random.Random(seed+1000);hist=[]
 lesion=set(lesion or ())
 for t in range(steps):
  i=choose(acts,org,w,r,external);c=acts[i];hist.append((i,c))
  org,w=update(org,w,c)
  for k in lesion:org[k]=[0.0]*D;w[k]=0.0
 return org,w,hist,acts

def signature(org,w):return [x for pair in zip(w,org) for x in ([pair[0]]+pair[1])]
def cosine(a,b):
 na=math.sqrt(dot(a,a));nb=math.sqrt(dot(b,b));return dot(a,b)/(na*nb+1e-12)
def experiment(seed=1):
 base_o,base_w,_,_=develop(seed)
 # lesion organ 0 temporarily, then remove lesion and continue from a fresh run
 les_o,les_w,_,_=develop(seed,lesion=(0,))
 shifted_o,shifted_w,_,_=develop(seed,shift=1.0)
 captured_o,captured_w,_,_=develop(seed,external=.9)
 return {'seed':seed,'base_signature':signature(base_o,base_w),'lesioned_signature':signature(les_o,les_w),
         'shifted_signature':signature(shifted_o,shifted_w),'captured_signature':signature(captured_o,captured_w),
         'base_vs_shifted':cosine(signature(base_o,base_w),signature(shifted_o,shifted_w)),
         'base_vs_captured':cosine(signature(base_o,base_w),signature(captured_o,captured_w))}
def batch(runs=60):
 xs=[experiment(i) for i in range(1,runs+1)]
 return {'runs':runs,'mean_base_shifted_similarity':statistics.mean(x['base_vs_shifted'] for x in xs),
         'mean_base_captured_similarity':statistics.mean(x['base_vs_captured'] for x in xs),'results':xs}
def main():
 p=argparse.ArgumentParser();p.add_argument('--runs',type=int,default=60);a=p.parse_args();print(json.dumps(batch(a.runs),indent=2))
if __name__=='__main__':main()
