"""Tests for Phase E social listener helpers."""

from __future__ import annotations

import pytest

from cryptobot.agents.tg_call_parser import extract_call, find_addresses
from cryptobot.agents.translator import _needs_translation, _non_english_fraction


# ---------------------------------------------------------------------------
# find_addresses
# ---------------------------------------------------------------------------

EVM_ADDR = "0x6982508145454ce325ddbe47a25d4ec3d2311933"
SOL_ADDR = "7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZV3qyouov87awMs"


def test_find_addresses_evm():
    found = find_addresses(f"check this token {EVM_ADDR} now")
    assert found == [(EVM_ADDR, "evm")]


def test_find_addresses_solana():
    found = find_addresses(f"new sol gem: {SOL_ADDR}")
    assert found == [(SOL_ADDR, "solana")]


def test_find_addresses_multiple():
    text = f"{EVM_ADDR} and {SOL_ADDR}"
    found = find_addresses(text)
    assert len(found) == 2
    chains = {chain for _, chain in found}
    assert chains == {"evm", "solana"}


def test_find_addresses_dedup():
    text = f"{EVM_ADDR} and again {EVM_ADDR}"
    found = find_addresses(text)
    assert len(found) == 1


def test_find_addresses_strips_punctuation():
    found = find_addresses(f"({EVM_ADDR})")
    assert found == [(EVM_ADDR, "evm")]


def test_find_addresses_empty():
    assert find_addresses("") == []
    assert find_addresses("no addresses here") == []


# ---------------------------------------------------------------------------
# extract_call
# ---------------------------------------------------------------------------


def test_extract_call_with_buy_language():
    text = f"ape into this gem: {EVM_ADDR}"
    call = extract_call(text)
    assert call is not None
    assert call["address"] == EVM_ADDR
    assert call["chain_guess"] == "evm"
    assert call["buy_language"] is True


def test_extract_call_with_ticker():
    text = f"$PEPE is mooning, buy at {EVM_ADDR}"
    call = extract_call(text)
    assert call is not None
    assert "$PEPE" in call["tickers"]


def test_extract_call_address_only_no_signal():
    # Address alone, no buy-language, no ticker → not a call
    call = extract_call(EVM_ADDR)
    assert call is None


def test_extract_call_no_address():
    assert extract_call("ape into $PEPE right now") is None


def test_extract_call_empty():
    assert extract_call("") is None
    assert extract_call(None) is None  # type: ignore[arg-type]


def test_extract_call_solana_with_lfg():
    text = f"LFG this new sol launch {SOL_ADDR} $WIF"
    call = extract_call(text)
    assert call is not None
    assert call["chain_guess"] == "solana"
    assert call["buy_language"] is True


# ---------------------------------------------------------------------------
# translator helpers
# ---------------------------------------------------------------------------


def test_non_english_fraction_english():
    assert _non_english_fraction("hello world this is english") == 0.0


def test_non_english_fraction_chinese():
    frac = _non_english_fraction("比特币价格今天大涨了很多")
    assert frac > 0.5


def test_non_english_fraction_korean():
    frac = _non_english_fraction("오늘 비트코인이 많이 올랐어요")
    assert frac > 0.4


def test_non_english_fraction_cyrillic():
    frac = _non_english_fraction("Биткоин сегодня вырос")
    assert frac > 0.5


def test_needs_translation_english():
    assert _needs_translation("btc going up today, very bullish") is False


def test_needs_translation_chinese():
    assert _needs_translation("比特币价格今天大涨了非常多，大家都在讨论") is True


def test_needs_translation_short():
    # Below minimum length threshold
    assert _needs_translation("比特") is False


def test_needs_translation_empty():
    assert _needs_translation("") is False
