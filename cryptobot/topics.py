"""Canonical event topic names. Importing constants > hardcoding strings."""

from __future__ import annotations

# ---- Chain ----
CHAIN_NEW_PAIR = "chain.new_pair"          # + .{sol|eth|bsc|base|arb}
CHAIN_WHALE_MOVE = "chain.whale_move"
CHAIN_LP_EVENT = "chain.lp_event"
CHAIN_LARGE_TRANSFER = "chain.large_transfer"
CHAIN_CONTRACT_DEPLOYED = "chain.contract_deployed"

# ---- Social ----
SOCIAL_TG_MESSAGE = "social.tg.message"
SOCIAL_TG_CALL = "social.tg.call"
SOCIAL_X_TWEET = "social.x.tweet"
SOCIAL_X_TRENDING = "social.x.trending"
SOCIAL_DISCORD_MESSAGE = "social.discord.message"
SOCIAL_REDDIT_POST = "social.reddit.post"

# ---- News ----
NEWS_CRYPTO = "news.crypto"
NEWS_MACRO = "news.macro"
NEWS_MACRO_HIGH_IMPACT = "news.macro.high_impact"

# ---- Market ----
MARKET_PRICE_MOVE = "market.price_move"    # + .{symbol}
MARKET_FUNDING_ANOMALY = "market.funding_anomaly"
MARKET_LIQUIDATION_CLUSTER = "market.liquidation_cluster"
MARKET_VOLUME_SPIKE = "market.volume_spike"

# ---- Signals (outbound alerts) ----
SIGNAL_ALERT_STRICT = "signal.alert.strict"
SIGNAL_ALERT_MEDIUM = "signal.alert.medium"
SIGNAL_ALERT_FIREHOSE = "signal.alert.firehose"
SIGNAL_ALERT_MACRO = "signal.alert.macro"
SIGNAL_ALERT_DM = "signal.alert.dm"

# ---- Intelligence / user-driven ----
INTEL_USER_QUERY = "intel.user_query"
INTEL_COIN_LABELED = "intel.coin_labeled"
INTEL_RUG_CONFIRMED = "intel.rug_confirmed"

# Map signal topics → outbound channel name in the Telegram reporter.
ALERT_TOPIC_TO_CHANNEL: dict[str, str] = {
    SIGNAL_ALERT_STRICT: "strict",
    SIGNAL_ALERT_MEDIUM: "medium",
    SIGNAL_ALERT_FIREHOSE: "firehose",
    SIGNAL_ALERT_MACRO: "macro",
    SIGNAL_ALERT_DM: "dm",
}
