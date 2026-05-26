"""
Momentum Tracker - Tracks price momentum, volume spikes, and buy/sell ratios.
Provides 5m/15m/1h price changes and volume analysis.
"""

import time
import logging
import requests
from dataclasses import dataclass
from typing import Optional

from src.config import DEXSCREENER_API, VOLUME_SPIKE_MULTIPLIER, MOMENTUM_WINDOWS

logger = logging.getLogger(__name__)


@dataclass
class MomentumData:
    """Momentum analysis results for a token."""
    token_address: str
    symbol: str = ""

    # Price changes
    price_change_5m: float = 0.0
    price_change_15m: float = 0.0
    price_change_1h: float = 0.0
    price_change_24h: float = 0.0

    # Volume
    volume_5m: float = 0.0
    volume_15m: float = 0.0
    volume_1h: float = 0.0
    volume_24h: float = 0.0
    volume_spike: bool = False
    volume_spike_ratio: float = 0.0

    # Buy/Sell
    buys_5m: int = 0
    sells_5m: int = 0
    buy_sell_ratio_5m: float = 0.0
    buys_1h: int = 0
    sells_1h: int = 0
    buy_sell_ratio_1h: float = 0.0

    # Momentum score
    momentum_score: float = 0.0  # -1 to 1, positive = bullish
    trend: str = "neutral"  # "bullish", "bearish", "neutral"

    # Price tracking
    current_price: float = 0.0
    price_history: list = None

    def __post_init__(self):
        if self.price_history is None:
            self.price_history = []

    @property
    def is_buying_pressure(self) -> bool:
        return self.buy_sell_ratio_5m > 1.5

    @property
    def is_volume_spike(self) -> bool:
        return self.volume_spike

    def to_dict(self) -> dict:
        return {
            "token_address": self.token_address,
            "symbol": self.symbol,
            "price_change_5m": round(self.price_change_5m, 2),
            "price_change_15m": round(self.price_change_15m, 2),
            "price_change_1h": round(self.price_change_1h, 2),
            "price_change_24h": round(self.price_change_24h, 2),
            "volume_5m": round(self.volume_5m, 2),
            "volume_1h": round(self.volume_1h, 2),
            "volume_spike": self.volume_spike,
            "volume_spike_ratio": round(self.volume_spike_ratio, 2),
            "buy_sell_ratio_5m": round(self.buy_sell_ratio_5m, 3),
            "buy_sell_ratio_1h": round(self.buy_sell_ratio_1h, 3),
            "momentum_score": round(self.momentum_score, 4),
            "trend": self.trend,
            "current_price": self.current_price,
        }


