"""
Token Scanner - Discovers new Solana tokens from DexScreener and PumpFun APIs.
Applies filters: MC $5K-$50K, liquidity >$3K, age >5min.
"""

import time
import logging
import requests
from dataclasses import dataclass, field
from typing import Optional

from src.config import (
    DEXSCREENER_API, PUMPFUN_API,
    MIN_MARKET_CAP, MAX_MARKET_CAP, MIN_LIQUIDITY, MIN_TOKEN_AGE_SECONDS,
)

logger = logging.getLogger(__name__)


@dataclass
class TokenInfo:
    """Represents a scanned token with its market data."""
    address: str
    symbol: str
    name: str
    chain: str = "solana"
    market_cap: float = 0.0
    liquidity: float = 0.0
    price_usd: float = 0.0
    volume_24h: float = 0.0
    volume_5m: float = 0.0
    price_change_5m: float = 0.0
    price_change_1h: float = 0.0
    price_change_24h: float = 0.0
    age_seconds: int = 0
    created_at: float = 0.0
    pair_address: str = ""
    dex: str = ""
    source: str = ""
    buy_count_5m: int = 0
    sell_count_5m: int = 0
    txns_5m_buys: int = 0
    txns_5m_sells: int = 0
    holders: int = 0
    raw_data: dict = field(default_factory=dict)

    @property
    def age_minutes(self) -> float:
        return self.age_seconds / 60.0

    @property
    def is_pumpfun(self) -> bool:
        return self.source == "pumpfun"

    def passes_filters(self) -> bool:
        """Check if token passes all scanner filters."""
        if self.market_cap < MIN_MARKET_CAP or self.market_cap > MAX_MARKET_CAP:
            return False
        if self.liquidity < MIN_LIQUIDITY:
            return False
        if self.age_seconds < MIN_TOKEN_AGE_SECONDS:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "symbol": self.symbol,
            "name": self.name,
            "market_cap": self.market_cap,
            "liquidity": self.liquidity,
            "price_usd": self.price_usd,
            "volume_24h": self.volume_24h,
            "volume_5m": self.volume_5m,
            "price_change_5m": self.price_change_5m,
            "price_change_1h": self.price_change_1h,
            "age_minutes": round(self.age_minutes, 1),
            "source": self.source,
            "dex": self.dex,
            "pair_address": self.pair_address,
            "buy_count_5m": self.txns_5m_buys,
            "sell_count_5m": self.txns_5m_sells,
        }


