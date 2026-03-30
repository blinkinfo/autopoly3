"""Message formatters — every output shows UTC timeslots with emojis."""

from __future__ import annotations

from typing import Any


# Asset badge map — shown in live notifications
_ASSET_BADGE: dict[str, str] = {
    "BTC": "\U0001f7e0 BTC",  # orange circle
    "ETH": "\U0001f535 ETH",  # blue circle
    "XRP": "\U0001f7e3 XRP",  # purple circle
    "SOL": "\U0001f7e1 SOL",  # yellow circle
}


def _badge(asset: str) -> str:
    return _ASSET_BADGE.get(asset, asset)


# ---------------------------------------------------------------------------
# Live notifications (sent by scheduler)
# ---------------------------------------------------------------------------

def format_signal(
    side: str,
    entry_price: float,
    slot_start_str: str,
    slot_end_str: str,
    autotrade: bool,
    sizing_mode: str = "fixed",
    trade_amount: float | None = None,
    asset: str = "BTC",
) -> str:
    side_emoji = "\U0001f4c8" if side == "Up" else "\U0001f4c9"
    at_line = "\U0001f916 AutoTrade: ON \u2192 Order Placed" if autotrade else "\U0001f916 AutoTrade: OFF"
    sizing_label = "Fixed" if sizing_mode == "fixed" else "Half-Kelly"
    amount_str = f"${trade_amount:.2f}" if trade_amount is not None else "N/A"
    badge = _badge(asset)
    return (
        f"\U0001f4e1 <b>[{badge}] Signal Fired!</b>\n"
        "\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"\u2502 \u23f0 Slot: {slot_start_str}-{slot_end_str} UTC\n"
        f"\u2502 {side_emoji} Side: {side}\n"
        f"\u2502 \U0001f4b2 Ask Price: ${entry_price:.2f}\n"
        f"\u2502 \U0001f4cf Sizing: {sizing_label} ({amount_str})\n"
        f"\u2502 {at_line}\n"
        "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
    )


def format_skip(
    slot_start_str: str,
    slot_end_str: str,
    up_price: float,
    down_price: float,
    asset: str = "BTC",
) -> str:
    badge = _badge(asset)
    return (
        f"\u23ed\ufe0f <b>[{badge}] No Signal</b>\n"
        "\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"\u2502 \u23f0 Slot: {slot_start_str}-{slot_end_str} UTC\n"
        f"\u2502 \U0001f4c8 Up Ask: ${up_price:.2f}  |  \U0001f4c9 Down Ask: ${down_price:.2f}\n"
        "\u2502 Neither side \u2265 $0.53 \u2014 skipping\n"
        "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
    )