class MomentumTracker:
    """Tracks price momentum and volume for Solana tokens."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        self._price_cache: dict[str, list[tuple[float, float]]] = {}  # address -> [(timestamp, price)]

    def fetch_pair_data(self, token_address: str) -> Optional[dict]:
        """Fetch current pair data from DexScreener for a token."""
        try:
            url = f"{DEXSCREENER_API}/tokens/{token_address}"
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("pairs", [])
            if pairs:
                return pairs[0]
        except requests.RequestException as e:
            logger.error(f"Failed to fetch pair data for {token_address}: {e}")
        return None

    def track_price(self, token_address: str, price: float):
        """Record a price point for historical tracking."""
        now = time.time()
        if token_address not in self._price_cache:
            self._price_cache[token_address] = []
        self._price_cache[token_address].append((now, price))

        # Keep only last 24h of data
        cutoff = now - 86400
        self._price_cache[token_address] = [
            (t, p) for t, p in self._price_cache[token_address] if t > cutoff
        ]

    def get_historical_price_change(self, token_address: str, window_seconds: int) -> Optional[float]:
        """Calculate price change over a time window from cached data."""
        if token_address not in self._price_cache:
            return None

        history = self._price_cache[token_address]
        if len(history) < 2:
            return None

        now = time.time()
        target_time = now - window_seconds

        # Find closest price to target time
        closest = min(history, key=lambda x: abs(x[0] - target_time))
        oldest_price = closest[1]
        newest_price = history[-1][1]

        if oldest_price == 0:
            return None

        return ((newest_price - oldest_price) / oldest_price) * 100

    def analyze_momentum(self, token_address: str) -> MomentumData:
        """Full momentum analysis for a token."""
        pair = self.fetch_pair_data(token_address)
        if not pair:
            logger.warning(f"No pair data found for {token_address}")
            return MomentumData(token_address=token_address)

        base = pair.get("baseToken", {})
        price_change = pair.get("priceChange", {})
        volume = pair.get("volume", {})
        txns = pair.get("txns", {})

        current_price = float(pair.get("priceUsd", 0))
        self.track_price(token_address, current_price)

        # Extract data from API
        pc_5m = float(price_change.get("m5", 0))
        pc_1h = float(price_change.get("h1", 0))
        pc_24h = float(price_change.get("h24", 0))

        vol_5m = float(volume.get("m5", 0))
        vol_1h = float(volume.get("h1", 0))
        vol_6h = float(volume.get("h6", 0))
        vol_24h = float(volume.get("h24", 0))

        txns_5m = txns.get("m5", {})
        txns_1h = txns.get("h1", {})

        buys_5m = int(txns_5m.get("buys", 0))
        sells_5m = int(txns_5m.get("sells", 0))
        buys_1h = int(txns_1h.get("buys", 0))
        sells_1h = int(txns_1h.get("sells", 0))

        # Calculate buy/sell ratios
        bs_ratio_5m = buys_5m / sells_5m if sells_5m > 0 else (buys_5m if buys_5m > 0 else 1.0)
        bs_ratio_1h = buys_1h / sells_1h if sells_1h > 0 else (buys_1h if buys_1h > 0 else 1.0)

        # Volume spike detection: compare 5m volume to expected (24h / 288 five-min periods)
        expected_5m_vol = vol_24h / 288 if vol_24h > 0 else vol_5m
        vol_spike_ratio = vol_5m / expected_5m_vol if expected_5m_vol > 0 else 1.0
        volume_spike = vol_spike_ratio >= VOLUME_SPIKE_MULTIPLIER

        # Historical price changes from cache
        pc_15m_hist = self.get_historical_price_change(token_address, 900)
        pc_15m = pc_15m_hist if pc_15m_hist is not None else pc_5m * 2  # estimate

        # Calculate momentum score (-1 to 1)
        score = 0.0

        # Price momentum component (40% weight)
        price_score = 0.0
        if pc_5m > 0:
            price_score += 0.15
        if pc_15m > 0:
            price_score += 0.10
        if pc_1h > 0:
            price_score += 0.10
        if pc_1h > 10:
            price_score += 0.05

        if pc_5m < 0:
            price_score -= 0.15
        if pc_15m < 0:
            price_score -= 0.10
        if pc_1h < 0:
            price_score -= 0.10
        if pc_1h < -10:
            price_score -= 0.05

        # Volume component (30% weight)
        vol_score = 0.0
        if volume_spike:
            vol_score += 0.20
        if vol_5m > 1000:
            vol_score += 0.05
        if vol_1h > 10000:
            vol_score += 0.05

        # Buy pressure component (30% weight)
        buy_score = 0.0
        if bs_ratio_5m > 2.0:
            buy_score += 0.20
        elif bs_ratio_5m > 1.5:
            buy_score += 0.15
        elif bs_ratio_5m > 1.0:
            buy_score += 0.05
        elif bs_ratio_5m < 0.5:
            buy_score -= 0.20
        elif bs_ratio_5m < 0.8:
            buy_score -= 0.10

        if bs_ratio_1h > 1.5:
            buy_score += 0.10
        elif bs_ratio_1h < 0.7:
            buy_score -= 0.10

        score = price_score + vol_score + buy_score
        score = max(-1.0, min(1.0, score))

        # Determine trend
        if score > 0.3:
            trend = "bullish"
        elif score < -0.3:
            trend = "bearish"
        else:
            trend = "neutral"

        momentum = MomentumData(
            token_address=token_address,
            symbol=base.get("symbol", ""),
            price_change_5m=pc_5m,
            price_change_15m=pc_15m,
            price_change_1h=pc_1h,
            price_change_24h=pc_24h,
            volume_5m=vol_5m,
            volume_15m=vol_5m * 3,  # estimate from 5m
            volume_1h=vol_1h,
            volume_24h=vol_24h,
            volume_spike=volume_spike,
            volume_spike_ratio=vol_spike_ratio,
            buys_5m=buys_5m,
            sells_5m=sells_5m,
            buy_sell_ratio_5m=bs_ratio_5m,
            buys_1h=buys_1h,
            sells_1h=sells_1h,
            buy_sell_ratio_1h=bs_ratio_1h,
            momentum_score=score,
            trend=trend,
            current_price=current_price,
        )

        logger.info(
            f"Momentum for {momentum.symbol}: score={score:.3f} trend={trend} "
            f"5m={pc_5m:+.1f}% 1h={pc_1h:+.1f}% B/S={bs_ratio_5m:.2f} spike={volume_spike}"
        )
        return momentum

    def analyze_batch(self, token_addresses: list[str]) -> list[MomentumData]:
        """Analyze momentum for multiple tokens."""
        results = []
        for addr in token_addresses:
            try:
                m = self.analyze_momentum(addr)
                results.append(m)
            except Exception as e:
                logger.error(f"Error analyzing momentum for {addr}: {e}")
        return results
