"""
Holder Quality Analyzer - Analyzes token holder distribution via Solana RPC.
Checks top holder %, concentration ratio, and holder count.
"""

import logging
import requests
from dataclasses import dataclass
from typing import Optional

from src.config import SOLANA_RPC, MAX_TOP_HOLDER_PCT, MAX_CONCENTRATION_RATIO, MIN_UNIQUE_HOLDERS

logger = logging.getLogger(__name__)


@dataclass
class HolderAnalysis:
    """Results of holder quality analysis."""
    token_address: str
    total_holders: int = 0
    top_holder_pct: float = 0.0
    top5_holder_pct: float = 0.0
    top10_holder_pct: float = 0.0
    concentration_ratio: float = 0.0  # Gini-like: top10 / total_supply_held
    is_quality: bool = False
    quality_score: float = 0.0  # 0-1, higher is better
    holder_distribution: list = None
    raw_top_holders: list = None

    def __post_init__(self):
        if self.holder_distribution is None:
            self.holder_distribution = []
        if self.raw_top_holders is None:
            self.raw_top_holders = []

    def passes_quality_check(self) -> bool:
        """Whether this token passes holder quality filters."""
        if self.total_holders < MIN_UNIQUE_HOLDERS:
            return False
        if self.top_holder_pct > MAX_TOP_HOLDER_PCT:
            return False
        if self.concentration_ratio > MAX_CONCENTRATION_RATIO:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "token_address": self.token_address,
            "total_holders": self.total_holders,
            "top_holder_pct": round(self.top_holder_pct, 2),
            "top5_holder_pct": round(self.top5_holder_pct, 2),
            "top10_holder_pct": round(self.top10_holder_pct, 2),
            "concentration_ratio": round(self.concentration_ratio, 4),
            "quality_score": round(self.quality_score, 3),
            "is_quality": self.is_quality,
            "passes_check": self.passes_quality_check(),
        }


class HolderAnalyzer:
    """Analyzes token holder quality using Solana RPC and supplementary APIs."""

    def __init__(self, rpc_url: str = SOLANA_RPC):
        self.rpc_url = rpc_url
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _rpc_call(self, method: str, params: list) -> Optional[dict]:
        """Make a JSON-RPC call to Solana."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        try:
            resp = self.session.post(self.rpc_url, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.error(f"RPC error: {data['error']}")
                return None
            return data.get("result")
        except requests.RequestException as e:
            logger.error(f"RPC call failed ({method}): {e}")
            return None

    def get_token_largest_accounts(self, mint_address: str) -> list[dict]:
        """Get the largest token holders using getTokenLargestAccounts RPC."""
        result = self._rpc_call("getTokenLargestAccounts", [mint_address])
        if not result:
            return []

        holders = []
        for account in result.get("value", []):
            holders.append({
                "address": account.get("address", ""),
                "amount": int(account.get("amount", "0")),
                "decimals": account.get("decimals", 0),
                "ui_amount": float(account.get("uiAmount", 0)),
                "pct": 0.0,
            })
        return holders

    def get_token_supply(self, mint_address: str) -> Optional[int]:
        """Get total token supply using getTokenSupply RPC."""
        result = self._rpc_call("getTokenSupply", [mint_address])
        if not result:
            return None
        value = result.get("value", {})
        return int(value.get("amount", "0"))

    def get_token_holders_count(self, mint_address: str) -> int:
        """Estimate holder count using getProgramAccounts (top holders only via RPC)."""
        # RPC only returns top 20 holders; use DexScreener for approximate count
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint_address}"
            resp = self.session.get(url, timeout=10)
            if resp.ok:
                data = resp.json()
                pairs = data.get("pairs", [])
                if pairs:
                    info = pairs[0].get("info", {})
                    return info.get("holders", 0)
        except Exception as e:
            logger.debug(f"Could not get holder count from DexScreener: {e}")

        # Fallback: count unique accounts from largest accounts
        holders = self.get_token_largest_accounts(mint_address)
        return len(holders)

    def analyze(self, mint_address: str) -> HolderAnalysis:
        """Perform full holder quality analysis for a token."""
        analysis = HolderAnalysis(token_address=mint_address)

        # Get total supply
        total_supply = self.get_token_supply(mint_address)
        if not total_supply or total_supply == 0:
            logger.warning(f"Could not get supply for {mint_address}")
            analysis.quality_score = 0.0
            return analysis

        # Get largest holders
        holders = self.get_token_largest_accounts(mint_address)
        analysis.raw_top_holders = holders
        analysis.total_holders = self.get_token_holders_count(mint_address)

        if not holders:
            analysis.quality_score = 0.0
            return analysis

        # Calculate percentages
        for h in holders:
            h["pct"] = (h["amount"] / total_supply * 100) if total_supply > 0 else 0

        sorted_holders = sorted(holders, key=lambda x: x["amount"], reverse=True)
        analysis.holder_distribution = sorted_holders

        # Top holder percentages
        if sorted_holders:
            analysis.top_holder_pct = sorted_holders[0]["pct"]
        if len(sorted_holders) >= 5:
            analysis.top5_holder_pct = sum(h["pct"] for h in sorted_holders[:5])
        if len(sorted_holders) >= 10:
            analysis.top10_holder_pct = sum(h["pct"] for h in sorted_holders[:10])

        # Concentration ratio (top 10 holders share)
        analysis.concentration_ratio = analysis.top10_holder_pct / 100.0

        # Calculate quality score (0-1)
        score = 0.0

        # Holder count score (more = better)
        if analysis.total_holders >= 500:
            score += 0.3
        elif analysis.total_holders >= 200:
            score += 0.2
        elif analysis.total_holders >= 100:
            score += 0.1
        elif analysis.total_holders >= 50:
            score += 0.05

        # Top holder score (less = better)
        if analysis.top_holder_pct <= 5:
            score += 0.25
        elif analysis.top_holder_pct <= 10:
            score += 0.2
        elif analysis.top_holder_pct <= 20:
            score += 0.1
        elif analysis.top_holder_pct <= 30:
            score += 0.05

        # Concentration score (less = better)
        if analysis.concentration_ratio <= 0.25:
            score += 0.25
        elif analysis.concentration_ratio <= 0.35:
            score += 0.2
        elif analysis.concentration_ratio <= 0.50:
            score += 0.1
        elif analysis.concentration_ratio <= 0.60:
            score += 0.05

        # Top 5 distribution evenness
        if len(sorted_holders) >= 5:
            pct_values = [h["pct"] for h in sorted_holders[:5]]
            max_pct = max(pct_values)
            min_pct = min(pct_values)
            if max_pct - min_pct < 5:
                score += 0.2  # Very even distribution
            elif max_pct - min_pct < 10:
                score += 0.1

        analysis.quality_score = min(score, 1.0)
        analysis.is_quality = analysis.passes_quality_check()

        logger.info(
            f"Holder analysis for {mint_address}: "
            f"holders={analysis.total_holders}, top1={analysis.top_holder_pct:.1f}%, "
            f"conc={analysis.concentration_ratio:.3f}, score={analysis.quality_score:.3f}"
        )
        return analysis

    def batch_analyze(self, mint_addresses: list[str]) -> dict[str, HolderAnalysis]:
        """Analyze multiple tokens."""
        results = {}
        for addr in mint_addresses:
            results[addr] = self.analyze(addr)
        return results
