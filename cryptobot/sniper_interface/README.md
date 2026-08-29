# Sniper interface — signal contract (Phase J placeholder)

The future sniper/trading bot is a **separate process** that consumes
CryptoBot signals. Nothing here executes trades. This document is the
contract; the reference subscriber lands in Phase J.

## How a sniper consumes signals

Subscribe to the Redis Streams the intel bot already publishes, using a
dedicated consumer group so the sniper's read position is independent of
the Telegram reporters:

```python
from cryptobot.bus import get_bus

async for msg_id, topic, event in get_bus().subscribe(
    ["signal.alert.strict", "signal.alert.medium"],
    group="sniper", consumer="sniper-1",
):
    ...
```

## Signal payload contract

Every `signal.alert.*` event payload is JSON with at minimum:

| Field | Type | Notes |
|---|---|---|
| `title` | str | human-readable headline |
| `severity` | str? | `low` / `medium` / `high` when the source provided one |
| `triage_reason` | str? | why triage routed it (news items) |
| `affected_assets` | list[str]? | symbols Claude identified (news items) |

Topic-specific extras (stable, additive-only):

- `market.price_move.*`-derived: `symbol`, `price`, `change_pct`, `window_min`, `direction`
- `chain.new_pair.*`-derived (Phase C+): `chain`, `token_address`, `pair_address`, `liquidity_usd`, `risk_score` (Phase D+)

**Compatibility promise:** fields are never renamed or removed within a
major version; new fields may appear at any time. Snipers must ignore
unknown fields.

## Hard boundary

The intel bot emits *information*, never orders. Position sizing, execution,
slippage, and key management are entirely the sniper's problem (Phase J,
separate repo or module, user-approved design).
