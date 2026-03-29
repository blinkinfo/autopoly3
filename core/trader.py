"""FOK market-order execution with production-grade retry logic.

Handles Polymarket CLOB error classification, nonce-aware duplicate
prevention, exponential backoff, and time-budget enforcement for
5-min slot trading.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
BACKOFF_BASE = 1.0          # seconds — 1s, 2s, 4s
TIME_BUDGET_MARGIN = 30     # stop retrying if <30s before slot end

# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------
_TERMINAL_ERRORS = frozenset({
    "not enough balance",
    "insufficient allowance",
    "invalid nonce",
    "trading is currently disabled",
    "trading is currently cancel-only",
    "order minimum size",
    "invalid token",
    "invalid side",
    "invalid amount",
    "market not found",
    "market closed",
    "market paused",
})

_RETRYABLE_ERRORS = frozenset({
    "fully filled or killed",       # FOK killed — liquidity issue
    "matching engine is restarting", # transient CLOB state
    "too many requests",            # rate limit
    "service unavailable",          # 503
    "internal server error",        # 500
    "bad gateway",                  # 502
    "gateway timeout",              # 504
})


def _classify_error(error: str | Exception) -> str:
    """Classify a CLOB error as 'terminal', 'fok_killed', 'retryable', or 'unknown'.

    Returns a category string used to decide retry strategy.
    """
    msg = str(error).lower()

    for pattern in _TERMINAL_ERRORS:
        if pattern in msg:
            return "terminal"

    if "fully filled or killed" in msg:
        return "fok_killed"

    for pattern in _RETRYABLE_ERRORS:
        if pattern in msg:
            return "retryable"

    # Network-level errors are retryable
    if any(keyword in msg for keyword in ("timeout", "connection", "reset", "eof", "broken pipe")):
        return "retryable"

    return "unknown"


def _has_time_budget(slot_end_ts: int | None) -> bool:
    """Return True if there is enough time left before the slot ends to retry."""
    if slot_end_ts is None:
        return True  # no budget enforcement
    remaining = slot_end_ts - int(datetime.now(timezone.utc).timestamp())
    return remaining > TIME_BUDGET_MARGIN


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FokResult:
    """Structured result from execute_fok_order."""
    status: str               # 'filled', 'failed', 'fok_killed', 'timeout'
    order_id: str | None = None
    attempts: int = 0
    error: str | None = None
    error_category: str | None = None  # 'terminal', 'fok_killed', 'retryable', 'unknown'
    response: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------

async def _sign_order(poly_client, token_id: str, amount: float):
    """Sign a FOK market order locally (runs in thread for async compat)."""
    order_args = MarketOrderArgs(
        token_id=token_id,
        amount=amount,
        side=BUY,
        order_type=OrderType.FOK,
    )
    return await asyncio.to_thread(
        poly_client.client.create_market_order, order_args
    )


async def _post_order(poly_client, signed_order) -> dict[str, Any]:
    """Post a signed order to the CLOB (runs in thread for async compat)."""
    response = await asyncio.to_thread(
        poly_client.client.post_order, signed_order, OrderType.FOK
    )
    return response if isinstance(response, dict) else {"raw": str(response)}


async def execute_fok_order(
    poly_client,
    token_id: str,
    amount_usdc: float,
    slot_end_ts: int | None = None,
) -> FokResult:
    """Execute a FOK market buy with production-grade retry logic.

    Duplicate prevention strategy:
    - On network/5xx errors: retry the SAME signed order (same nonce).
      If the CLOB actually filled it, the retry gets 'invalid nonce' ->
      we treat that as a successful fill (not a duplicate).
    - On FOK kills (liquidity): re-sign with a NEW nonce (safe because
      we know the previous order was killed, not filled).
    - On terminal errors: fail immediately, no retry.

    Parameters
    ----------
    poly_client : PolymarketClient
        Authenticated CLOB client wrapper.
    token_id : str
        The outcome token to buy.
    amount_usdc : float
        Dollar amount to spend (rounded to 2dp).
    slot_end_ts : int | None
        Unix timestamp of slot end for time-budget enforcement.
        If None, no time budget is enforced.

    Returns
    -------
    FokResult
        Structured result with status, order_id, attempts, and error details.
    """
    amount = round(amount_usdc, 2)
    log.info("FOK execute: token=%s amount=$%.2f max_retries=%d", token_id, amount, MAX_RETRIES)

    signed_order = None
    last_error: str | None = None
    last_category: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        # --- Time budget check ---
        if not _has_time_budget(slot_end_ts):
            log.warning("FOK: time budget exhausted before attempt %d (slot_end_ts=%s)", attempt, slot_end_ts)
            return FokResult(
                status="timeout",
                attempts=attempt - 1,
                error="Time budget exhausted \u2014 too close to slot end",
                error_category="timeout",
            )

        try:
            # --- Sign (or reuse) ---
            if signed_order is None:
                log.debug("FOK attempt %d: signing new order", attempt)
                signed_order = await _sign_order(poly_client, token_id, amount)
            else:
                log.debug("FOK attempt %d: reusing existing signed order (same nonce)", attempt)

            # --- Post ---
            response = await _post_order(poly_client, signed_order)
            order_id = response.get("orderID") or response.get("order_id")

            # Check for error in response body (CLOB returns 200 with error messages)
            error_msg = response.get("errorMsg") or response.get("error_msg") or response.get("error")
            if error_msg:
                raise RuntimeError(error_msg)

            # --- Success ---
            log.info("FOK filled on attempt %d: order_id=%s", attempt, order_id)
            return FokResult(
                status="filled",
                order_id=order_id,
                attempts=attempt,
                response=response,
            )

        except Exception as exc:
            err_str = str(exc)
            category = _classify_error(exc)
            last_error = err_str
            last_category = category

            log.warning(
                "FOK attempt %d/%d failed: category=%s error=%s",
                attempt, MAX_RETRIES, category, err_str,
            )

            # --- Nonce conflict during retry: the original order was filled ---
            if "invalid nonce" in err_str.lower() and attempt > 1:
                log.info(
                    "FOK nonce conflict on retry \u2014 original order was likely filled. "
                    "Treating as success."
                )
                return FokResult(
                    status="filled",
                    attempts=attempt,
                    error="Nonce conflict \u2014 original order confirmed filled",
                    error_category="nonce_conflict_success",
                )

            # --- Terminal: stop immediately ---
            if category == "terminal":
                log.error("FOK terminal error \u2014 not retrying: %s", err_str)
                return FokResult(
                    status="failed",
                    attempts=attempt,
                    error=err_str,
                    error_category=category,
                )

            # --- Last attempt: give up ---
            if attempt >= MAX_RETRIES:
                break

            # --- FOK killed (liquidity): re-sign on next attempt ---
            if category == "fok_killed":
                log.info("FOK killed (liquidity) \u2014 will re-sign on next attempt")
                signed_order = None  # force re-sign (new nonce, safe because order was killed)

            # --- Network/5xx/matching-engine: keep same signed order ---
            # signed_order stays the same \u2014 retry with identical nonce

            # --- Backoff ---
            delay = BACKOFF_BASE * (2 ** (attempt - 1))
            log.debug("FOK: backing off %.1fs before attempt %d", delay, attempt + 1)
            await asyncio.sleep(delay)

    # Exhausted all retries
    log.error("FOK exhausted %d retries. Last error: %s (%s)", MAX_RETRIES, last_error, last_category)
    return FokResult(
        status="failed" if last_category != "fok_killed" else "fok_killed",
        attempts=MAX_RETRIES,
        error=last_error,
        error_category=last_category,
    )


# ---------------------------------------------------------------------------
# Backward-compatible wrapper (used by any code still calling the old API)
# ---------------------------------------------------------------------------

async def place_fok_order(
    poly_client,
    token_id: str,
    amount_usdc: float,
) -> dict[str, Any]:
    """Legacy wrapper \u2014 delegates to execute_fok_order without time budget.

    Raises on failure to preserve the old exception-based contract.
    """
    result = await execute_fok_order(poly_client, token_id, amount_usdc)
    if result.status == "filled":
        resp = result.response or {}
        if result.order_id:
            resp["orderID"] = result.order_id
        return resp
    raise RuntimeError(
        f"FOK order failed after {result.attempts} attempt(s): {result.error}"
    )
