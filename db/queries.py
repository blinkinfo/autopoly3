"""CRUD helpers and analytics queries for signals, trades, and settings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aiosqlite
import config as cfg


def _db() -> str:
    return cfg.DB_PATH


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

async def get_setting(key: str) -> str | None:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(_db()) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


async def is_autotrade_enabled() -> bool:
    val = await get_setting("autotrade_enabled")
    return val == "true"


async def get_trade_amount() -> float:
    val = await get_setting("trade_amount_usdc")
    return float(val) if val else cfg.TRADE_AMOUNT_USDC


# ---------------------------------------------------------------------------
# Demo / Sizing setting helpers
# ---------------------------------------------------------------------------

async def is_demo_mode() -> bool:
    val = await get_setting("demo_mode")
    return val == "true"


async def get_demo_balance() -> float:
    val = await get_setting("demo_balance")
    return float(val) if val else cfg.DEFAULT_DEMO_BANKROLL


async def set_demo_balance(balance: float) -> None:
    await set_setting("demo_balance", str(round(balance, 4)))


async def get_demo_bankroll() -> float:
    val = await get_setting("demo_bankroll")
    return float(val) if val else cfg.DEFAULT_DEMO_BANKROLL


async def get_sizing_mode() -> str:
    val = await get_setting("sizing_mode")
    return val if val else cfg.DEFAULT_SIZING_MODE


async def get_win_rate_for_kelly() -> float:
    """Return historical signal win rate (non-skipped, resolved signals).

    Returns 0.0 if fewer than 10 resolved signals exist (not enough data).
    """
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins "
            "FROM signals WHERE skipped = 0 AND is_win IS NOT NULL"
        )
        row = await cursor.fetchone()
        total = row["total"]
        wins = row["wins"] or 0
    if total < 10:
        return 0.0
    return wins / total


# ---------------------------------------------------------------------------
# Signal CRUD
# ---------------------------------------------------------------------------

async def insert_signal(
    slot_start: str,
    slot_end: str,
    slot_timestamp: int,
    side: str | None,
    entry_price: float | None,
    opposite_price: float | None,
    skipped: bool = False,
) -> int:
    async with aiosqlite.connect(_db()) as db:
        cursor = await db.execute(
            "INSERT INTO signals (slot_start, slot_end, slot_timestamp, side, "
            "entry_price, opposite_price, skipped) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (slot_start, slot_end, slot_timestamp, side, entry_price, opposite_price, 1 if skipped else 0),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def resolve_signal(signal_id: int, outcome: str, is_win: bool) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(_db()) as db:
        await db.execute(
            "UPDATE signals SET outcome = ?, is_win = ?, resolved_at = ? WHERE id = ?",
            (outcome, 1 if is_win else 0, now, signal_id),
        )
        await db.commit()


async def get_recent_signals(n: int = 10) -> list[dict[str, Any]]:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (n,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_unresolved_signals() -> list[dict[str, Any]]:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM signals WHERE is_win IS NULL AND skipped = 0 ORDER BY id"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_last_signal() -> dict[str, Any] | None:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM signals WHERE skipped = 0 ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Trade CRUD
# ---------------------------------------------------------------------------

async def insert_trade(
    signal_id: int,
    slot_start: str,
    slot_end: str,
    side: str,
    entry_price: float,
    amount_usdc: float,
    order_id: str | None = None,
    fill_price: float | None = None,
    status: str = "pending",
    demo: bool = False,
) -> int:
    async with aiosqlite.connect(_db()) as db:
        cursor = await db.execute(
            "INSERT INTO trades (signal_id, slot_start, slot_end, side, entry_price, "
            "amount_usdc, order_id, fill_price, status, is_demo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (signal_id, slot_start, slot_end, side, entry_price, amount_usdc,
             order_id, fill_price, status, 1 if demo else 0),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def update_trade_status(
    trade_id: int,
    status: str,
    order_id: str | None = None,
    order_status_detail: str | None = None,
    fill_price: float | None = None,
) -> None:
    async with aiosqlite.connect(_db()) as db:
        fields = ["status = ?"]
        params: list[Any] = [status]
        if order_id is not None:
            fields.append("order_id = ?")
            params.append(order_id)
        if order_status_detail is not None:
            fields.append("order_status_detail = ?")
            params.append(order_status_detail)
        if fill_price is not None:
            fields.append("fill_price = ?")
            params.append(fill_price)
        params.append(trade_id)
        await db.execute(
            f"UPDATE trades SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
        await db.commit()


async def update_trade_retry(
    trade_id: int,
    last_error: str,
    order_status_detail: str,
) -> None:
    """Increment retry_count and record the latest error for a trade."""
    async with aiosqlite.connect(_db()) as db:
        await db.execute(
            "UPDATE trades SET retry_count = retry_count + 1, "
            "last_error = ?, order_status_detail = ? WHERE id = ?",
            (last_error, order_status_detail, trade_id),
        )
        await db.commit()


async def resolve_trade(trade_id: int, outcome: str, is_win: bool, pnl: float) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(_db()) as db:
        await db.execute(
            "UPDATE trades SET outcome = ?, is_win = ?, pnl = ?, resolved_at = ? WHERE id = ?",
            (outcome, 1 if is_win else 0, pnl, now, trade_id),
        )
        await db.commit()


async def get_recent_trades(n: int = 10, demo: bool = False) -> list[dict[str, Any]]:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trades WHERE is_demo = ? ORDER BY id DESC LIMIT ?",
            (1 if demo else 0, n),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_unresolved_trades(demo: bool = False) -> list[dict[str, Any]]:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trades WHERE is_win IS NULL AND status IN ('pending', 'filled') "
            "AND is_demo = ? ORDER BY id",
            (1 if demo else 0,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_trade_by_signal(signal_id: int, demo: bool = False) -> dict[str, Any] | None:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trades WHERE signal_id = ? AND is_demo = ? LIMIT 1",
            (signal_id, 1 if demo else 0),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Streak helpers
# ---------------------------------------------------------------------------

def _compute_streaks(results: list[int]) -> dict[str, Any]:
    """Given a list of 1/0 (win/loss) in chronological order, compute streaks."""
    if not results:
        return {
            "current_streak": 0,
            "current_streak_type": None,
            "best_win_streak": 0,
            "worst_loss_streak": 0,
        }

    current = 1
    current_type = results[-1]
    best_win = 0
    worst_loss = 0
    streak = 1
    prev = results[0]

    for i in range(len(results)):
        if i == 0:
            streak = 1
        elif results[i] == prev:
            streak += 1
        else:
            streak = 1
        prev = results[i]
        if results[i] == 1:
            best_win = max(best_win, streak)
        else:
            worst_loss = max(worst_loss, streak)

    # compute current streak from the end
    current_type = results[-1]
    current = 0
    for v in reversed(results):
        if v == current_type:
            current += 1
        else:
            break

    return {
        "current_streak": current,
        "current_streak_type": "W" if current_type == 1 else "L",
        "best_win_streak": best_win,
        "worst_loss_streak": worst_loss,
    }


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

async def get_signal_stats(limit: int | None = None) -> dict[str, Any]:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row

        # Total signals (non-skipped)
        q = "SELECT COUNT(*) as cnt FROM signals WHERE skipped = 0"
        row = await (await db.execute(q)).fetchone()
        total = row["cnt"]

        # Skip count
        q2 = "SELECT COUNT(*) as cnt FROM signals WHERE skipped = 1"
        row2 = await (await db.execute(q2)).fetchone()
        skip_count = row2["cnt"]

        # Resolved signals for stats
        if limit:
            inner = (
                f"SELECT * FROM signals WHERE skipped = 0 AND is_win IS NOT NULL "
                f"ORDER BY id DESC LIMIT {limit}"
            )
            query = f"SELECT is_win FROM ({inner}) ORDER BY id ASC"
        else:
            query = (
                "SELECT is_win FROM signals WHERE skipped = 0 AND is_win IS NOT NULL "
                "ORDER BY id ASC"
            )

        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        results = [r["is_win"] for r in rows]

    wins = sum(1 for r in results if r == 1)
    losses = sum(1 for r in results if r == 0)
    resolved = wins + losses
    win_pct = (wins / resolved * 100) if resolved else 0.0
    streaks = _compute_streaks(results)

    return {
        "total_signals": total,
        "skip_count": skip_count,
        "wins": wins,
        "losses": losses,
        "resolved": resolved,
        "win_pct": round(win_pct, 1),
        **streaks,
    }


async def get_trade_stats(limit: int | None = None, demo: bool = False) -> dict[str, Any]:
    demo_flag = 1 if demo else 0
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row

        if limit:
            inner = (
                f"SELECT * FROM trades WHERE is_win IS NOT NULL AND is_demo = {demo_flag} "
                f"ORDER BY id DESC LIMIT {limit}"
            )
            query = f"SELECT is_win, amount_usdc, pnl FROM ({inner}) ORDER BY id ASC"
        else:
            query = (
                "SELECT is_win, amount_usdc, pnl FROM trades "
                f"WHERE is_win IS NOT NULL AND is_demo = {demo_flag} ORDER BY id ASC"
            )

        cursor = await db.execute(query)
        rows = await cursor.fetchall()

        total_q = f"SELECT COUNT(*) as cnt FROM trades WHERE is_demo = {demo_flag}"
        total_row = await (await db.execute(total_q)).fetchone()
        total_trades = total_row["cnt"]

    results = [r["is_win"] for r in rows]
    wins = sum(1 for r in results if r == 1)
    losses = sum(1 for r in results if r == 0)
    resolved = wins + losses
    win_pct = (wins / resolved * 100) if resolved else 0.0

    total_deployed = sum(r["amount_usdc"] for r in rows)
    total_pnl = sum(r["pnl"] for r in rows if r["pnl"] is not None)
    total_returned = total_deployed + total_pnl
    roi_pct = (total_pnl / total_deployed * 100) if total_deployed else 0.0

    streaks = _compute_streaks(results)

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "resolved": resolved,
        "win_pct": round(win_pct, 1),
        "total_deployed": round(total_deployed, 2),
        "total_returned": round(total_returned, 2),
        "net_pnl": round(total_pnl, 2),
        "roi_pct": round(roi_pct, 1),
        **streaks,
    }


# ---------------------------------------------------------------------------
# Redemption CRUD
# ---------------------------------------------------------------------------

async def is_auto_redeem_enabled() -> bool:
    val = await get_setting("auto_redeem_enabled")
    return val == "true"


async def insert_redemption(
    condition_id: str,
    amount_usdc: float,
    market_slug: str | None = None,
    market_title: str | None = None,
    outcome: str | None = None,
    tx_hash: str | None = None,
    status: str = "pending",
) -> int:
    async with aiosqlite.connect(_db()) as db:
        cursor = await db.execute(
            "INSERT INTO redemptions (condition_id, amount_usdc, market_slug, "
            "market_title, outcome, tx_hash, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (condition_id, amount_usdc, market_slug, market_title, outcome, tx_hash, status),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def update_redemption_status(
    redemption_id: int, status: str, tx_hash: str | None = None, error_message: str | None = None
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(_db()) as db:
        if status == "redeemed":
            await db.execute(
                "UPDATE redemptions SET status = ?, tx_hash = COALESCE(?, tx_hash), "
                "redeemed_at = ?, error_message = NULL WHERE id = ?",
                (status, tx_hash, now, redemption_id),
            )
        else:
            await db.execute(
                "UPDATE redemptions SET status = ?, error_message = ? WHERE id = ?",
                (status, error_message, redemption_id),
            )
        await db.commit()


async def get_redeemed_condition_ids() -> set[str]:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT DISTINCT condition_id FROM redemptions WHERE status IN ('redeemed', 'pending')"
        )
        rows = await cursor.fetchall()
        return {row["condition_id"] for row in rows}


async def get_recent_redemptions(n: int = 10) -> list[dict[str, Any]]:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM redemptions ORDER BY id DESC LIMIT ?", (n,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_redemption_stats() -> dict[str, Any]:
    async with aiosqlite.connect(_db()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN status = 'redeemed' THEN 1 ELSE 0 END) as success_count, "
            "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_count, "
            "SUM(CASE WHEN status = 'redeemed' THEN amount_usdc ELSE 0 END) as total_redeemed_usdc "
            "FROM redemptions"
        )
        row = await cursor.fetchone()
        return {
            "total": row["total"] or 0,
            "success_count": row["success_count"] or 0,
            "failed_count": row["failed_count"] or 0,
            "total_redeemed_usdc": round(row["total_redeemed_usdc"] or 0, 2),
        }