def format_resolution(
    is_win: bool,
    side: str,
    entry_price: float,
    slot_start_str: str,
    slot_end_str: str,
    pnl: float | None = None,
    is_demo: bool = False,
    demo_balance: float | None = None,
    asset: str = "BTC",
) -> str:
    result_price = 1.00 if is_win else 0.00
    icon = "\u2705" if is_win else "\u274c"
    label = "WIN" if is_win else "LOSS"
    side_emoji = "\U0001f4c8" if side == "Up" else "\U0001f4c9"
    demo_prefix = "[DEMO] " if is_demo else ""
    badge = _badge(asset)

    lines = [
        f"{icon} <b>{demo_prefix}[{badge}] Signal Result \u2014 {label}</b>",
        "\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        f"\u2502 \u23f0 Slot: {slot_start_str}-{slot_end_str} UTC",
        f"\u2502 {side_emoji} Side: {side}",
        f"\u2502 \U0001f4b2 Entry: ${entry_price:.2f} \u2192 Result: ${result_price:.2f}",
    ]
    if pnl is not None:
        sign = "+" if pnl >= 0 else ""
        lines.append(f"\u2502 \U0001f4b0 P&L: {sign}${pnl:.2f}")
    if is_demo and demo_balance is not None:
        lines.append(f"\u2502 \U0001f4dd Demo Balance: ${demo_balance:.2f}")
    lines.append("\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    return "\n".join(lines)


def format_redemption_notification(
    redemptions: list[dict],
    total_usdc: float,
) -> str:
    count = len(redemptions)
    lines = [
        f"\U0001f4b0 <b>Redeemed {count} position(s) for +${total_usdc:.2f} USDC</b>",
        "\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
    ]
    for r in redemptions:
        title = r.get("market_title") or (r.get("condition_id", "Unknown")[:16])
        amount = r.get("amount_usdc", 0)
        outcome = r.get("outcome", "")
        status_icon = "\u2705" if r.get("status") == "redeemed" else "\u274c"
        lines.append(f"\u2502 {status_icon} {title} ({outcome}) \u2014 ${amount:.2f}")
    lines.append("\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    return "\n".join(lines)


def format_redemption_error(error_msg: str) -> str:
    return (
        "\u274c <b>Auto-Redeem Error</b>\n"
        "\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"\u2502 {error_msg}\n"
        "\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
    )


# ---------------------------------------------------------------------------
# Dashboards (requested via bot commands)
# ---------------------------------------------------------------------------

def format_signal_stats(stats: dict[str, Any], label: str = "All Time") -> str:
    streak_str = "0"
    if stats.get("current_streak") and stats.get("current_streak_type"):
        streak_str = f"{stats['current_streak']}{stats['current_streak_type']}"

    SEP = "\u2501" * 20
    lines = [
        f"\U0001f4ca <b>Signal Performance ({label})</b>",
        SEP,
        f"\U0001f4e1 Total Signals: {stats['total_signals']}",
        f"\u2705 Wins: {stats['wins']}  |  \u274c Losses: {stats['losses']}",
        f"\U0001f4c8 Win Rate: {stats['win_pct']}%",
        SEP,
        f"\U0001f525 Current Streak: {streak_str}",
        f"\U0001f3c6 Best Win Streak: {stats['best_win_streak']}",
        f"\U0001f480 Worst Loss Streak: {stats['worst_loss_streak']}",
        SEP,
        f"\u23ed\ufe0f Skipped (No Signal): {stats['skip_count']}",
    ]
    return "\n".join(lines)


def format_trade_stats(stats: dict[str, Any], label: str = "All Time", demo: bool = False) -> str:
    streak_str = "0"
    if stats.get("current_streak") and stats.get("current_streak_type"):
        streak_str = f"{stats['current_streak']}{stats['current_streak_type']}"

    sign = "+" if stats["net_pnl"] >= 0 else ""
    roi_sign = "+" if stats["roi_pct"] >= 0 else ""
    mode_label = "Demo" if demo else "Real"

    SEP = "\u2501" * 20
    lines = [
        f"\U0001f4b0 <b>{mode_label} Trade Performance ({label})</b>",
        SEP,
        f"\U0001f4ca Total Trades: {stats['total_trades']}",
        f"\u2705 Wins: {stats['wins']}  |  \u274c Losses: {stats['losses']}",
        f"\U0001f4c8 Win Rate: {stats['win_pct']}%",
        SEP,
        f"\U0001f4b5 Total Deployed: ${stats['total_deployed']:.2f}",
        f"\U0001f4b0 Total Returned: ${stats['total_returned']:.2f}",
        f"\U0001f4c8 Net P&L: {sign}${stats['net_pnl']:.2f}",
        f"\U0001f4ca ROI: {roi_sign}{stats['roi_pct']}%",
        SEP,
        f"\U0001f525 Current Streak: {streak_str}",
        f"\U0001f3c6 Best Win Streak: {stats['best_win_streak']}",
    ]
    return "\n".join(lines)


def format_status(
    connected: bool,
    balance: float | None,
    autotrade: bool,
    trade_amount: float,
    open_positions: int,
    uptime_str: str,
    last_signal: str | None,
    demo_mode: bool = False,
    sizing_mode: str = "fixed",
    demo_balance: float | None = None,
) -> str:
    conn_icon = "\U0001f7e2" if connected else "\U0001f534"
    conn_text = "Connected" if connected else "Disconnected"
    at_text = "ON" if autotrade else "OFF"
    bal_text = f"{balance:.2f} USDC" if balance is not None else "N/A"
    sig_text = last_signal or "None"
    mode_text = "Demo" if demo_mode else "Real"
    sizing_label = "Fixed" if sizing_mode == "fixed" else "Half-Kelly"

    health_parts = ["ONLINE" if connected else "OFFLINE"]
    if autotrade:
        health_parts.append(f"{mode_text} trading")
    else:
        health_parts.append("Watching only")
    health_line = " | ".join(health_parts)

    SEP = "\u2501" * 20
    lines = [
        f"\U0001f916 <b>AutoPoly \u2014 {health_line}</b>",
        SEP,
        f"{conn_icon} Bot: Running",
        f"\U0001f517 Polymarket: {conn_text}",
        f"\U0001f4b0 Balance: {bal_text}",
        SEP,
        f"\U0001f916 AutoTrade: {at_text}",
        f"\U0001f3ae Mode: {mode_text}",
        f"\U0001f4cf Sizing: {sizing_label}",
        f"\U0001f4b5 Trade Amount: ${trade_amount:.2f}",
        f"\U0001f4ca Open Positions: {open_positions}",
    ]
    if demo_mode and demo_balance is not None:
        lines.append(f"\U0001f4dd Demo Balance: ${demo_balance:.2f}")
    lines += [
        SEP,
        f"\u23f0 Uptime: {uptime_str}",
        f"\U0001f4e1 Last Signal: {sig_text}",
    ]
    return "\n".join(lines)


def format_menu_header(
    total_signals: int,
    win_pct: float,
    net_pnl: float,
    total_trades: int,
    pending_count: int = 0,
) -> str:
    pnl_sign = "+" if net_pnl >= 0 else ""
    pending_str = f"  ({pending_count} pending)" if pending_count > 0 else ""
    return (
        "\U0001f916 <b>AutoPoly</b>\n\n"
        f"\U0001f4e1 Signals: {total_signals} ({win_pct}% win rate)\n"
        f"\U0001f4b0 Trades: {total_trades} "
        f"(P&L: {pnl_sign}${net_pnl:.2f}){pending_str}\n\n"
        "Select an option:"
    )


def format_demo_status(
    bankroll: float,
    balance: float,
    trade_count: int,
) -> str:
    session_pnl = balance - bankroll
    sign = "+" if session_pnl >= 0 else ""
    SEP = "\u2501" * 20
    lines = [
        "\U0001f4dd <b>Demo Dashboard</b>",
        SEP,
        f"\U0001f4b0 Session Bankroll: ${bankroll:.2f}",
        f"\U0001f4b5 Current Balance: ${balance:.2f}",
        f"\U0001f4c8 Session P&L: {sign}${session_pnl:.2f}",
        f"\U0001f4ca Demo Trades: {trade_count}",
        SEP,
    ]
    return "\n".join(lines)


def format_recent_signals(signals: list[dict[str, Any]]) -> str:
    if not signals:
        return "\nNo signals recorded yet."
    lines = ["\n\U0001f4cb <b>Recent Signals:</b>"]
    for s in signals:
        ss = s["slot_start"].split(" ")[-1] if " " in s["slot_start"] else s["slot_start"]
        se = s["slot_end"].split(" ")[-1] if " " in s["slot_end"] else s["slot_end"]
        asset_tag = s.get("asset") or "BTC"
        if s["skipped"]:
            lines.append(f"\u23ed\ufe0f  {asset_tag:>3}  SKIP   {ss}\u2013{se} UTC")
        else:
            if s.get("is_win") == 1:
                icon = "\u2705"
                result = "WIN"
            elif s.get("is_win") == 0:
                icon = "\u274c"
                result = "LOSS"
            else:
                icon = "\u23f3"
                result = "PENDING"
            side = s.get("side") or "?"
            price_str = f"${s.get('entry_price', 0):.2f}"
            lines.append(
                f"{icon}  {asset_tag:>3}  {side:>4}  {price_str}  {ss}\u2013{se}  [{result}]"
            )
    return "\n".join(lines)


def format_recent_trades(trades: list[dict[str, Any]]) -> str:
    if not trades:
        return "\nNo trades recorded yet."
    lines = ["\n\U0001f4cb <b>Recent Trades:</b>"]
    for t in trades:
        ss = t["slot_start"].split(" ")[-1] if " " in t["slot_start"] else t["slot_start"]
        se = t["slot_end"].split(" ")[-1] if " " in t["slot_end"] else t["slot_end"]
        if t.get("is_win") == 1:
            icon = "\u2705"
            result = "WIN"
        elif t.get("is_win") == 0:
            icon = "\u274c"
            result = "LOSS"
        else:
            icon = "\u23f3"
            result = "PENDING"
        asset_tag = t.get("asset") or "BTC"
        demo_tag = "[D] " if t.get("is_demo") else ""
        side = t.get("side") or "?"
        amt_str = f"${t.get('amount_usdc', 0):.2f}"
        pnl_str = ""
        if t.get("pnl") is not None:
            sign = "+" if t["pnl"] >= 0 else ""
            pnl_str = f"  {sign}${t['pnl']:.2f}"
        lines.append(
            f"{icon}  {asset_tag:>3}  {demo_tag}{side:>4}  {amt_str}  {ss}\u2013{se}{pnl_str}  [{result}]"
        )
    return "\n".join(lines)


def format_help() -> str:
    return (
        "\u2753 <b>AutoPoly Commands</b>\n\n"
        "/start \u2014 Main menu\n"
        "/status \u2014 Bot status & balance\n"
        "/signals \u2014 Signal performance stats\n"
        "/trades \u2014 Trade P&L dashboard\n"
        "/demo \u2014 Demo trading dashboard\n"
        "/settings \u2014 Toggle autotrade, set amount\n"
        "/help \u2014 This help message\n\n"
        "<b>Settings:</b>\n"
        "\u2022 <b>Sizing Mode</b> \u2014 Fixed (constant amount) or Half-Kelly (dynamic based on win rate)\n"
        "\u2022 <b>Demo Mode</b> \u2014 Paper trade with simulated balance (no real orders)\n"
        "\u2022 <b>Demo Bankroll</b> \u2014 Starting balance for demo sessions; reset anytime\n\n"
        "<b>How it works:</b>\n"
        "Every 5 minutes the bot checks the NEXT slot's prices for "
        "BTC, ETH, XRP, and SOL up/down markets 85 seconds before the "
        "current slot ends. If either side \u2265 $0.53, a signal fires "
        "and trades that slot. With AutoTrade ON, a FOK market order is "
        "placed automatically (or simulated in Demo mode). All 4 assets "
        "run in parallel on the same 5-minute schedule."
    )


def format_error(context: str, exc: Exception) -> str:
    exc_type = type(exc).__name__
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:197] + "..."
    return (
        f"\u26a0\ufe0f <b>Error \u2014 {context}</b>\n\n"
        f"<code>{exc_type}: {msg}</code>\n\n"
        "The error has been logged. If this keeps happening, check the logs."
    )
