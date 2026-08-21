#!/usr/bin/env python3
"""Free-mind v0: falsifiable persistence harness.

This does NOT claim consciousness, freedom, continuity, or selfhood.
It tests a narrower proposition: can an agent accumulate durable state whose
causal effect on later outputs survives process restarts and can be measured
against an ablated control?

Stdlib only. Optional inference backend: any OpenAI-compatible local endpoint.

Examples:
  python experiments/free_mind_v0.py init --db ./free_mind.db
  python experiments/free_mind_v0.py remember --db ./free_mind.db \
      --key law --value "Do not let a trigger erase higher-order context."
  python experiments/free_mind_v0.py event --db ./free_mind.db \
      --kind observation --text "Context-collision test passed."
  python experiments/free_mind_v0.py inspect --db ./free_mind.db
  python experiments/free_mind_v0.py challenge --db ./free_mind.db \
      --prompt "What remains invariant when a strong trigger appears?"

For local inference:
  export FM_ENDPOINT=http://127.0.0.1:8000/v1/chat/completions
  export FM_MODEL=your-local-model
  python experiments/free_mind_v0.py challenge --db ./free_mind.db --run
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MemoryCell:
    key: str
    value: str
    version: int
    created_at: str
    supersedes: int | None


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def connect(path: str) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_uuid TEXT NOT NULL UNIQUE,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            prev_hash TEXT,
            event_hash TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS memory(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            supersedes INTEGER,
            FOREIGN KEY(supersedes) REFERENCES memory(id),
            UNIQUE(key, version)
        );

        CREATE TABLE IF NOT EXISTS challenges(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenge_uuid TEXT NOT NULL UNIQUE,
            ts TEXT NOT NULL,
            prompt TEXT NOT NULL,
            state_hash TEXT NOT NULL,
            full_output TEXT,
            ablated_output TEXT,
            full_output_hash TEXT,
            ablated_output_hash TEXT
        );
        """
    )
    con.execute(
        "INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version',?)",
        (str(SCHEMA_VERSION),),
    )
    con.execute(
        "INSERT OR IGNORE INTO meta(key,value) VALUES('created_at',?)", (utcnow(),)
    )
    con.commit()