class TokenScanner:
    """Scans DexScreener and PumpFun for new Solana tokens meeting filter criteria."""

    def __init__(self, min_mc: float = MIN_MARKET_CAP, max_mc: float = MAX_MARKET_CAP,
                 min_liq: float = MIN_LIQUIDITY, min_age: int = MIN_TOKEN_AGE_SECONDS):
        self.min_mc = min_mc
        self.max_mc = max_mc
        self.min_liq = min_liq
        self.min_age = min_age
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        self._seen_addresses: set = set()

    def scan_dexscreener(self) -> list[TokenInfo]:
        """Fetch new Solana pairs from DexScreener API."""
        tokens = []
        try:
            # Search for new Solana tokens
            url = f"{DEXSCREENER_API}/search?q=solana"
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            pairs = data.get("pairs", [])
            logger.info(f"DexScreener returned {len(pairs)} pairs")

            now = time.time()
            for pair in pairs:
                try:
                    if pair.get("chainId") != "solana":
                        continue

                    base = pair.get("baseToken", {})
                    price_change = pair.get("priceChange", {})
                    txns = pair.get("txns", {})
                    txns_5m = txns.get("m5", {})

                    created_at = pair.get("pairCreatedAt", 0)
                    if created_at:
                        age = int(now - created_at / 1000)
                    else:
                        age = 999999

                    mc = float(pair.get("marketCap") or pair.get("fdv") or 0)
                    liq = float(pair.get("liquidity", {}).get("usd", 0))

                    token = TokenInfo(
                        address=base.get("address", ""),
                        symbol=base.get("symbol", "UNKNOWN"),
                        name=base.get("name", "Unknown"),
                        market_cap=mc,
                        liquidity=liq,
                        price_usd=float(pair.get("priceUsd", 0)),
                        volume_24h=float(pair.get("volume", {}).get("h24", 0)),
                        volume_5m=float(pair.get("volume", {}).get("m5", 0)),
                        price_change_5m=float(price_change.get("m5", 0)),
                        price_change_1h=float(price_change.get("h1", 0)),
                        price_change_24h=float(price_change.get("h24", 0)),
                        age_seconds=age,
                        created_at=created_at,
                        pair_address=pair.get("pairAddress", ""),
                        dex=pair.get("dexId", ""),
                        source="dexscreener",
                        txns_5m_buys=int(txns_5m.get("buys", 0)),
                        txns_5m_sells=int(txns_5m.get("sells", 0)),
                        raw_data=pair,
                    )
                    tokens.append(token)
                except (KeyError, ValueError, TypeError) as e:
                    logger.debug(f"Error parsing pair: {e}")
                    continue

        except requests.RequestException as e:
            logger.error(f"DexScreener API error: {e}")

        logger.info(f"Scanned {len(tokens)} tokens from DexScreener")
        return tokens

    def scan_pumpfun(self) -> list[TokenInfo]:
        """Fetch new tokens from PumpFun API."""
        tokens = []
        try:
            # PumpFun recent tokens endpoint
            url = f"{PUMPFUN_API}/coins?offset=0&limit=50&sort=created_timestamp&order=DESC&includeNsfw=false"
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            coins = data if isinstance(data, list) else data.get("data", data.get("coins", []))
            logger.info(f"PumpFun returned {len(coins)} coins")

            now = time.time()
            for coin in coins:
                try:
                    created = coin.get("created_timestamp", 0)
                    if created > 1e12:
                        created = created / 1000
                    age = int(now - created) if created else 999999

                    mc = float(coin.get("usd_market_cap", 0) or coin.get("market_cap", 0) or 0)
                    # PumpFun MC is often in SOL, convert if needed
                    if mc < 100 and mc > 0:
                        mc = mc * 200  # rough SOL->USD

                    token = TokenInfo(
                        address=coin.get("mint", coin.get("address", "")),
                        symbol=coin.get("symbol", "UNKNOWN"),
                        name=coin.get("name", "Unknown"),
                        market_cap=mc,
                        liquidity=float(coin.get("virtual_sol_reserves", 0)) * 200 / 1e9 if coin.get("virtual_sol_reserves") else 0,
                        price_usd=float(coin.get("usd_price", 0) or 0),
                        volume_24h=0,
                        age_seconds=age,
                        created_at=created,
                        source="pumpfun",
                        dex="pumpfun",
                        raw_data=coin,
                    )
                    tokens.append(token)
                except (KeyError, ValueError, TypeError) as e:
                    logger.debug(f"Error parsing PumpFun coin: {e}")
                    continue

        except requests.RequestException as e:
            logger.error(f"PumpFun API error: {e}")

        logger.info(f"Scanned {len(tokens)} tokens from PumpFun")
        return tokens

    def scan_all(self, deduplicate: bool = True) -> list[TokenInfo]:
        """Scan both APIs and return filtered, deduplicated tokens."""
        all_tokens = []

        dex_tokens = self.scan_dexscreener()
        all_tokens.extend(dex_tokens)

        pump_tokens = self.scan_pumpfun()
        all_tokens.extend(pump_tokens)

        if deduplicate:
            seen = set()
            deduped = []
            for t in all_tokens:
                if t.address and t.address not in seen:
                    seen.add(t.address)
                    deduped.append(t)
            all_tokens = deduped

        # Apply filters
        filtered = [t for t in all_tokens if t.passes_filters()]
        logger.info(f"After filtering: {len(filtered)} tokens pass all criteria")

        return filtered

    def scan_with_retries(self, max_retries: int = 3) -> list[TokenInfo]:
        """Scan with retry logic."""
        for attempt in range(max_retries):
            try:
                return self.scan_all()
            except Exception as e:
                logger.warning(f"Scan attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        logger.error("All scan attempts failed")
        return []

    def get_token_details(self, address: str) -> Optional[TokenInfo]:
        """Get detailed info for a specific token address."""
        try:
            url = f"{DEXSCREENER_API}/tokens/{address}"
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            pairs = data.get("pairs", [])
            if not pairs:
                return None

            pair = pairs[0]
            base = pair.get("baseToken", {})
            price_change = pair.get("priceChange", {})
            txns = pair.get("txns", {})
            txns_5m = txns.get("m5", {})

            created_at = pair.get("pairCreatedAt", 0)
            now = time.time()
            age = int(now - created_at / 1000) if created_at else 999999

            return TokenInfo(
                address=base.get("address", address),
                symbol=base.get("symbol", "UNKNOWN"),
                name=base.get("name", "Unknown"),
                market_cap=float(pair.get("marketCap") or pair.get("fdv") or 0),
                liquidity=float(pair.get("liquidity", {}).get("usd", 0)),
                price_usd=float(pair.get("priceUsd", 0)),
                volume_24h=float(pair.get("volume", {}).get("h24", 0)),
                volume_5m=float(pair.get("volume", {}).get("m5", 0)),
                price_change_5m=float(price_change.get("m5", 0)),
                price_change_1h=float(price_change.get("h1", 0)),
                price_change_24h=float(price_change.get("h24", 0)),
                age_seconds=age,
                pair_address=pair.get("pairAddress", ""),
                dex=pair.get("dexId", ""),
                source="dexscreener",
                txns_5m_buys=int(txns_5m.get("buys", 0)),
                txns_5m_sells=int(txns_5m.get("sells", 0)),
                raw_data=pair,
            )
        except requests.RequestException as e:
            logger.error(f"Error fetching token details for {address}: {e}")
            return None
