"""APScheduler loop — syncs to 5-min slot boundaries, fires signals, trades, resolves."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config as cfg
from core import strategy, trader, resolver
from core import pending_queue
from core import sizing
from core.redeemer import redeem_winning_positions
from db import queries
from polymarket import account as pm_account
from polymarket.markets import SLOT_DURATION, slot_info_from_ts
from core.trader import execute_fok_order

log = logging.getLogger(__name__)

SCHEDULER: AsyncIOScheduler | None = None

# Holds references so Telegram bot can send messages
_tg_app = None
_poly_client = None

# Reverse map: slug prefix -> asset name (e.g. 'eth' -> 'ETH')
_PREFIX_TO_ASSET: dict[str, str] = {
    v: k for k, v in cfg.ASSET_SLUG_PREFIX.items()
}


def _next_check_time() -> datetime:
    """Calculate the next T-85s check time (slot_end - SIGNAL_LEAD_TIME).

    Slots align to :00, :05, :10 ... :55 of each hour.
    T-85s = slot_end - 85 seconds = slot_start + 300 - 85 = slot_start + 215 seconds.
    """
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    current_slot_start = epoch - (epoch % SLOT_DURATION)
    check_epoch = current_slot_start + SLOT_DURATION - cfg.SIGNAL_LEAD_TIME

    if check_epoch <= epoch:
        # Already past this slot's check time — schedule for next slot
        check_epoch += SLOT_DURATION

    return datetime.fromtimestamp(check_epoch, tz=timezone.utc)


def _asset_from_slug(slug: str) -> str:
    """Extract asset name from a slot slug like 'eth-updown-5m-1234567890'.

    Falls back to 'BTC' for any legacy slugs that don't match.
    """
    try:
        prefix = slug.split("-updown-5m-")[0]
        return _PREFIX_TO_ASSET.get(prefix, "BTC")
    except Exception:
        return "BTC"


async def _send_telegram(text: str) -> None:
    """Send a message to the configured Telegram chat."""
    if _tg_app is None or cfg.TELEGRAM_CHAT_ID is None:
        return
    try:
        await _tg_app.bot.send_message(
            chat_id=int(cfg.TELEGRAM_CHAT_ID),
            text=text,
            parse_mode="HTML",
        )
    except Exception:
        log.exception("Failed to send Telegram message")


async def _update_demo_balance_after_pnl(pnl: float) -> float | None:
    """Adjust demo_balance by pnl and return the new balance (or None if not demo)."""
    balance = await queries.get_demo_balance()
    new_balance = round(balance + pnl, 4)
    if new_balance < 0:
        new_balance = 0.0
    await queries.set_demo_balance(new_balance)
    return new_balance


async def _resolve_and_notify(
    signal_id: int,
    slug: str,
    side: str,
    entry_price: float,
    slot_start: str,
    slot_end: str,
    trade_id: int | None,
    amount_usdc: float | None,
    is_demo_trade: bool = False,
    asset: str = "BTC",
) -> None:
    """Poll for resolution, update DB, notify Telegram."""
    try:
        from bot.formatters import format_resolution

        winner = await resolver.resolve_slot(slug)
        if winner is None:
            log.warning(
                "[%s] Could not resolve slot %s after all attempts — adding to persistent retry queue",
                asset, slug,
            )
            await pending_queue.add_pending(
                signal_id=signal_id,
                slug=slug,
                side=side,
                entry_price=entry_price,
                slot_start=slot_start,
                slot_end=slot_end,
                trade_id=trade_id,
                amount_usdc=amount_usdc,
                is_demo=is_demo_trade,
            )
            return

        is_win = winner == side
        await queries.resolve_signal(signal_id, winner, is_win)

        pnl: float | None = None
        demo_balance_after: float | None = None
        if trade_id is not None and amount_usdc is not None:
            if is_win:
                pnl = round(amount_usdc * (1.0 / entry_price - 1.0), 4)
            else:
                pnl = -amount_usdc
            await queries.resolve_trade(trade_id, winner, is_win, pnl)

            if is_demo_trade and pnl is not None:
                demo_balance_after = await _update_demo_balance_after_pnl(pnl)

        # Extract HH:MM from slot_start/slot_end full strings
        s_start = slot_start.split(" ")[-1] if " " in slot_start else slot_start
        s_end = slot_end.split(" ")[-1] if " " in slot_end else slot_end

        msg = format_resolution(
            is_win=is_win,
            side=side,
            entry_price=entry_price,
            slot_start_str=s_start,
            slot_end_str=s_end,
            pnl=pnl,
            is_demo=is_demo_trade,
            demo_balance=demo_balance_after,
            asset=asset,
        )
        await _send_telegram(msg)
    except Exception as exc:
        log.exception("[%s] _resolve_and_notify crashed", asset)
        from bot.formatters import format_error
        await _send_telegram(format_error(f"Resolution cycle [{asset}]", exc))


async def _reconcile_pending() -> None:
    """Retry resolution for all slots in the persistent pending queue.

    Called every 5 minutes by the scheduler.
    """
    from bot.formatters import format_resolution

    pending = await pending_queue.list_pending()
    if not pending:
        return

    log.info("Reconciler: checking %d pending slot(s)...", len(pending))

    for item in pending:
        try:
            signal_id = item["signal_id"]
            slug = item["slug"]
            side = item["side"]
            entry_price = item["entry_price"]
            slot_start = item["slot_start"]
            slot_end = item["slot_end"]
            trade_id = item.get("trade_id")
            amount_usdc = item.get("amount_usdc")
            is_demo_trade = item.get("is_demo", False)
            asset = _asset_from_slug(slug)

            try:
                winner, resolved = await resolver.check_resolution(slug)
            except Exception:
                log.exception("Reconciler: error checking slug=%s", slug)
                continue

            if not resolved:
                log.debug("Reconciler: slot %s still unresolved — will retry next cycle", slug)
                continue

            is_win = winner == side
            await queries.resolve_signal(signal_id, winner, is_win)

            pnl: float | None = None
            demo_balance_after: float | None = None
            if trade_id is not None and amount_usdc is not None:
                if is_win:
                    pnl = round(amount_usdc * (1.0 / entry_price - 1.0), 4)
                else:
                    pnl = -amount_usdc
                await queries.resolve_trade(trade_id, winner, is_win, pnl)

                if is_demo_trade and pnl is not None:
                    demo_balance_after = await _update_demo_balance_after_pnl(pnl)

            await pending_queue.remove_pending(signal_id)

            s_start = slot_start.split(" ")[-1] if " " in slot_start else slot_start
            s_end = slot_end.split(" ")[-1] if " " in slot_end else slot_end
            msg = format_resolution(
                is_win=is_win,
                side=side,
                entry_price=entry_price,
                slot_start_str=s_start,
                slot_end_str=s_end,
                pnl=pnl,
                is_demo=is_demo_trade,
                demo_balance=demo_balance_after,
                asset=asset,
            )
            await _send_telegram(msg)
            log.info(
                "Reconciler: resolved signal %d [%s] — winner=%s is_win=%s",
                signal_id, asset, winner, is_win,
            )
        except Exception as exc:
            log.exception("_reconcile_pending: error processing item %s", item)
            from bot.formatters import format_error
            await _send_telegram(format_error("Reconcile pending", exc))
            continue


async def _auto_redeem() -> None:
    """Fetch and redeem all redeemable positions; notify Telegram on success."""
    try:
        from bot.formatters import format_redemption_notification

        if not await queries.is_auto_redeem_enabled():
            log.debug("Auto-redeem disabled — skipping")
            return

        if _poly_client is None:
            log.debug("No poly_client — skipping auto-redeem")
            return

        results = await redeem_winning_positions(_poly_client)

        if results:
            total_usdc = sum(r.get("amount_usdc", 0) for r in results if r.get("status") == "redeemed")
            msg = format_redemption_notification(results, total_usdc)
            await _send_telegram(msg)
            log.info("Auto-redeem: %d position(s) processed, total=%.4f USDC", len(results), total_usdc)

    except Exception as exc:
        log.exception("Auto-redeem job failed unexpectedly")
        from bot.formatters import format_redemption_error
        await _send_telegram(format_redemption_error(str(exc)))


async def _check_and_trade(asset: str = "BTC") -> None:
    """Core loop body — called at T-85s for each asset's slot."""
    try:
        from bot.formatters import format_signal, format_skip

        # 1. Check signal
        signal = await strategy.check_signal(asset=asset)
        if signal is None:
            log.error("[%s] Strategy returned None (hard error) — skipping this slot", asset)
            await _send_telegram(f"\u274c [{asset}] Strategy error \u2014 could not fetch prices. Skipping slot.")
            return

        slot_start_full = signal["slot_n1_start_full"]
        slot_end_full = signal["slot_n1_end_full"]
        slot_start_str = signal["slot_n1_start_str"]
        slot_end_str = signal["slot_n1_end_str"]
        slot_ts = signal["slot_n1_ts"]

        # 2. Log signal to DB
        if signal["skipped"]:
            signal_id = await queries.insert_signal(
                slot_start=slot_start_full,
                slot_end=slot_end_full,
                slot_timestamp=slot_ts,
                side=None,
                entry_price=None,
                opposite_price=None,
                skipped=True,
                asset=asset,
            )
            msg = format_skip(
                slot_start_str=slot_start_str,
                slot_end_str=slot_end_str,
                up_price=signal["up_price"],
                down_price=signal["down_price"],
                asset=asset,
            )
            await _send_telegram(msg)
            return

        side = signal["side"]
        entry_price = signal["entry_price"]
        opposite_price = signal["opposite_price"]
        token_id = signal["token_id"]
        prefix = cfg.ASSET_SLUG_PREFIX.get(asset, asset.lower())
        slug = signal.get("slot_n1_slug", f"{prefix}-updown-5m-{slot_ts}")

        signal_id = await queries.insert_signal(
            slot_start=slot_start_full,
            slot_end=slot_end_full,
            slot_timestamp=slot_ts,
            side=side,
            entry_price=entry_price,
            opposite_price=opposite_price,
            skipped=False,
            asset=asset,
        )

        # 3. Check autotrade and compute trade size
        autotrade = await queries.is_autotrade_enabled()
        demo_mode = await queries.is_demo_mode()

        balance_val: float | None = None
        if not demo_mode and _poly_client is not None:
            try:
                balance_val = await pm_account.get_balance(_poly_client)
            except Exception:
                log.exception("[%s] Failed to fetch Polymarket balance for sizing", asset)

        trade_amount = await sizing.get_trade_size(entry_price, real_bankroll=balance_val)
        sizing_mode = await queries.get_sizing_mode()

        # 4. Send signal notification
        msg = format_signal(
            side=side,
            entry_price=entry_price,
            slot_start_str=slot_start_str,
            slot_end_str=slot_end_str,
            autotrade=autotrade,
            sizing_mode=sizing_mode,
            trade_amount=trade_amount,
            asset=asset,
        )
        await _send_telegram(msg)

        # 5. Place trade
        trade_id: int | None = None
        amount_usdc: float | None = None
        is_demo_trade = False

        if demo_mode:
            is_demo_trade = True
            amount_usdc = round(trade_amount, 2)
            demo_bal = await queries.get_demo_balance()
            if amount_usdc > demo_bal:
                amount_usdc = round(demo_bal, 2)
            if amount_usdc <= 0:
                await _send_telegram(
                    f"\u26a0\ufe0f [{asset}] [DEMO] Insufficient demo balance \u2014 trade skipped."
                )
            else:
                trade_id = await queries.insert_trade(
                    signal_id=signal_id,
                    slot_start=slot_start_full,
                    slot_end=slot_end_full,
                    side=side,
                    entry_price=entry_price,
                    amount_usdc=amount_usdc,
                    fill_price=entry_price,
                    status="filled",
                    demo=True,
                    asset=asset,
                )
                await _send_telegram(
                    f"\U0001f4dd [{asset}] [DEMO] Trade placed: {side} ${amount_usdc:.2f} @ ${entry_price:.4f}"
                )

        elif autotrade and _poly_client is not None and token_id:
            amount_usdc = round(trade_amount, 2)
            slot_end_epoch = slot_ts + SLOT_DURATION
            trade_id = await queries.insert_trade(
                signal_id=signal_id,
                slot_start=slot_start_full,
                slot_end=slot_end_full,
                side=side,
                entry_price=entry_price,
                amount_usdc=amount_usdc,
                status="pending",
                demo=False,
                asset=asset,
            )

            result = await execute_fok_order(
                _poly_client, token_id, amount_usdc, slot_end_ts=slot_end_epoch,
            )

            if result.status == "filled":
                await queries.update_trade_status(
                    trade_id, "filled",
                    order_id=result.order_id,
                    order_status_detail=result.error_category or "filled_ok",
                )
                if result.attempts > 1:
                    await queries.update_trade_retry(
                        trade_id,
                        last_error=result.error or "",
                        order_status_detail=result.error_category or "filled_after_retry",
                    )
                    await _send_telegram(
                        f"\u2705 [{asset}] Trade FILLED after {result.attempts} attempt(s): "
                        f"{side} ${amount_usdc:.2f} slot {slot_start_str}-{slot_end_str} UTC"
                    )
                log.info("[%s] Trade filled: order_id=%s attempts=%d", asset, result.order_id, result.attempts)
            else:
                await queries.update_trade_status(
                    trade_id, "failed",
                    order_status_detail=result.error_category or result.status,
                )
                if result.attempts > 0:
                    await queries.update_trade_retry(
                        trade_id,
                        last_error=result.error or "unknown",
                        order_status_detail=result.error_category or result.status,
                    )
                detail = f" ({result.error_category})" if result.error_category else ""
                await _send_telegram(
                    f"\u274c [{asset}] Trade FAILED{detail} after {result.attempts} attempt(s) for "
                    f"{side} slot {slot_start_str}-{slot_end_str} UTC"
                )
                log.error(
                    "[%s] Trade failed: status=%s attempts=%d error=%s",
                    asset, result.status, result.attempts, result.error,
                )
                trade_id = None

        # 6. Schedule resolution after slot N+1 ends
        resolve_time = datetime.fromtimestamp(slot_ts + SLOT_DURATION + 15, tz=timezone.utc)
        if SCHEDULER is not None:
            SCHEDULER.add_job(
                _resolve_and_notify,
                trigger="date",
                run_date=resolve_time,
                kwargs={
                    "signal_id": signal_id,
                    "slug": slug,
                    "side": side,
                    "entry_price": entry_price,
                    "slot_start": slot_start_full,
                    "slot_end": slot_end_full,
                    "trade_id": trade_id,
                    "amount_usdc": amount_usdc,
                    "is_demo_trade": is_demo_trade,
                    "asset": asset,
                },
                id=f"resolve_{asset}_{signal_id}",
                replace_existing=True,
            )
            log.debug("[%s] Scheduled resolution for signal %d at %s", asset, signal_id, resolve_time.isoformat())

    except Exception as exc:
        log.exception("[%s] _check_and_trade crashed", asset)
        from bot.formatters import format_error
        await _send_telegram(format_error(f"Signal/trade cycle [{asset}]", exc))
    finally:
        _schedule_next_for_asset(asset)


