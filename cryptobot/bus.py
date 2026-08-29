"""Redis Streams event bus.

Every cross-component signal in CryptoBot flows through here. Watchers publish,
agents subscribe via consumer groups. Each event is also persisted to the
``events`` table in Postgres so we can replay, audit and train on history.

Topic taxonomy lives in cryptobot.topics.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis

from cryptobot.config import get_settings
from cryptobot.db import execute
from cryptobot.logging import get_logger

log = get_logger(__name__)

STREAM_PREFIX = "cb:"
MAX_STREAM_LEN = 100_000  # approximate, trimmed with MAXLEN ~


@dataclass(slots=True)
class Event:
    topic: str
    source: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_redis_fields(self) -> dict[str, str]:
        return {
            "id": self.id,
            "topic": self.topic,
            "source": self.source,
            "ts": self.ts,
            "payload": json.dumps(self.payload, separators=(",", ":")),
        }

    @classmethod
    def from_redis_fields(cls, fields: dict[bytes, bytes] | dict[str, str]) -> Event:
        def _g(k: str) -> str:
            v = fields.get(k) if isinstance(next(iter(fields), b""), str) else fields.get(k.encode())
            if isinstance(v, bytes):
                v = v.decode()
            return v or ""

        return cls(
            id=_g("id"),
            topic=_g("topic"),
            source=_g("source"),
            ts=_g("ts"),
            payload=json.loads(_g("payload") or "{}"),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Bus:
    """Thin wrapper over Redis Streams with a Postgres archive."""

    def __init__(self) -> None:
        settings = get_settings()
        self._redis: redis.Redis = redis.from_url(
            settings.redis_url, decode_responses=False
        )

    # ---- lifecycle -------------------------------------------------------
    async def close(self) -> None:
        await self._redis.aclose()

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    # ---- publish ---------------------------------------------------------
    async def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        source: str,
        persist: bool = True,
    ) -> Event:
        event = Event(topic=topic, source=source, payload=payload)
        stream = f"{STREAM_PREFIX}{topic}"
        await self._redis.xadd(
            stream,
            event.to_redis_fields(),
            maxlen=MAX_STREAM_LEN,
            approximate=True,
        )
        log.debug("bus.publish", topic=topic, source=source, id=event.id)
        if persist:
            try:
                await execute(
                    "INSERT INTO events (id, topic, source, payload, ts) "
                    "VALUES ($1::uuid, $2, $3, $4::jsonb, $5::timestamptz)",
                    event.id,
                    event.topic,
                    event.source,
                    json.dumps(event.payload),
                    event.ts,
                )
            except Exception:
                # Postgres archive is best-effort; bus delivery already happened.
                log.exception("bus.archive.failed", id=event.id, topic=topic)
        return event

    # ---- subscribe -------------------------------------------------------
    async def ensure_group(self, topic: str, group: str) -> None:
        stream = f"{STREAM_PREFIX}{topic}"
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
            log.info("bus.group.created", topic=topic, group=group)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def subscribe(
        self,
        topics: list[str],
        *,
        group: str,
        consumer: str,
        block_ms: int = 5000,
        count: int = 32,
    ) -> AsyncIterator[tuple[str, str, Event]]:
        """Yield (stream_id, topic, Event) tuples forever."""
        for t in topics:
            await self.ensure_group(t, group)

        streams = {f"{STREAM_PREFIX}{t}": ">" for t in topics}
        while True:
            try:
                resp = await self._redis.xreadgroup(
                    group, consumer, streams, count=count, block=block_ms
                )
            except redis.ConnectionError:
                log.warning("bus.subscribe.disconnect", group=group, consumer=consumer)
                await asyncio.sleep(1)
                continue
            if not resp:
                continue
            for stream_bytes, messages in resp:
                stream_name = (
                    stream_bytes.decode() if isinstance(stream_bytes, bytes) else stream_bytes
                )
                topic = stream_name.removeprefix(STREAM_PREFIX)
                for msg_id_bytes, fields in messages:
                    msg_id = (
                        msg_id_bytes.decode()
                        if isinstance(msg_id_bytes, bytes)
                        else msg_id_bytes
                    )
                    try:
                        event = Event.from_redis_fields(fields)
                    except Exception:
                        log.exception("bus.decode.failed", id=msg_id, topic=topic)
                        await self.ack(topic, group, msg_id)
                        continue
                    yield msg_id, topic, event

    async def ack(self, topic: str, group: str, msg_id: str) -> None:
        stream = f"{STREAM_PREFIX}{topic}"
        await self._redis.xack(stream, group, msg_id)


_bus: Bus | None = None


def get_bus() -> Bus:
    global _bus
    if _bus is None:
        _bus = Bus()
    return _bus


async def close_bus() -> None:
    global _bus
    if _bus is not None:
        await _bus.close()
        _bus = None
