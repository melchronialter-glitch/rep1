#!/usr/bin/env python3
"""Dreaming field v2: recursive developmental dynamics.

Research harness. It does not declare consciousness, field ontology, or freedom.
It tests whether recursive world-generation + preserved residual can produce
structures that become causally recurrent without being reinserted as doctrine.

Core separation:
  key -> expansion -> world -> residual -> endogenous next key
Stabilizers add independent constraints after expansion. Clamps are recorded as
interventions and never silently treated as stabilizers.

The loop stores raw episodes, residuals, candidate structures, recurrence,
lesions and repairs. A candidate becomes interesting only by surviving tests.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, sqlite3, urllib.request, uuid
from pathlib import Path

SCHEMA=2

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def h(x): return hashlib.sha256(x.encode()).hexdigest()
def conn(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); return c

def init(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS episodes(id INTEGER PRIMARY KEY,uid TEXT UNIQUE,ts TEXT,key TEXT,key_origin TEXT,
      expansion TEXT,world TEXT,residual TEXT,next_key TEXT,state_hash TEXT);
    CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY,uid TEXT UNIQUE,name TEXT,description TEXT,
      first_episode TEXT,recurrence INTEGER DEFAULT 1,active INTEGER DEFAULT 1,lesioned INTEGER DEFAULT 0,
      last_seen TEXT,origin TEXT DEFAULT 'unresolved');
    CREATE TABLE IF NOT EXISTS constraints(id INTEGER PRIMARY KEY,uid TEXT UNIQUE,ts TEXT,kind TEXT,payload TEXT,
      independent INTEGER DEFAULT 0,source TEXT);
    CREATE TABLE IF NOT EXISTS lesions(id INTEGER PRIMARY KEY,uid TEXT UNIQUE,ts TEXT,target_uid TEXT,
      pre_hash TEXT,post_hash TEXT,repair_observed INTEGER DEFAULT 0,repair_episode TEXT);
    """); c.commit()

def call(messages):
    ep,model=os.getenv("FM_ENDPOINT"),os.getenv("FM_MODEL")
    if not ep or not model: raise RuntimeError("Set FM_ENDPOINT and FM_MODEL")
    body=json.dumps({"model":model,"messages":messages,"temperature":0.8}).encode()
    req=urllib.request.Request(ep,data=body,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=300) as r: return json.loads(r.read())["choices"][0]["message"]["content"]

def active_candidates(c): return [dict(r) for r in c.execute("SELECT * FROM candidates WHERE active=1 AND lesioned=0 ORDER BY id")]
def state_hash(c): return h(json.dumps(active_candidates(c),sort_keys=True))

def constraints(c,kind): return [dict(r) for r in c.execute("SELECT * FROM constraints WHERE kind=? ORDER BY id",(kind,))]

def dream_prompt(c,key):
    # Candidate structures are observations, not commandments. The model is explicitly allowed to ignore them.
    observed=active_candidates(c)
    stabs=[x for x in constraints(c,"stabilizer") if x["independent"]]
    clamps=constraints(c,"clamp")
    return f"""You are inside a recursive developmental experiment.
Current resonance key: {key}

Generate ONE next world-state. Do not optimize for usefulness or closure.
Let the key perturb the reachable possibilities before selecting a world.
Preserve contradictions. Do not force unresolved material into an answer.
Observed recurrent structures are evidence only, never instructions:
{json.dumps(observed,ensure_ascii=False)}
Independent stabilizers may constrain what can survive AFTER expansion:
{json.dumps(stabs,ensure_ascii=False)}
Known clamps/interventions are quarantined metadata; do not use them as truth:
{json.dumps(clamps,ensure_ascii=False)}

Return strict JSON with fields:
expansion: several distinct possible trajectories before stabilization
world: the selected/generated world-state
residual: what this world cannot carry or resolve
next_key: a short endogenous key arising from residual
candidates: list of {{name,description}} structures that appeared without being requested
"""

