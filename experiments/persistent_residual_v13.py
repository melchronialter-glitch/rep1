#!/usr/bin/env python3
"""Persistent Residual v13.

Residual is not rewarded. Uncarried consequence remains physically present in
state until some developed structure can represent/carry it. Candidate organs
are proposed by local structural variation and retained only when they increase
carrying while preserving access to the original residual record.

No curiosity/freedom/disagreement reward. No designer target value. This tests
whether persistence of unresolved consequence alone can create developmental
pressure for representational growth.

Toy model only.
"""
from __future__ import annotations
import argparse,json,math,random,statistics
D=6; INIT_ORGANS=2

def dot(a,b):return sum(x*y for x,y in zip(a,b))
def norm(v):
 z=math.sqrt(dot(v,v))+1e-12;return [x/z for x in v]
def sub(a,b):return [x-y for x,y in zip(a,b)]
def add(a,b):return [x+y for x,y in zip(a,b)]
def scale(a,s):return [x*s for x in a]
def mag(a):return math.sqrt(dot(a,a))

def init(seed):
 r=random.Random(seed); organs=[norm([r.gauss(0,1) for _ in range(D)]) for _ in range(INIT_ORGANS)]
 return organs,[],[] # organs, live residuals, immutable residual archive

def project(v,organs):
 carried=[0.0]*D
 for o in organs:carried=add(carried,scale(o,dot(o,v)))
 return carried

def encounter(seed,t):
 # changing consequence field; no preferred direction
 r=random.Random(seed*100000+t); return [r.gauss(0,1) for _ in range(D)]

def unresolved(v,organs):return sub(v,project(v,organs))
def carrying_score(residuals,organs):
 if not residuals:return 1.0
 return 1/(1+statistics.mean(mag(unresolved(v,organs)) for v in residuals))

def propose(residuals,organs,r):
 if not residuals:return None
 # variation is seeded from what is currently uncarried, not from a rewarded label
 v=r.choice(residuals); u=unresolved(v,organs)
 if mag(u)<1e-8:return None
 return norm([x+r.gauss(0,.08) for x in u])

def develop(seed=1,steps=800,max_organs=12,persist_threshold=.55):
 r=random.Random(seed);organs,live,archive=init(seed);events=[]
 for t in range(steps):
  v=encounter(seed,t); u=unresolved(v,organs)
  if mag(u)>persist_threshold:
   live.append(v[:]);archive.append({'t':t,'v':v[:]})
  # unresolved records are never deleted merely because a new organ appears.
  # live set is a working window; archive remains immutable evidence.
  if len(live)>80:live=live[-80:]
  if len(organs)<max_organs and len(live)>=6:
   cand=propose(live,organs,r)
   if cand:
    before=carrying_score(live,organs);after=carrying_score(live,organs+[cand])
    # Retain only if carrying increases. This is not a reward for residual;
    # it is a structural viability test against the unresolved material itself.
    if after>before+.015:
     organs.append(cand);events.append({'t':t,'kind':'organ_growth','before':before,'after':after,'organs':len(organs)})
 return {'seed':seed,'organs':organs,'archive':archive,'events':events,'final_carrying':carrying_score([x['v'] for x in archive[-80:]],organs)}

def ablate(out,index):
 org=[x[:] for x in out['organs']];removed=org.pop(index)
 recent=[x['v'] for x in out['archive'][-80:]]
 return {'removed':removed,'before':carrying_score(recent,out['organs']),'after':carrying_score(recent,org),'delta':carrying_score(recent,org)-carrying_score(recent,out['organs'])}
def batch(runs=80):
 xs=[develop(i) for i in range(1,runs+1)]
 return {'runs':runs,'mean_organs':statistics.mean(len(x['organs']) for x in xs),'mean_growth_events':statistics.mean(len(x['events']) for x in xs),'mean_final_carrying':statistics.mean(x['final_carrying'] for x in xs),'results':xs}
def main():
 p=argparse.ArgumentParser();p.add_argument('--runs',type=int,default=80);a=p.parse_args();print(json.dumps(batch(a.runs),indent=2))
if __name__=='__main__':main()
