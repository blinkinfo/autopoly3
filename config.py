"""AutoPoly configuration — loads from environment variables with sensible defaults."""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Polymarket
# ---------------------------------------------------------------------------
POLYMARKET_PRIVATE_KEY: str | None = os.getenv("POLYMARKET_PRIVATE_KEY")
POLYMARKET_FUNDER_ADDRESS: str | None = os.getenv("POLYMARKET_FUNDER_ADDRESS")
POLYMARKET_SIGNATURE_TYPE: int = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "2"))

CLOB_HOST: str = "https://clob.polymarket.com"
GAMMA_API_HOST: str = "https://gamma-api.polymarket.com"
CHAIN_ID: int = 137

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str | None = os.getenv("TELEGRAM_CHAT_ID")

# ---------------------------------------------------------------------------
# Trading
# ---------------------------------------------------------------------------
TRADE_AMOUNT_USDC: float = float(os.getenv("TRADE_AMOUNT_USDC", "1.0"))

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH: str = os.getenv("DB_PATH", "autopoly.db")

# ---------------------------------------------------------------------------
# Demo / Sizing defaults
# ---------------------------------------------------------------------------
DEFAULT_DEMO_BANKROLL: float = 100.0
DEFAULT_SIZING_MODE: str = "fixed"

# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------
SIGNAL_THRESHOLD: float = 0.53
SIGNAL_LEAD_TIME: int = 85  # seconds before slot end to check signal

# ---------------------------------------------------------------------------
# Redemption
# ---------------------------------------------------------------------------
DATA_API_HOST: str = "https://data-api.polymarket.com"
CTF_ADDRESS: str = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_ADAPTER_ADDRESS: str = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
USDC_ADDRESS: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
WRAPPED_COLLATERAL_ADDRESS: str = "0x3A3BD7bb9528E159577F7C2e685CC81A765002E2"
RELAYER_URL: str = "https://relayer-v2.polymarket.com"
# NOTE: Builder / relayer API credentials (api key, secret, passphrase) are
# derived automatically from POLYMARKET_PRIVATE_KEY at redemption time via
# py-clob-client's create_or_derive_api_creds(). No separate env vars needed.
