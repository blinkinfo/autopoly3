"""Telegram command and callback handlers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from bot import formatters, keyboards
from db import queries
from core import scheduler as sched

log = logging.getLogger(__name__)

# Startup timestamp for uptime display
_BOT_START_TIME = datetime.now(timezone.utc)

# States for awaiting user text input
AWAIT_AMOUNT = "await_amount"
AWAIT_DEMO_BANKROLL = "await_demo_bankroll"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uptime_str() -> str:
    delta = datetime.now(timezone.utc) - _BOT_START_TIME
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


async def _edit_or_reply(update: Update, text: str, reply_markup=None) -> None:
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode="HTML", reply_markup=reply_markup
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text, parse_mode="HTML", reply_markup=reply_markup
            )
    elif update.message:
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=reply_markup
        )


# ---------------------------------------------------------------------------
# Signal & Trade renderers (accept asset filter)
# ---------------------------------------------------------------------------

async def _render_signals(update: Update, limit: int | None, asset: str | None = None) -> None:
    label = f"Last {limit}" if limit else "All Time"
    if asset and asset != "ALL":
        label += f" | {asset}"
    stats = await queries.get_signal_stats(limit=limit, asset=asset if asset != "ALL" else None)
    signals = await queries.get_recent_signals(n=min(limit or 20, 50), asset=asset if asset != "ALL" else None)
    text = (
        formatters.format_signal_stats(stats, label=label)
        + "\n"
        + formatters.format_recent_signals(signals)
    )
    active = str(limit) if limit else "all"
    active_asset = asset if asset else "ALL"
    await _edit_or_reply(update, text, keyboards.signal_filter_row(active, active_asset))


async def _render_trades(update: Update, limit: int | None, demo: bool = False, asset: str | None = None) -> None:
    label = f"Last {limit}" if limit else "All Time"
    if asset and asset != "ALL":
        label += f" | {asset}"
    stats = await queries.get_trade_stats(limit=limit, demo=demo, asset=asset if asset != "ALL" else None)
    trades = await queries.get_recent_trades(n=min(limit or 20, 50), demo=demo, asset=asset if asset != "ALL" else None)
    text = (
        formatters.format_trade_stats(stats, label=label, demo=demo)
        + "\n"
        + formatters.format_recent_trades(trades)
    )
    active = str(limit) if limit else "all"
    active_asset = asset if asset else "ALL"
    await _edit_or_reply(update, text, keyboards.trade_filter_row(active, demo=demo, active_asset=active_asset))


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    stats = await queries.get_signal_stats()
    trade_stats = await queries.get_trade_stats()
    pending_count = len(await queries.get_unresolved_signals())
    text = formatters.format_menu_header(
        total_signals=stats["total_signals"],
        win_pct=stats["win_pct"],
        net_pnl=trade_stats["net_pnl"],
        total_trades=trade_stats["total_trades"],
        pending_count=pending_count,
    )
    await _edit_or_reply(update, text, keyboards.main_menu())


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    poly_client = sched._poly_client
    connected = poly_client is not None
    balance: float | None = None
    if connected:
        try:
            from polymarket import account as pm_account
            balance = await pm_account.get_balance(poly_client)
        except Exception:
            pass

    autotrade = await queries.is_autotrade_enabled()
    trade_amount = await queries.get_trade_amount()
    demo_mode = await queries.is_demo_mode()
    demo_balance = await queries.get_demo_balance() if demo_mode else None
    sizing_mode = await queries.get_sizing_mode()

    last_sig_row = await queries.get_last_signal()
    last_signal_str: str | None = None
    if last_sig_row:
        side = last_sig_row.get("side") or "Skip"
        asset = last_sig_row.get("asset") or "BTC"
        ss = last_sig_row["slot_start"]
        ss_time = ss.split(" ")[-1] if " " in ss else ss
        last_signal_str = f"[{asset}] {side} @ {ss_time} UTC"

    unresolved = await queries.get_unresolved_trades()
    text = formatters.format_status(
        connected=connected,
        balance=balance,
        autotrade=autotrade,
        trade_amount=trade_amount,
        open_positions=len(unresolved),
        uptime_str=_uptime_str(),
        last_signal=last_signal_str,
        demo_mode=demo_mode,
        sizing_mode=sizing_mode,
        demo_balance=demo_balance,
    )
    await _edit_or_reply(update, text, keyboards.back_to_menu())


async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    active_asset = context.user_data.get("signals_asset_filter", "ALL")
    await _render_signals(update, limit=None, asset=active_asset)


async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    demo = await queries.is_demo_mode()
    active_asset = context.user_data.get("trades_asset_filter", "ALL")
    await _render_trades(update, limit=None, demo=demo, asset=active_asset)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    autotrade = await queries.is_autotrade_enabled()
    trade_amount = await queries.get_trade_amount()
    sizing_mode = await queries.get_sizing_mode()
    demo_on = await queries.is_demo_mode()
    demo_balance = await queries.get_demo_balance()
    auto_redeem_on = await queries.is_auto_redeem_enabled()
    text = (
        "\u2699\ufe0f <b>Settings</b>\n\n"
        f"AutoTrade: {'ON' if autotrade else 'OFF'}\n"
        f"Mode: {'Demo' if demo_on else 'Real'}\n"
        f"Sizing: {'Fixed' if sizing_mode == 'fixed' else 'Half-Kelly'}\n"
        f"Trade Amount: ${trade_amount:.2f}\n"
        f"Demo Balance: ${demo_balance:.2f}\n"
        f"Auto-Redeem: {'ON' if auto_redeem_on else 'OFF'}"
    )
    kb = keyboards.settings_keyboard(
        autotrade_on=autotrade,
        trade_amount=trade_amount,
        sizing_mode=sizing_mode,
        demo_on=demo_on,
        demo_balance=demo_balance,
        auto_redeem_on=auto_redeem_on,
    )
    await _edit_or_reply(update, text, kb)


async def cmd_demo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bankroll = await queries.get_demo_bankroll()
    balance = await queries.get_demo_balance()
    stats = await queries.get_trade_stats(demo=True)
    text = formatters.format_demo_status(
        bankroll=bankroll,
        balance=balance,
        trade_count=stats["total_trades"],
    )
    await _edit_or_reply(update, text, keyboards.demo_dashboard())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _edit_or_reply(update, formatters.format_help(), keyboards.back_to_menu())


# ---------------------------------------------------------------------------
# Callback router
# ---------------------------------------------------------------------------

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    # Awaiting input state — ignore callbacks
    state = context.user_data.get("awaiting")
    if state:
        return

    # ---- Navigation ----
    if data == "cmd_menu":
        await cmd_start(update, context)

    elif data == "cmd_status":
        await cmd_status(update, context)

    elif data == "cmd_signals":
        active_asset = context.user_data.get("signals_asset_filter", "ALL")
        await _render_signals(update, limit=None, asset=active_asset)

    elif data == "cmd_trades":
        demo = await queries.is_demo_mode()
        active_asset = context.user_data.get("trades_asset_filter", "ALL")
        await _render_trades(update, limit=None, demo=demo, asset=active_asset)

    elif data == "cmd_settings":
        await cmd_settings(update, context)

    elif data == "cmd_demo":
        await cmd_demo(update, context)

    elif data == "cmd_help":
        await cmd_help(update, context)

    # ---- Signal time filters ----
    elif data == "signals_10":
        context.user_data["signals_limit"] = 10
        active_asset = context.user_data.get("signals_asset_filter", "ALL")
        await _render_signals(update, limit=10, asset=active_asset)

    elif data == "signals_50":
        context.user_data["signals_limit"] = 50
        active_asset = context.user_data.get("signals_asset_filter", "ALL")
        await _render_signals(update, limit=50, asset=active_asset)

    elif data == "signals_all":
        context.user_data["signals_limit"] = None
        active_asset = context.user_data.get("signals_asset_filter", "ALL")
        await _render_signals(update, limit=None, asset=active_asset)

    # ---- Signal asset filters ----
    elif data.startswith("signals_asset_"):
        asset = data[len("signals_asset_"):]
        context.user_data["signals_asset_filter"] = asset
        limit = context.user_data.get("signals_limit")
        await _render_signals(update, limit=limit, asset=asset)

    # ---- Trade time filters ----
    elif data == "trades_10":
        context.user_data["trades_limit"] = 10
        demo = await queries.is_demo_mode()
        active_asset = context.user_data.get("trades_asset_filter", "ALL")
        await _render_trades(update, limit=10, demo=demo, asset=active_asset)

    elif data == "trades_50":
        context.user_data["trades_limit"] = 50
        demo = await queries.is_demo_mode()
        active_asset = context.user_data.get("trades_asset_filter", "ALL")
        await _render_trades(update, limit=50, demo=demo, asset=active_asset)

    elif data == "trades_all":
        context.user_data["trades_limit"] = None
        demo = await queries.is_demo_mode()
        active_asset = context.user_data.get("trades_asset_filter", "ALL")
        await _render_trades(update, limit=None, demo=demo, asset=active_asset)

    # ---- Trade mode filters ----
    elif data == "trades_mode_real":
        limit = context.user_data.get("trades_limit")
        active_asset = context.user_data.get("trades_asset_filter", "ALL")
        await _render_trades(update, limit=limit, demo=False, asset=active_asset)

    elif data == "trades_mode_demo":
        limit = context.user_data.get("trades_limit")
        active_asset = context.user_data.get("trades_asset_filter", "ALL")
        await _render_trades(update, limit=limit, demo=True, asset=active_asset)

    # ---- Trade asset filters ----
    elif data.startswith("trades_asset_"):
        asset = data[len("trades_asset_"):]
        context.user_data["trades_asset_filter"] = asset
        limit = context.user_data.get("trades_limit")
        demo = await queries.is_demo_mode()
        await _render_trades(update, limit=limit, demo=demo, asset=asset)

    # ---- Settings toggles ----
    elif data == "toggle_autotrade":
        current = await queries.is_autotrade_enabled()
        await queries.set_setting("autotrade_enabled", "false" if current else "true")
        await cmd_settings(update, context)

    elif data == "toggle_demo":
        current = await queries.is_demo_mode()
        await queries.set_setting("demo_mode", "false" if current else "true")
        await cmd_settings(update, context)

    elif data == "toggle_sizing":
        current = await queries.get_sizing_mode()
        new_mode = "kelly" if current == "fixed" else "fixed"
        await queries.set_setting("sizing_mode", new_mode)
        await cmd_settings(update, context)

    elif data == "toggle_auto_redeem":
        current = await queries.is_auto_redeem_enabled()
        await queries.set_setting("auto_redeem_enabled", "false" if current else "true")
        await cmd_settings(update, context)

    elif data == "change_amount":
        context.user_data["awaiting"] = AWAIT_AMOUNT
        await _edit_or_reply(
            update,
            "\U0001f4b5 Enter the new trade amount in USDC (e.g. <code>2.50</code>):",
            keyboards.cancel_input_keyboard(),
        )

    elif data == "change_demo_bankroll":
        context.user_data["awaiting"] = AWAIT_DEMO_BANKROLL
        await _edit_or_reply(
            update,
            "\U0001f4dd Enter the new demo bankroll in USDC (e.g. <code>200</code>):",
            keyboards.cancel_input_keyboard(),
        )

    elif data == "reset_demo":
        await _edit_or_reply(
            update,
            "\u26a0\ufe0f <b>Reset Demo Balance?</b>\n\nThis will restore your demo balance to the bankroll amount.",
            keyboards.reset_demo_confirm_keyboard(),
        )

    elif data == "reset_demo_confirm":
        bankroll = await queries.get_demo_bankroll()
        await queries.set_demo_balance(bankroll)
        await cmd_settings(update, context)

    else:
        log.debug("Unhandled callback: %s", data)


# ---------------------------------------------------------------------------
# Text message handler (input collection)
# ---------------------------------------------------------------------------

async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.get("awaiting")
    if not state:
        return

    text = (update.message.text or "").strip()
    context.user_data.pop("awaiting", None)

    if state == AWAIT_AMOUNT:
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError("Must be > 0")
            await queries.set_setting("trade_amount_usdc", str(round(amount, 2)))
            await update.message.reply_text(
                f"\u2705 Trade amount updated to <b>${amount:.2f}</b>.",
                parse_mode="HTML",
            )
        except ValueError:
            await update.message.reply_text(
                "\u274c Invalid amount. Please enter a positive number.",
                parse_mode="HTML",
            )
        await cmd_settings(update, context)

    elif state == AWAIT_DEMO_BANKROLL:
        try:
            bankroll = float(text)
            if bankroll <= 0:
                raise ValueError("Must be > 0")
            await queries.set_setting("demo_bankroll", str(round(bankroll, 2)))
            await queries.set_demo_balance(bankroll)
            await update.message.reply_text(
                f"\u2705 Demo bankroll set to <b>${bankroll:.2f}</b> and balance reset.",
                parse_mode="HTML",
            )
        except ValueError:
            await update.message.reply_text(
                "\u274c Invalid amount. Please enter a positive number.",
                parse_mode="HTML",
            )
        await cmd_settings(update, context)