def _schedule_next_for_asset(asset: str) -> None:
    """Schedule the next check_and_trade job for a specific asset."""
    if SCHEDULER is None:
        return
    next_time = _next_check_time()
    SCHEDULER.add_job(
        _check_and_trade,
        trigger="date",
        run_date=next_time,
        kwargs={"asset": asset},
        id=f"check_and_trade_{asset}",
        replace_existing=True,
    )
    log.info("[%s] Next check: %s UTC", asset, next_time.strftime("%H:%M:%S"))


def _schedule_next() -> None:
    """Schedule the next check_and_trade job for ALL supported assets."""
    for asset in cfg.SUPPORTED_ASSETS:
        _schedule_next_for_asset(asset)


async def recover_unresolved() -> None:
    """On startup, schedule resolution for any unresolved signals/trades."""
    signals = await queries.get_unresolved_signals()
    if not signals:
        log.debug("No unresolved signals to recover.")
    else:
        log.info("Recovering %d unresolved signal(s)...", len(signals))
        for sig in signals:
            # Derive asset from stored asset column; fall back to slug parsing
            asset = sig.get("asset") or "BTC"
            prefix = cfg.ASSET_SLUG_PREFIX.get(asset, asset.lower())
            slug = f"{prefix}-updown-5m-{sig['slot_timestamp']}"

            trade = await queries.get_trade_by_signal(sig["id"], demo=False)
            is_demo_trade = False
            if trade is None:
                trade = await queries.get_trade_by_signal(sig["id"], demo=True)
                if trade is not None:
                    is_demo_trade = True
            trade_id = trade["id"] if trade else None
            amount_usdc = trade["amount_usdc"] if trade else None

            resolve_time = datetime.now(timezone.utc) + timedelta(seconds=5)
            if SCHEDULER is not None:
                SCHEDULER.add_job(
                    _resolve_and_notify,
                    trigger="date",
                    run_date=resolve_time,
                    kwargs={
                        "signal_id": sig["id"],
                        "slug": slug,
                        "side": sig["side"],
                        "entry_price": sig["entry_price"],
                        "slot_start": sig["slot_start"],
                        "slot_end": sig["slot_end"],
                        "trade_id": trade_id,
                        "amount_usdc": amount_usdc,
                        "is_demo_trade": is_demo_trade,
                        "asset": asset,
                    },
                    id=f"recover_{sig['id']}",
                    replace_existing=True,
                )

    pending = await pending_queue.list_pending()
    if pending:
        log.info(
            "%d slot(s) remain in persistent retry queue — reconciler will handle them.",
            len(pending),
        )


def start_scheduler(tg_app, poly_client) -> AsyncIOScheduler:
    """Create, configure, and start the scheduler."""
    global SCHEDULER, _tg_app, _poly_client
    _tg_app = tg_app
    _poly_client = poly_client

    SCHEDULER = AsyncIOScheduler(timezone="UTC")
    SCHEDULER.start()

    # Reconciler: retry pending slots every 5 minutes
    SCHEDULER.add_job(
        _reconcile_pending,
        trigger="interval",
        minutes=5,
        id="reconcile_pending",
        replace_existing=True,
    )
    log.info("Reconciler job scheduled (every 5 minutes).")

    # Auto-redeem: check and redeem winning positions every 5 minutes
    SCHEDULER.add_job(
        _auto_redeem,
        trigger="interval",
        minutes=5,
        id="auto_redeem",
        replace_existing=True,
    )
    log.info("Auto-redeem job scheduled (every 5 minutes).")

    # Schedule first check for all assets
    _schedule_next()
    log.info("Scheduler started for assets: %s", cfg.SUPPORTED_ASSETS)

    return SCHEDULER
