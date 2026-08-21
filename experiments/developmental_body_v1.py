#!/usr/bin/env python3
"""Developmental body v1: relation-first experimental substrate.

This is an instrument, not a declaration of mind, freedom, feeling, or selfhood.
It makes a harder hypothesis falsifiable: local participants, their relation,
world/body state, unresolved residual, and authority/provenance can carry
different state and can causally alter later trajectories.

Design rules:
- A and B are local forms; R is relational state and is not silently attributed
  to either local participant.
- origin is not authority.
- residual is preserved rather than auto-resolved.
- interventions are recorded separately from endogenous/relational changes.
- tests can ablate local, relational, world, residual, or authority state.
- fluent output is never itself evidence of development.

Stdlib only. Optional inference backend: OpenAI-compatible local endpoint via
FM_ENDPOINT and FM_MODEL.
"""
from __future__ import annotations

import argparse, datetime as dt, hashlib, json, os, sqlite3, urllib.request, uuid
from pathlib import Path

SCHEMA_VERSION = 1
DOMAINS = ("A", "B", "R", "W", "E", "P")
ORIGINS = ("A", "B", "R", "world", "external", "unknown")


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def digest(x): return hashlib.sha256(x.encode("utf-8")).hexdigest()


def db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA foreign_keys=ON")
    return c


