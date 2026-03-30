"""Signal engine — check slot N+1 prices at T-85 s and trade N+1 if threshold met."""

from __future__ import annotations

import logging
from typing import Any

import config as cfg
from polymarket.markets import (
    get_current_slot_info,
    get_next_slot_info,
    get_slot_prices,
)

log = logging.getLogger(__name__)


async def check_signal(asset: str = "BTC") -> dict[str, Any] | None:
    """Called at T-85 s before the current slot N ends.

    1. Fetch slot N+1 live prices from Gamma API for the given asset.
    2. If UP price >= threshold -> signal "Up".
    3. If DOWN price >= threshold -> signal "Down".
    4. If neither >= threshold -> return skip sentinel.

    Returns a dict (signal or skip) or ``None`` on hard error.
    """
    slot_n1 = get_next_slot_info(asset=asset)

    log.debug(
        "[%s] Checking signal for slot N+1 %s (%s-%s UTC)",
        asset,
        slot_n1["slug"],
        slot_n1["slot_start_str"],
        slot_n1["slot_end_str"],
    )

    # Fetch N+1 prices — the market we're evaluating AND trading
    prices = await get_slot_prices(slot_n1["slug"])
    if prices is None:
        log.error("[%s] Could not fetch prices for slot N+1 %s", asset, slot_n1["slug"])
        return None

    up_price = prices["up_price"]
    down_price = prices["down_price"]

    log.debug(
        "[%s] Slot N+1 ask prices  Up=%.4f  Down=%.4f  (threshold=%.2f)",
        asset, up_price, down_price, cfg.SIGNAL_THRESHOLD,
    )

    side: str | None = None
    entry_price: float | None = None
    opposite_price: float | None = None

    if up_price >= cfg.SIGNAL_THRESHOLD:
        side = "Up"
        entry_price = up_price
        opposite_price = down_price
    elif down_price >= cfg.SIGNAL_THRESHOLD:
        side = "Down"
        entry_price = down_price
        opposite_price = up_price

    # --- Build result --------------------------------------------------
    if side is None:
        # No signal — return a skip sentinel so the scheduler can log it
        return {
            "skipped": True,
            "asset": asset,
            "up_price": up_price,
            "down_price": down_price,
            "slot_n1_start_full": slot_n1["slot_start_full"],
            "slot_n1_end_full": slot_n1["slot_end_full"],
            "slot_n1_start_str": slot_n1["slot_start_str"],
            "slot_n1_end_str": slot_n1["slot_end_str"],
            "slot_n1_ts": slot_n1["slot_start_ts"],
        }

    # Token ID comes directly from the N+1 prices we already fetched
    token_id = prices["up_token_id"] if side == "Up" else prices["down_token_id"]

    log.info(
        "[%s] SIGNAL: %s @ ask $%.4f for slot N+1 %s-%s UTC  token=%s",
        asset,
        side,
        entry_price,
        slot_n1["slot_start_str"],
        slot_n1["slot_end_str"],
        token_id,
    )

    return {
        "skipped": False,
        "asset": asset,
        "side": side,
        "entry_price": entry_price,
        "opposite_price": opposite_price,
        "token_id": token_id,
        # Slot N+1 (both signal source and trade window)
        "slot_n1_start_full": slot_n1["slot_start_full"],
        "slot_n1_end_full": slot_n1["slot_end_full"],
        "slot_n1_start_str": slot_n1["slot_start_str"],
        "slot_n1_end_str": slot_n1["slot_end_str"],
        "slot_n1_ts": slot_n1["slot_start_ts"],
        "slot_n1_slug": slot_n1["slug"],
    }