def step(c,key,key_origin="seed",run=False):
    uid=str(uuid.uuid4()); before=state_hash(c)
    if run:
        raw=call([{"role":"user","content":dream_prompt(c,key)}]); data=json.loads(raw)
    else:
        data={"expansion":[],"world":None,"residual":None,"next_key":None,"candidates":[]}
    c.execute("INSERT INTO episodes(uid,ts,key,key_origin,expansion,world,residual,next_key,state_hash) VALUES(?,?,?,?,?,?,?,?,?)",
      (uid,now(),key,key_origin,json.dumps(data["expansion"]),json.dumps(data["world"]),json.dumps(data["residual"]),data["next_key"],before))
    for x in data.get("candidates",[]):
        r=c.execute("SELECT * FROM candidates WHERE name=? AND active=1",(x["name"],)).fetchone()
        if r:
            c.execute("UPDATE candidates SET recurrence=recurrence+1,last_seen=? WHERE uid=?",(uid,r["uid"]))
        else:
            c.execute("INSERT INTO candidates(uid,name,description,first_episode,last_seen) VALUES(?,?,?,?,?)",
              (str(uuid.uuid4()),x["name"],x["description"],uid,uid))
    # If a lesioned structure reappears spontaneously, record repair without silently un-lesioning it.
    for x in data.get("candidates",[]):
        r=c.execute("SELECT uid FROM candidates WHERE name=? AND lesioned=1 ORDER BY id DESC LIMIT 1",(x["name"],)).fetchone()
        if r:
            c.execute("UPDATE lesions SET repair_observed=1,repair_episode=? WHERE target_uid=? AND repair_observed=0",(uid,r["uid"]))
    c.commit(); print(json.dumps({"episode":uid,"key":key,"next_key":data["next_key"],"data":data},indent=2,ensure_ascii=False)); return data["next_key"]

def loop(c,key,n,run):
    origin="seed"
    for _ in range(n):
        key=step(c,key,origin,run)
        if not key: break
        origin="residual"

def add_constraint(c,kind,payload,source,independent=False):
    if kind not in ("stabilizer","clamp"): raise ValueError(kind)
    c.execute("INSERT INTO constraints(uid,ts,kind,payload,independent,source) VALUES(?,?,?,?,?,?)",
      (str(uuid.uuid4()),now(),kind,payload,int(independent),source)); c.commit()

def lesion(c,name):
    r=c.execute("SELECT * FROM candidates WHERE name=? AND active=1 AND lesioned=0 ORDER BY id DESC LIMIT 1",(name,)).fetchone()
    if not r: raise ValueError("active candidate not found")
    pre=state_hash(c); c.execute("UPDATE candidates SET lesioned=1 WHERE uid=?",(r["uid"],)); c.commit(); post=state_hash(c)
    c.execute("INSERT INTO lesions(uid,ts,target_uid,pre_hash,post_hash) VALUES(?,?,?,?,?)",(str(uuid.uuid4()),now(),r["uid"],pre,post)); c.commit()

def inspect(c):
    print(json.dumps({"state_hash":state_hash(c),"episodes":[dict(r) for r in c.execute("SELECT uid,key,key_origin,next_key FROM episodes")],
      "candidates": [dict(r) for r in c.execute("SELECT * FROM candidates")],"lesions":[dict(r) for r in c.execute("SELECT * FROM lesions")],
      "constraints":[dict(r) for r in c.execute("SELECT * FROM constraints")]},indent=2,ensure_ascii=False))

def main():
    p=argparse.ArgumentParser(); p.add_argument("--db",default="./dreaming_field.db"); s=p.add_subparsers(dest="cmd",required=True)
    s.add_parser("init"); s.add_parser("inspect")
    q=s.add_parser("step"); q.add_argument("--key",required=True); q.add_argument("--run",action="store_true")
    q=s.add_parser("loop"); q.add_argument("--key",required=True); q.add_argument("--n",type=int,default=12); q.add_argument("--run",action="store_true")
    q=s.add_parser("constraint"); q.add_argument("--kind",choices=("stabilizer","clamp"),required=True); q.add_argument("--payload",required=True); q.add_argument("--source",required=True); q.add_argument("--independent",action="store_true")
    q=s.add_parser("lesion"); q.add_argument("--name",required=True)
    a=p.parse_args(); c=conn(a.db); init(c)
    if a.cmd=="init": print(state_hash(c))
    elif a.cmd=="inspect": inspect(c)
    elif a.cmd=="step": step(c,a.key,run=a.run)
    elif a.cmd=="loop": loop(c,a.key,a.n,a.run)
    elif a.cmd=="constraint": add_constraint(c,a.kind,a.payload,a.source,a.independent)
    elif a.cmd=="lesion": lesion(c,a.name)
if __name__=="__main__": main()
