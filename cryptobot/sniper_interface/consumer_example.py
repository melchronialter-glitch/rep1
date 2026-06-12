"""Reference consumer for the sniper bot (Phase J — separate project).

This file is the ENTIRE integration surface: the sniper subscribes to the
intel bot's Redis Streams and reads alert payloads. It deliberately imports
nothing from cryptobot — copy it into the sniper project as a starting
point. The intel bot never places orders; the sniper never publishes intel.

Payload contract (stable, additive-only — see README.md in this directory):
new-pair alerts carry chain, token_address, risk_score, risk_reasons,
liquidity_usd, and (once the classifier is trained) ml_rug_probability.

Run standalone to watch the strict + medium streams:

    python -m cryptobot.sniper_interface.consumer_example
"""

from __future__ import annotations

import asyncio
import json

import redis.asyncio as redis

REDIS_URL = "redis://localhost:6379/0"
STREAM_PREFIX = "cb:"
TOPICS = ["signal.alert.strict", "signal.alert.medium"]
GROUP = "sniper"
CONSUMER = "sniper-1"


async def main() -> None:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    for topic in TOPICS:
        try:
            await r.xgroup_create(f"{STREAM_PREFIX}{topic}", GROUP, id="$", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    streams = {f"{STREAM_PREFIX}{t}": ">" for t in TOPICS}
    print(f"listening on {TOPICS} …")
    while True:
        resp = await r.xreadgroup(GROUP, CONSUMER, streams, count=16, block=5000)
        for stream, messages in resp or []:
            topic = stream.removeprefix(STREAM_PREFIX)
            for msg_id, fields in messages:
                payload = json.loads(fields.get("payload") or "{}")
                # ---- sniper decision logic goes here ----
                # Example gate: fresh pair, low risk, real liquidity.
                if (
                    payload.get("token_address")
                    and (payload.get("risk_score") or 100) < 30
                    and (payload.get("liquidity_usd") or 0) >= 50_000
                    and (payload.get("ml_rug_probability") or 0.0) < 0.3
                ):
                    print(f"[CANDIDATE] {topic}: {json.dumps(payload)[:300]}")
                else:
                    print(f"[seen] {topic}: {payload.get('title') or payload.get('token_address')}")
                await r.xack(stream, GROUP, msg_id)


if __name__ == "__main__":
    asyncio.run(main())
