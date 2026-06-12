from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from cryptobot.bus import get_bus
from cryptobot.config import get_settings
from cryptobot.logging import get_logger
from cryptobot.topics import SIGNAL_ALERT_FIREHOSE, SIGNAL_ALERT_MEDIUM, SOCIAL_DEV_ACTIVITY

log = get_logger(__name__)

_GITHUB_COMMITS_URL = "https://api.github.com/repos/{owner}/{repo}/commits"
_POLL_INTERVAL = 6 * 3600
_REDIS_COMMIT_KEY = "cb:dev_activity:{owner}:{repo}:daily_counts"
_DAILY_COUNT_TTL = 8 * 86400  # store 8 days worth


def _iso_since(hours_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _fetch_commits(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    since_iso: str,
    token: str,
) -> list[dict[str, Any]]:
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = _GITHUB_COMMITS_URL.format(owner=owner, repo=repo)
    commits: list[dict[str, Any]] = []
    page = 1
    while True:
        try:
            resp = await client.get(
                url,
                headers=headers,
                params={"since": since_iso, "per_page": 100, "page": page},
                timeout=20,
            )
            resp.raise_for_status()
            page_data = resp.json()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("dev_activity.github.error", repo=f"{owner}/{repo}", error=str(exc))
            break

        if not isinstance(page_data, list) or not page_data:
            break
        commits.extend(page_data)
        if len(page_data) < 100:
            break
        page += 1

    return commits


async def _get_7day_average(redis: Any, owner: str, repo: str) -> float:
    key = _REDIS_COMMIT_KEY.format(owner=owner, repo=repo)
    try:
        raw = await redis.lrange(key, 0, 6)
        if not raw:
            return 0.0
        values = [float(v.decode() if isinstance(v, bytes) else v) for v in raw]
        return sum(values) / len(values)
    except Exception as exc:
        log.warning("dev_activity.redis.avg_error", error=str(exc))
        return 0.0


async def _store_daily_count(redis: Any, owner: str, repo: str, count: int) -> None:
    key = _REDIS_COMMIT_KEY.format(owner=owner, repo=repo)
    try:
        await redis.lpush(key, str(count))
        await redis.ltrim(key, 0, 7)
        await redis.expire(key, _DAILY_COUNT_TTL)
    except Exception as exc:
        log.warning("dev_activity.redis.store_error", error=str(exc))


async def _poll_repo(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    token: str,
    bus: Any,
    redis: Any,
) -> None:
    since_24h = _iso_since(24)
    commits = await _fetch_commits(client, owner, repo, since_24h, token)

    count_24h = len(commits)
    authors = list({
        c.get("commit", {}).get("author", {}).get("name", "")
        for c in commits
        if c.get("commit", {}).get("author", {}).get("name")
    })

    avg_7day = await _get_7day_average(redis, owner, repo)
    await _store_daily_count(redis, owner, repo, count_24h)

    payload: dict[str, Any] = {
        "repo": f"{owner}/{repo}",
        "owner": owner,
        "name": repo,
        "commits_24h": count_24h,
        "authors": authors[:20],
        "avg_7day_daily": round(avg_7day, 1),
    }

    signal_topic: str | None = None

    if avg_7day > 0:
        change_pct = ((count_24h - avg_7day) / avg_7day) * 100
        payload["change_pct_vs_7day"] = round(change_pct, 1)

        if change_pct <= -80:
            signal_topic = SIGNAL_ALERT_FIREHOSE
            payload["signal_reason"] = "dead_project_drop"
            log.info(
                "dev_activity.drop.detected",
                repo=f"{owner}/{repo}",
                count_24h=count_24h,
                avg_7day=avg_7day,
                change_pct=round(change_pct, 1),
            )
        elif change_pct >= 200:
            signal_topic = SIGNAL_ALERT_MEDIUM
            payload["signal_reason"] = "activity_spike"
            log.info(
                "dev_activity.spike.detected",
                repo=f"{owner}/{repo}",
                count_24h=count_24h,
                avg_7day=avg_7day,
                change_pct=round(change_pct, 1),
            )
    else:
        payload["change_pct_vs_7day"] = None

    try:
        bus.publish(SOCIAL_DEV_ACTIVITY, payload, source="dev_activity")
        if signal_topic:
            bus.publish(signal_topic, payload, source="dev_activity")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("dev_activity.publish.error", repo=f"{owner}/{repo}", error=str(exc))


async def run_dev_activity(stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    repos = settings.github_repo_list
    if not repos:
        log.info("dev_activity.disabled", reason="GITHUB_TRACKED_REPOS not set")
        return

    log.info("dev_activity.started", repos=repos)
    bus = get_bus()
    redis = bus._redis

    async with httpx.AsyncClient() as client:
        while not (stop_event and stop_event.is_set()):
            for repo_str in repos:
                parts = repo_str.strip().split("/")
                if len(parts) != 2:
                    log.warning("dev_activity.bad_repo", value=repo_str)
                    continue
                owner, repo = parts
                try:
                    await _poll_repo(client, owner, repo, settings.github_token, bus, redis)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("dev_activity.poll.error", repo=repo_str, error=str(exc))

            try:
                await asyncio.sleep(_POLL_INTERVAL)
            except asyncio.CancelledError:
                raise

    log.info("dev_activity.stopped")
