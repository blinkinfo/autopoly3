"""SQLite schema initialisation — creates tables and inserts default settings."""

import aiosqlite
import config as cfg

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    slot_start TEXT NOT NULL,
    slot_end TEXT NOT NULL,
    slot_timestamp INTEGER NOT NULL,
    side TEXT,
    entry_price REAL,
    opposite_price REAL,
    outcome TEXT,
    is_win INTEGER,
    resolved_at TIMESTAMP,
    skipped INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    slot_start TEXT NOT NULL,
    slot_end TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    amount_usdc REAL NOT NULL,
    order_id TEXT,
    fill_price REAL,
    status TEXT DEFAULT 'pending',
    outcome TEXT,
    is_win INTEGER,
    pnl REAL,
    resolved_at TIMESTAMP,
    is_demo INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    order_status_detail TEXT,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    condition_id TEXT NOT NULL,
    market_slug TEXT,
    market_title TEXT,
    outcome TEXT,
    amount_usdc REAL NOT NULL,
    tx_hash TEXT,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    redeemed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_redemptions_condition ON redemptions(condition_id);
CREATE INDEX IF NOT EXISTS idx_redemptions_status ON redemptions(status);
"""

DEFAULT_SETTINGS = {
    "autotrade_enabled": "false",
    "trade_amount_usdc": str(cfg.TRADE_AMOUNT_USDC),
    "sizing_mode": "fixed",
    "demo_mode": "true",
    "demo_bankroll": "100",
    "demo_balance": "100",
    "auto_redeem_enabled": "true",
}


async def _migrate(db: aiosqlite.Connection) -> None:
    """Run forward-only migrations for existing databases."""
    try:
        await db.execute(
            "ALTER TABLE trades ADD COLUMN is_demo INTEGER DEFAULT 0"
        )
    except Exception as exc:  # noqa: BLE001
        if "duplicate column" not in str(exc).lower():
            raise

    try:
        await db.execute(
            "ALTER TABLE trades ADD COLUMN retry_count INTEGER DEFAULT 0"
        )
    except Exception as exc:  # noqa: BLE001
        if "duplicate column" not in str(exc).lower():
            raise

    try:
        await db.execute(
            "ALTER TABLE trades ADD COLUMN last_error TEXT"
        )
    except Exception as exc:  # noqa: BLE001
        if "duplicate column" not in str(exc).lower():
            raise

    try:
        await db.execute(
            "ALTER TABLE trades ADD COLUMN order_status_detail TEXT"
        )
    except Exception as exc:  # noqa: BLE001
        if "duplicate column" not in str(exc).lower():
            raise

    # Multi-asset migration — adds asset column to signals and trades.
    # DEFAULT 'BTC' preserves all existing rows as BTC history.
    try:
        await db.execute(
            "ALTER TABLE signals ADD COLUMN asset TEXT DEFAULT 'BTC'"
        )
    except Exception as exc:  # noqa: BLE001
        if "duplicate column" not in str(exc).lower():
            raise

    try:
        await db.execute(
            "ALTER TABLE trades ADD COLUMN asset TEXT DEFAULT 'BTC'"
        )
    except Exception as exc:  # noqa: BLE001
        if "duplicate column" not in str(exc).lower():
            raise


async def init_db(db_path: str | None = None) -> None:
    """Create tables if they don't exist and seed default settings."""
    path = db_path or cfg.DB_PATH
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA_SQL)
        await _migrate(db)
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()
