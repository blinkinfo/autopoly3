"""Account helpers — balance, positions, connection status."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

log = logging.getLogger(__name__)


async def get_balance(poly_client) -> float | None:
    """Return USDC balance in dollars via get_balance_allowance (COLLATERAL)."""
    try:
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        result = await asyncio.to_thread(
            poly_client.client.get_balance_allowance, params
        )
        # Result is a dict with 'balance' in wei (1 USDC = 1_000_000 wei)
        balance_usdc = int(result["balance"]) / 1e6
        return round(balance_usdc, 2)
    except Exception:
        log.exception("Failed to fetch balance")
        return None


async def get_open_positions(poly_client) -> list[dict[str, Any]]:
    """Return list of open positions via the CLOB client."""
    try:
        positions = await asyncio.to_thread(
            lambda: getattr(poly_client.client, "get_positions", lambda: [])()
        )
        if isinstance(positions, list):
            return positions
        return []
    except Exception:
        log.exception("Failed to fetch positions")
        return []


async def get_connection_status(poly_client) -> bool:
    """Quick connectivity check — try to hit the CLOB server time endpoint."""
    try:
        info = await asyncio.to_thread(poly_client.client.get_server_time)
        return info is not None
    except Exception:
        log.exception("Connection check failed")
        return False
