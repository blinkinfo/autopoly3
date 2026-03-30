"""Inline keyboard layouts for the Telegram bot."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config as cfg


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001f4ca Status", callback_data="cmd_status"),
            InlineKeyboardButton("\U0001f4e1 Signals", callback_data="cmd_signals"),
        ],
        [
            InlineKeyboardButton("\U0001f4b0 Trades", callback_data="cmd_trades"),
            InlineKeyboardButton("\u2699\ufe0f Settings", callback_data="cmd_settings"),
        ],
        [
            InlineKeyboardButton("\U0001f4dd Demo", callback_data="cmd_demo"),
            InlineKeyboardButton("\u2753 Help", callback_data="cmd_help"),
        ],
    ])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def settings_keyboard(
    autotrade_on: bool,
    trade_amount: float,
    sizing_mode: str = "fixed",
    demo_on: bool = True,
    demo_balance: float = 100.0,
    auto_redeem_on: bool = True,
) -> InlineKeyboardMarkup:
    at_label = "\U0001f916 AutoTrade: ON" if autotrade_on else "\U0001f916 AutoTrade: OFF"
    sizing_label = "Fixed" if sizing_mode == "fixed" else "Half-Kelly"
    demo_label = "\U0001f4dd Demo: ON" if demo_on else "\U0001f4dd Demo: OFF"
    redeem_label = "\U0001f4b0 Redeem: ON" if auto_redeem_on else "\U0001f4b0 Redeem: OFF"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(at_label, callback_data="toggle_autotrade"),
            InlineKeyboardButton(f"\U0001f4b5 ${trade_amount:.2f}", callback_data="change_amount"),
        ],
        [
            InlineKeyboardButton(f"\U0001f4cf Sizing: {sizing_label}", callback_data="toggle_sizing"),
            InlineKeyboardButton(redeem_label, callback_data="toggle_auto_redeem"),
        ],
        [
            InlineKeyboardButton(demo_label, callback_data="toggle_demo"),
            InlineKeyboardButton(f"\U0001f4b0 Balance: ${demo_balance:.2f}", callback_data="change_demo_bankroll"),
        ],
        [InlineKeyboardButton("\U0001f504 Reset Demo", callback_data="reset_demo")],
        [InlineKeyboardButton("\U0001f519 Back to Menu", callback_data="cmd_menu")],
    ])


# ---------------------------------------------------------------------------
# Reset Demo confirmation keyboard
# ---------------------------------------------------------------------------

def reset_demo_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Yes, Reset", callback_data="reset_demo_confirm"),
            InlineKeyboardButton("\u274c Cancel", callback_data="cmd_settings"),
        ],
    ])


# ---------------------------------------------------------------------------
# Filter rows (Last 10 / Last 50 / All Time + asset filter)
# ---------------------------------------------------------------------------

def signal_filter_row(active: str = "all", active_asset: str = "ALL") -> InlineKeyboardMarkup:
    # Time filter row
    time_buttons = [
        InlineKeyboardButton(
            ("[Last 10]" if active == "10" else "Last 10"),
            callback_data="signals_10",
        ),
        InlineKeyboardButton(
            ("[Last 50]" if active == "50" else "Last 50"),
            callback_data="signals_50",
        ),
        InlineKeyboardButton(
            ("[All Time]" if active == "all" else "All Time"),
            callback_data="signals_all",
        ),
    ]
    # Asset filter row
    asset_buttons = []
    for asset in cfg.SUPPORTED_ASSETS:
        label = f"[{asset}]" if active_asset == asset else asset
        asset_buttons.append(
            InlineKeyboardButton(label, callback_data=f"signals_asset_{asset}")
        )
    all_label = "[ALL]" if active_asset == "ALL" else "ALL"
    asset_buttons.append(InlineKeyboardButton(all_label, callback_data="signals_asset_ALL"))

    return InlineKeyboardMarkup([
        time_buttons,
        asset_buttons,
        [InlineKeyboardButton("\U0001f519 Back to Menu", callback_data="cmd_menu")],
    ])


def trade_filter_row(active: str = "all", demo: bool = False, active_asset: str = "ALL") -> InlineKeyboardMarkup:
    # Time filter row
    time_buttons = [
        InlineKeyboardButton(
            ("[Last 10]" if active == "10" else "Last 10"),
            callback_data="trades_10",
        ),
        InlineKeyboardButton(
            ("[Last 50]" if active == "50" else "Last 50"),
            callback_data="trades_50",
        ),
        InlineKeyboardButton(
            ("[All Time]" if active == "all" else "All Time"),
            callback_data="trades_all",
        ),
    ]
    # Demo / Real filter row
    demo_label = "[Demo]" if demo else "Demo"
    real_label = "[Real]" if not demo else "Real"
    mode_row = [
        InlineKeyboardButton(real_label, callback_data="trades_mode_real"),
        InlineKeyboardButton(demo_label, callback_data="trades_mode_demo"),
    ]
    # Asset filter row
    asset_buttons = []
    for asset in cfg.SUPPORTED_ASSETS:
        label = f"[{asset}]" if active_asset == asset else asset
        asset_buttons.append(
            InlineKeyboardButton(label, callback_data=f"trades_asset_{asset}")
        )
    all_label = "[ALL]" if active_asset == "ALL" else "ALL"
    asset_buttons.append(InlineKeyboardButton(all_label, callback_data="trades_asset_ALL"))

    return InlineKeyboardMarkup([
        time_buttons,
        mode_row,
        asset_buttons,
        [InlineKeyboardButton("\U0001f519 Back to Menu", callback_data="cmd_menu")],
    ])


# ---------------------------------------------------------------------------
# Demo dashboard
# ---------------------------------------------------------------------------

def demo_dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4b0 Demo Trades", callback_data="trades_mode_demo")],
        [InlineKeyboardButton("\U0001f504 Reset Demo", callback_data="reset_demo")],
        [InlineKeyboardButton("\U0001f519 Back to Menu", callback_data="cmd_menu")],
    ])


# ---------------------------------------------------------------------------
# Input-wait cancel keyboard
# ---------------------------------------------------------------------------

def cancel_input_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\u274c Cancel", callback_data="cmd_settings")],
    ])


# ---------------------------------------------------------------------------
# Back button only
# ---------------------------------------------------------------------------

def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f519 Back to Menu", callback_data="cmd_menu")],
    ])
