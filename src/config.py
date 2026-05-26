"""Configuration constants for the trading agent."""

# API Endpoints
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex"
PUMPFUN_API = "https://frontend-api-v3.pump.fun"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# Token Filters
MIN_MARKET_CAP = 5_000      # $5K
MAX_MARKET_CAP = 50_000     # $50K
MIN_LIQUIDITY = 3_000       # $3K
MIN_TOKEN_AGE_SECONDS = 300 # 5 minutes

# Risk Management
DEFAULT_POSITION_SIZE_PCT = 0.02  # 2% of portfolio
MAX_POSITION_SIZE_PCT = 0.05      # 5% max
STOP_LOSS_PCT = 0.15              # 15% stop loss
TAKE_PROFIT_LEVELS = [0.25, 0.50, 1.0, 2.0]  # 25%, 50%, 100%, 200%
MAX_DRAWDOWN_PCT = 0.20           # 20% max drawdown
MAX_OPEN_POSITIONS = 5

# Signal Thresholds
BUY_SIGNAL_THRESHOLD = 0.65
SELL_SIGNAL_THRESHOLD = -0.40

# Holder Analysis
MAX_TOP_HOLDER_PCT = 30.0         # Top holder shouldn't own >30%
MAX_CONCENTRATION_RATIO = 0.50    # Top 10 holders <50%
MIN_UNIQUE_HOLDERS = 50

# Momentum
VOLUME_SPIKE_MULTIPLIER = 2.0     # 2x avg volume = spike
MOMENTUM_WINDOWS = [300, 900, 3600]  # 5m, 15m, 1h in seconds

# Solana
SOL_MINT = "So11111111111111111111111111111111111111112"