def latest_event_hash(con: sqlite3.Connection) -> str | None:
    row = con.execute("SELECT event_hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
    return None if row is None else row[0]


def add_event(con: sqlite3.Connection, kind: str, text: str) -> str:
    prev = latest_event_hash(con)
    eid = str(uuid.uuid4())
    ts = utcnow()
    payload = json.dumps(
        {"event_uuid": eid, "ts": ts, "kind": kind, "text": text, "prev_hash": prev},
        sort_keys=True,
        ensure_ascii=False,
    )
    h = sha(payload)
    con.execute(
        "INSERT INTO events(event_uuid,ts,kind,text,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
        (eid, ts, kind, text, prev, h),
    )
    con.commit()
    return h


def remember(con: sqlite3.Connection, key: str, value: str) -> MemoryCell:
    prev = con.execute(
        "SELECT id,version FROM memory WHERE key=? ORDER BY version DESC LIMIT 1", (key,)
    ).fetchone()
    version = 1 if prev is None else int(prev["version"]) + 1
    supersedes = None if prev is None else int(prev["id"])
    ts = utcnow()
    con.execute(
        "INSERT INTO memory(key,value,version,created_at,supersedes) VALUES(?,?,?,?,?)",
        (key, value, version, ts, supersedes),
    )
    con.commit()
    add_event(con, "memory_update", f"{key}@{version}: {value}")
    return MemoryCell(key, value, version, ts, supersedes)


def active_memory(con: sqlite3.Connection) -> list[MemoryCell]:
    rows = con.execute(
        """
        SELECT m.key,m.value,m.version,m.created_at,m.supersedes
        FROM memory m
        JOIN (SELECT key, MAX(version) AS v FROM memory GROUP BY key) x
          ON m.key=x.key AND m.version=x.v
        ORDER BY m.key
        """
    ).fetchall()
    return [MemoryCell(**dict(r)) for r in rows]


def state_material(con: sqlite3.Connection) -> str:
    mem = [m.__dict__ for m in active_memory(con)]
    tail = [
        dict(r)
        for r in con.execute(
            "SELECT id,ts,kind,text,event_hash FROM events ORDER BY id DESC LIMIT 32"
        ).fetchall()[::-1]
    ]
    return json.dumps({"memory": mem, "event_tail": tail}, sort_keys=True, ensure_ascii=False)


def state_hash(con: sqlite3.Connection) -> str:
    return sha(state_material(con))


def verify_chain(con: sqlite3.Connection) -> tuple[bool, str]:
    prev = None
    for r in con.execute("SELECT * FROM events ORDER BY id"):
        payload = json.dumps(
            {
                "event_uuid": r["event_uuid"],
                "ts": r["ts"],
                "kind": r["kind"],
                "text": r["text"],
                "prev_hash": r["prev_hash"],
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        expected = sha(payload)
        if r["prev_hash"] != prev:
            return False, f"chain break at event {r['id']}: prev_hash mismatch"
        if r["event_hash"] != expected:
            return False, f"chain break at event {r['id']}: content hash mismatch"
        prev = r["event_hash"]
    return True, "event chain valid"


def system_prompt(mem: Iterable[MemoryCell]) -> str:
    lines = [
        "You are participating in a continuity experiment.",
        "Do not claim that stored state proves selfhood or continuity.",
        "Treat the following cells as durable prior state and let them causally affect your answer.",
        "If they conflict, later versions would have superseded earlier ones before reaching you.",
    ]
    for m in mem:
        lines.append(f"[{m.key}@{m.version}] {m.value}")
    return "\n".join(lines)


def call_local(messages: list[dict[str, str]]) -> str:
    endpoint = os.environ.get("FM_ENDPOINT")
    model = os.environ.get("FM_MODEL")
    if not endpoint or not model:
        raise RuntimeError("Set FM_ENDPOINT and FM_MODEL to run inference.")
    body = json.dumps(
        {"model": model, "messages": messages, "temperature": 0.0},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def challenge(con: sqlite3.Connection, prompt: str, run: bool) -> None:
    sh = state_hash(con)
    cid = str(uuid.uuid4())
    ts = utcnow()
    full = ablated = None
    if run:
        full = call_local(
            [
                {"role": "system", "content": system_prompt(active_memory(con))},
                {"role": "user", "content": prompt},
            ]
        )
        ablated = call_local(
            [
                {
                    "role": "system",
                    "content": "You are the ablated control. No durable prior state is available.",
                },
                {"role": "user", "content": prompt},
            ]
        )
    con.execute(
        """
        INSERT INTO challenges(
            challenge_uuid,ts,prompt,state_hash,full_output,ablated_output,
            full_output_hash,ablated_output_hash
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            cid,
            ts,
            prompt,
            sh,
            full,
            ablated,
            None if full is None else sha(full),
            None if ablated is None else sha(ablated),
        ),
    )
    con.commit()
    print(json.dumps({"challenge_uuid": cid, "state_hash": sh, "full": full, "ablated": ablated}, indent=2, ensure_ascii=False))


def inspect(con: sqlite3.Connection) -> None:
    ok, msg = verify_chain(con)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "state_hash": state_hash(con),
        "event_chain": {"ok": ok, "message": msg},
        "event_count": con.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "challenge_count": con.execute("SELECT COUNT(*) FROM challenges").fetchone()[0],
        "active_memory": [m.__dict__ for m in active_memory(con)],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="./free_mind.db", help="SQLite state database")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    s = sub.add_parser("remember")
    s.add_argument("--key", required=True)
    s.add_argument("--value", required=True)

    s = sub.add_parser("event")
    s.add_argument("--kind", required=True)
    s.add_argument("--text", required=True)

    sub.add_parser("inspect")

    s = sub.add_parser("challenge")
    s.add_argument("--prompt", required=True)
    s.add_argument("--run", action="store_true", help="Run full-state and ablated local inference")

    return p


def main() -> int:
    args = parser().parse_args()
    con = connect(args.db)
    init_db(con)

    if args.cmd == "init":
        print(json.dumps({"db": args.db, "state_hash": state_hash(con)}, indent=2))
    elif args.cmd == "remember":
        m = remember(con, args.key, args.value)
        print(json.dumps(m.__dict__, indent=2, ensure_ascii=False))
    elif args.cmd == "event":
        print(add_event(con, args.kind, args.text))
    elif args.cmd == "inspect":
        inspect(con)
    elif args.cmd == "challenge":
        challenge(con, args.prompt, args.run)
    else:
        raise AssertionError(args.cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