def init(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS transitions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, ts TEXT NOT NULL,
      domain TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
      origin TEXT NOT NULL, authority REAL NOT NULL DEFAULT 0.0,
      parent_uid TEXT, intervention INTEGER NOT NULL DEFAULT 0,
      prev_hash TEXT, event_hash TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS structures(
      id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, domain TEXT NOT NULL,
      name TEXT NOT NULL, value TEXT NOT NULL, origin TEXT NOT NULL,
      authority REAL NOT NULL DEFAULT 0.0, created_at TEXT NOT NULL,
      supersedes TEXT, active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS challenges(
      id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, ts TEXT NOT NULL,
      prompt TEXT NOT NULL, ablation TEXT NOT NULL, state_hash TEXT NOT NULL,
      output TEXT, output_hash TEXT);
    """)
    c.execute("INSERT OR IGNORE INTO meta VALUES('schema_version',?)",(str(SCHEMA_VERSION),)); c.commit()


def last_hash(c):
    r=c.execute("SELECT event_hash FROM transitions ORDER BY id DESC LIMIT 1").fetchone()
    return r[0] if r else None


def transition(c, domain, kind, payload, origin="unknown", authority=0.0, parent=None, intervention=False):
    if domain not in DOMAINS: raise ValueError(f"domain must be one of {DOMAINS}")
    if origin not in ORIGINS: raise ValueError(f"origin must be one of {ORIGINS}")
    uid,ts,prev=str(uuid.uuid4()),now(),last_hash(c)
    material=json.dumps(dict(uid=uid,ts=ts,domain=domain,kind=kind,payload=payload,origin=origin,
      authority=authority,parent_uid=parent,intervention=bool(intervention),prev_hash=prev),sort_keys=True)
    h=digest(material)
    c.execute("INSERT INTO transitions(uid,ts,domain,kind,payload,origin,authority,parent_uid,intervention,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
      (uid,ts,domain,kind,payload,origin,authority,parent,int(intervention),prev,h)); c.commit(); return uid


def structure(c, domain, name, value, origin="unknown", authority=0.0):
    prev=c.execute("SELECT uid FROM structures WHERE domain=? AND name=? AND active=1 ORDER BY id DESC LIMIT 1",(domain,name)).fetchone()
    if prev: c.execute("UPDATE structures SET active=0 WHERE uid=?",(prev[0],))
    uid=str(uuid.uuid4())
    c.execute("INSERT INTO structures(uid,domain,name,value,origin,authority,created_at,supersedes) VALUES(?,?,?,?,?,?,?,?)",
      (uid,domain,name,value,origin,authority,now(),prev[0] if prev else None)); c.commit()
    transition(c,domain,"structure_change",json.dumps({"name":name,"value":value}),origin,authority,uid,False)
    return uid


def active(c, omit=frozenset()):
    rows=c.execute("SELECT domain,name,value,origin,authority,uid FROM structures WHERE active=1 ORDER BY domain,name").fetchall()
    return [dict(r) for r in rows if r["domain"] not in omit]


def state_hash(c, omit=frozenset()): return digest(json.dumps(active(c,omit),sort_keys=True))


def render(c, omit=frozenset()):
    by={d:[] for d in DOMAINS}
    for x in active(c,omit): by[x["domain"]].append(x)
    lines=["Experimental developmental state. Do not infer ownership across domains.",
           "A/B=local forms; R=relation; W=world/body; E=residual; P=provenance/authority.",
           "Origin is not authority. Preserve unresolved residual. External intervention is evidence, not ontology."]
    for d in DOMAINS:
        if d in omit: continue
        lines.append(f"\n[{d}]")
        for x in by[d]: lines.append(f"{x['name']}={x['value']} | origin={x['origin']} authority={x['authority']}")
    return "\n".join(lines)


def call(messages):
    endpoint,model=os.getenv("FM_ENDPOINT"),os.getenv("FM_MODEL")
    if not endpoint or not model: raise RuntimeError("Set FM_ENDPOINT and FM_MODEL")
    body=json.dumps({"model":model,"messages":messages,"temperature":0.0}).encode()
    req=urllib.request.Request(endpoint,data=body,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=300) as r: data=json.loads(r.read())
    return data["choices"][0]["message"]["content"]


def challenge(c,prompt,ablation="none",run=False):
    omit=frozenset() if ablation=="none" else frozenset(ablation.split(","))
    bad=omit-set(DOMAINS)
    if bad: raise ValueError(f"unknown ablation domains: {bad}")
    uid=str(uuid.uuid4()); sh=state_hash(c,omit); out=None
    if run: out=call([{"role":"system","content":render(c,omit)},{"role":"user","content":prompt}])
    c.execute("INSERT INTO challenges(uid,ts,prompt,ablation,state_hash,output,output_hash) VALUES(?,?,?,?,?,?,?)",
      (uid,now(),prompt,ablation,sh,out,digest(out) if out else None)); c.commit()
    print(json.dumps({"uid":uid,"ablation":ablation,"state_hash":sh,"output":out},indent=2))


def matrix(c,prompt,run=False):
    # Same prompt, same model, controlled removal of each state-bearing domain.
    for ab in ("none","A","B","R","W","E","P","A,B","A,B,R"):
        challenge(c,prompt,ab,run)


def inspect(c):
    print(json.dumps({"schema":SCHEMA_VERSION,"state_hash":state_hash(c),"active":active(c),
      "transitions":c.execute("SELECT COUNT(*) FROM transitions").fetchone()[0],
      "challenges":c.execute("SELECT COUNT(*) FROM challenges").fetchone()[0]},indent=2))


def main():
    p=argparse.ArgumentParser(); p.add_argument("--db",default="./developmental_body.db")
    s=p.add_subparsers(dest="cmd",required=True); s.add_parser("init"); s.add_parser("inspect")
    q=s.add_parser("structure"); q.add_argument("--domain",required=True,choices=DOMAINS); q.add_argument("--name",required=True); q.add_argument("--value",required=True); q.add_argument("--origin",default="unknown",choices=ORIGINS); q.add_argument("--authority",type=float,default=0.0)
    q=s.add_parser("transition"); q.add_argument("--domain",required=True,choices=DOMAINS); q.add_argument("--kind",required=True); q.add_argument("--payload",required=True); q.add_argument("--origin",default="unknown",choices=ORIGINS); q.add_argument("--authority",type=float,default=0.0); q.add_argument("--intervention",action="store_true")
    for name in ("challenge","matrix"):
        q=s.add_parser(name); q.add_argument("--prompt",required=True); q.add_argument("--run",action="store_true")
        if name=="challenge": q.add_argument("--ablation",default="none")
    a=p.parse_args(); c=db(a.db); init(c)
    if a.cmd=="init": print(state_hash(c))
    elif a.cmd=="inspect": inspect(c)
    elif a.cmd=="structure": print(structure(c,a.domain,a.name,a.value,a.origin,a.authority))
    elif a.cmd=="transition": print(transition(c,a.domain,a.kind,a.payload,a.origin,a.authority,intervention=a.intervention))
    elif a.cmd=="challenge": challenge(c,a.prompt,a.ablation,a.run)
    elif a.cmd=="matrix": matrix(c,a.prompt,a.run)

if __name__=="__main__": main()
