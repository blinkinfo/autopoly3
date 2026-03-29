"""Auto-redemption of winning Polymarket positions via poly-web3.

Fetches redeemable positions from the Data API and redeems them using the
poly-web3 PolyWeb3Service (gasless Safe proxy transactions via the relayer).
Handles both standard CTF and NegRisk markets transparently.

Gracefully degrades to a no-op if poly-web3 is not installed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

import config as cfg
from db import queries

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional poly-web3 import — graceful degradation if not installed
# ---------------------------------------------------------------------------
try:
    from poly_web3 import PolyWeb3Service  # type: ignore[import]
    from py_builder_relayer_client.client import RelayClient  # type: ignore[import]
    from py_builder_signing_sdk.config import BuilderConfig  # type: ignore[import]
    from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds  # type: ignore[import]
    _POLY_WEB3_AVAILABLE = True
except ImportError:
    log.warning(
        "poly-web3 / py-builder-relayer-client not installed — "
        "auto-redeem is disabled. Install poly-web3>=1.0.0 to enable."
    )
    _POLY_WEB3_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data API helpers
# ---------------------------------------------------------------------------

async def _fetch_redeemable_positions(funder_address: str) -> list[dict[str, Any]]:
    """Fetch redeemable positions for *funder_address* from the Data API."""
    url = f"{cfg.DATA_API_HOST}/positions"
    params = {"user": funder_address, "redeemable": "true"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            # API may return a list directly or {"data": [...]}
            if isinstance(data, list):
                return data
            return data.get("data", data.get("positions", []))
    except Exception:
        log.exception("Failed to fetch redeemable positions from Data API")
        return []


def _parse_amount_usdc(position: dict[str, Any]) -> float:
    """Extract USDC value from a position record.

    The Data API returns positions with various field names depending on
    version. We try several common ones and fall back to 0.0.
    """
    # Prefer explicit size fields
    for field in ("redeemableAmount", "size", "currentValue", "value"):
        val = position.get(field)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    # Derive from token quantity * current price
    qty = position.get("quantity") or position.get("amount") or 0
    price = position.get("curPrice") or position.get("price") or 1.0
    try:
        return float(qty) * float(price)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Redemption execution (blocking — called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _derive_builder_config() -> Any:
    """Derive BuilderConfig automatically from POLYMARKET_PRIVATE_KEY.

    The CLOB L2 api key/secret/passphrase are deterministically derived
    from the wallet private key via EIP-712 — no separate env vars needed.
    This uses the same py-clob-client that the rest of the app already
    depends on, so there is zero extra credential management overhead.

    Raises RuntimeError if POLYMARKET_PRIVATE_KEY is not set.
    """
    if not cfg.POLYMARKET_PRIVATE_KEY:
        raise RuntimeError(
            "POLYMARKET_PRIVATE_KEY is not set — cannot derive builder credentials"
        )

    # Import here to avoid a hard dependency at module level.
    # py-clob-client is already in requirements.txt.
    from py_clob_client.client import ClobClient  # type: ignore[import]

    # Initialise a temporary L1-only client (no api creds yet).
    temp_client = ClobClient(
        host=cfg.CLOB_HOST,
        key=cfg.POLYMARKET_PRIVATE_KEY,
        chain_id=cfg.CHAIN_ID,
    )

    # Derive (or create) the L2 api credentials from the private key.
    # This call signs an EIP-712 message — deterministic, idempotent.
    api_creds = temp_client.create_or_derive_api_creds()

    # api_creds is an ApiCreds namedtuple/object with .api_key, .api_secret,
    # .api_passphrase attributes (field names vary by py-clob-client version).
    key = getattr(api_creds, "api_key", None) or getattr(api_creds, "apiKey", None)
    secret = getattr(api_creds, "api_secret", None) or getattr(api_creds, "secret", None)
    passphrase = (
        getattr(api_creds, "api_passphrase", None)
        or getattr(api_creds, "passphrase", None)
    )

    if not key or not secret or not passphrase:
        raise RuntimeError(
            f"create_or_derive_api_creds() returned incomplete credentials: {api_creds!r}"
        )

    return BuilderConfig(
        local_builder_creds=BuilderApiKeyCreds(
            key=key,
            secret=secret,
            passphrase=passphrase,
        )
    )


def _build_poly_web3_service(clob_client: Any) -> Any:
    """Construct a PolyWeb3Service with auto-derived builder credentials.

    Builder credentials (api key/secret/passphrase) are derived on-the-fly
    from POLYMARKET_PRIVATE_KEY — no separate env vars required.
    """
    builder_config = _derive_builder_config()

    relay_client = RelayClient(
        relayer_url=cfg.RELAYER_URL,
        chain_id=cfg.CHAIN_ID,
        private_key=cfg.POLYMARKET_PRIVATE_KEY,
        builder_config=builder_config,
    )

    service = PolyWeb3Service(
        clob_client=clob_client.client,
        relay_client=relay_client,
    )
    return service


def _do_redeem(clob_client: Any, condition_id: str) -> str:
    """Blocking call: build service and redeem one condition.

    Returns the transaction hash string on success.
    """
    service = _build_poly_web3_service(clob_client)
    result = service.redeem([condition_id])
    # result may be a tx hash string, a dict with 'hash', or similar
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return result.get("hash") or result.get("tx_hash") or str(result)
    return str(result)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def redeem_winning_positions(poly_client: Any) -> list[dict[str, Any]]:
    """Fetch and redeem all redeemable positions. Returns list of result dicts.

    Each result dict contains:
        condition_id, market_slug, market_title, outcome, amount_usdc,
        tx_hash (or None), status ('redeemed' or 'failed'), error_message.

    One failure does NOT block processing of subsequent positions.
    Returns an empty list if poly-web3 is unavailable or no positions are found.
    """
    if not _POLY_WEB3_AVAILABLE:
        log.debug("poly-web3 not available — skipping auto-redeem")
        return []

    if poly_client is None:
        log.debug("No poly_client — skipping auto-redeem")
        return []

    funder = cfg.POLYMARKET_FUNDER_ADDRESS
    if not funder:
        log.warning("POLYMARKET_FUNDER_ADDRESS not set — skipping auto-redeem")
        return []

    # 1. Fetch redeemable positions from Data API
    positions = await _fetch_redeemable_positions(funder)
    if not positions:
        log.debug("No redeemable positions found")
        return []

    log.info("Found %d redeemable position(s) from Data API", len(positions))

    # 2. Filter out already-processed condition IDs
    already_done = await queries.get_redeemed_condition_ids()
    new_positions = [
        p for p in positions
        if (p.get("conditionId") or p.get("condition_id", "")) not in already_done
    ]
    if not new_positions:
        log.info("All redeemable positions already processed — nothing to do")
        return []

    log.info("%d new position(s) to redeem", len(new_positions))

    results: list[dict[str, Any]] = []

    for position in new_positions:
        condition_id: str = position.get("conditionId") or position.get("condition_id", "")
        market_slug: str | None = position.get("market") or position.get("slug") or position.get("marketSlug")
        market_title: str | None = position.get("title") or position.get("marketTitle")
        outcome: str | None = position.get("outcome") or position.get("side")
        amount_usdc: float = _parse_amount_usdc(position)

        if not condition_id:
            log.warning("Position missing conditionId — skipping: %s", position)
            continue

        log.info(
            "Redeeming condition=%s slug=%s amount=%.4f USDC",
            condition_id, market_slug, amount_usdc,
        )

        # Insert a pending record first (idempotency guard)
        redemption_id = await queries.insert_redemption(
            condition_id=condition_id,
            amount_usdc=amount_usdc,
            market_slug=market_slug,
            market_title=market_title,
            outcome=outcome,
            status="pending",
        )

        # 3. Execute redemption in a thread (blocking call)
        try:
            tx_hash: str = await asyncio.to_thread(_do_redeem, poly_client, condition_id)
            log.info("Redeemed condition=%s tx=%s", condition_id, tx_hash)
            await queries.update_redemption_status(
                redemption_id, status="redeemed", tx_hash=tx_hash
            )
            results.append({
                "condition_id": condition_id,
                "market_slug": market_slug,
                "market_title": market_title,
                "outcome": outcome,
                "amount_usdc": amount_usdc,
                "tx_hash": tx_hash,
                "status": "redeemed",
                "error_message": None,
            })
        except Exception as exc:
            err = str(exc)
            log.exception("Redemption failed for condition=%s: %s", condition_id, err)
            await queries.update_redemption_status(
                redemption_id, status="failed", error_message=err
            )
            results.append({
                "condition_id": condition_id,
                "market_slug": market_slug,
                "market_title": market_title,
                "outcome": outcome,
                "amount_usdc": amount_usdc,
                "tx_hash": None,
                "status": "failed",
                "error_message": err,
            })

    return results
