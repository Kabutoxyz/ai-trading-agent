"""
Signal Generator - Combines momentum, holder quality, volume, and market cap
to generate actionable buy/sell signals with confidence scores.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.config import BUY_SIGNAL_THRESHOLD, SELL_SIGNAL_THRESHOLD
from src.scanner import TokenInfo
from src.analyzer import HolderAnalysis, HolderAnalyzer
from src.momentum import MomentumData, MomentumTracker

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """A trading signal with confidence and reasoning."""
    token_address: str
    symbol: str
    signal_type: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0 to 1
    momentum_score: float = 0.0
    holder_score: float = 0.0
    volume_score: float = 0.0
    mc_score: float = 0.0
    combined_score: float = 0.0
    reasons: list = None
    risk_level: str = "medium"  # "low", "medium", "high"
    suggested_action: str = ""

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []

    def to_dict(self) -> dict:
        return {
            "token_address": self.token_address,
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "confidence": round(self.confidence, 4),
            "momentum_score": round(self.momentum_score, 4),
            "holder_score": round(self.holder_score, 4),
            "volume_score": round(self.volume_score, 4),
            "mc_score": round(self.mc_score, 4),
            "combined_score": round(self.combined_score, 4),
            "risk_level": self.risk_level,
            "reasons": self.reasons,
            "suggested_action": self.suggested_action,
        }


class SignalGenerator:
    """Generates trading signals from multiple analysis inputs."""

    # Weights for combining scores
    WEIGHTS = {
        "momentum": 0.35,
        "holder_quality": 0.25,
        "volume": 0.20,
        "market_cap": 0.20,
    }

    def __init__(self, buy_threshold: float = BUY_SIGNAL_THRESHOLD,
                 sell_threshold: float = SELL_SIGNAL_THRESHOLD):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.momentum_tracker = MomentumTracker()

    def score_momentum(self, momentum: MomentumData) -> tuple[float, list[str]]:
        """Score momentum data. Returns (score, reasons)."""
        score = 0.0
        reasons = []

        # Price changes
        if momentum.price_change_5m > 5:
            score += 0.3
            reasons.append(f"Strong 5m pump: {momentum.price_change_5m:+.1f}%")
        elif momentum.price_change_5m > 0:
            score += 0.1

        if momentum.price_change_1h > 20:
            score += 0.2
            reasons.append(f"1h momentum: {momentum.price_change_1h:+.1f}%")
        elif momentum.price_change_1h > 5:
            score += 0.1

        # Volume spike
        if momentum.volume_spike:
            score += 0.25
            reasons.append(f"Volume spike: {momentum.volume_spike_ratio:.1f}x avg")

        # Buy pressure
        if momentum.buy_sell_ratio_5m > 2.0:
            score += 0.25
            reasons.append(f"Strong buying: B/S={momentum.buy_sell_ratio_5m:.2f}")
        elif momentum.buy_sell_ratio_5m > 1.5:
            score += 0.15
        elif momentum.buy_sell_ratio_5m < 0.5:
            score -= 0.3
            reasons.append(f"Heavy selling: B/S={momentum.buy_sell_ratio_5m:.2f}")

        # Negative signals
        if momentum.price_change_5m < -10:
            score -= 0.3
            reasons.append(f"5m dump: {momentum.price_change_5m:+.1f}%")
        if momentum.price_change_1h < -30:
            score -= 0.3
            reasons.append(f"1h crash: {momentum.price_change_1h:+.1f}%")

        return max(-1.0, min(1.0, score)), reasons

    def score_holder_quality(self, analysis: HolderAnalysis) -> tuple[float, list[str]]:
        """Score holder quality. Returns (score, reasons)."""
        score = 0.0
        reasons = []

        if analysis.total_holders >= 200:
            score += 0.3
            reasons.append(f"Good holder count: {analysis.total_holders}")
        elif analysis.total_holders >= 100:
            score += 0.15
        elif analysis.total_holders < 30:
            score -= 0.2
            reasons.append(f"Low holder count: {analysis.total_holders}")

        if analysis.top_holder_pct <= 10:
            score += 0.3
            reasons.append(f"Healthy top holder: {analysis.top_holder_pct:.1f}%")
        elif analysis.top_holder_pct <= 20:
            score += 0.1
        elif analysis.top_holder_pct > 30:
            score -= 0.3
            reasons.append(f"Whale risk: top holder owns {analysis.top_holder_pct:.1f}%")

        if analysis.concentration_ratio <= 0.30:
            score += 0.2
            reasons.append(f"Well distributed: conc={analysis.concentration_ratio:.2f}")
        elif analysis.concentration_ratio > 0.50:
            score -= 0.2
            reasons.append(f"Concentrated: top10 own {analysis.concentration_ratio:.0%}")

        if analysis.quality_score > 0.6:
            score += 0.2

        return max(-1.0, min(1.0, score)), reasons

    def score_volume(self, momentum: MomentumData) -> tuple[float, list[str]]:
        """Score volume quality. Returns (score, reasons)."""
        score = 0.0
        reasons = []

        if momentum.volume_5m > 10000:
            score += 0.4
            reasons.append(f"High 5m volume: ${momentum.volume_5m:,.0f}")
        elif momentum.volume_5m > 5000:
            score += 0.2
        elif momentum.volume_5m > 1000:
            score += 0.1
        elif momentum.volume_5m < 100:
            score -= 0.2
            reasons.append(f"Very low volume: ${momentum.volume_5m:,.0f}")

        if momentum.volume_1h > 50000:
            score += 0.3
            reasons.append(f"Strong 1h volume: ${momentum.volume_1h:,.0f}")
        elif momentum.volume_1h > 10000:
            score += 0.15

        if momentum.volume_spike:
            score += 0.3
            reasons.append(f"Volume spike {momentum.volume_spike_ratio:.1f}x")

        return max(-1.0, min(1.0, score)), reasons

    def score_market_cap(self, token: TokenInfo) -> tuple[float, list[str]]:
        """Score market cap positioning. Returns (score, reasons)."""
        score = 0.0
        reasons = []

        mc = token.market_cap

        # Sweet spot: $10K-$30K
        if 10000 <= mc <= 30000:
            score += 0.5
            reasons.append(f"Sweet spot MC: ${mc:,.0f}")
        elif 5000 <= mc < 10000:
            score += 0.3
            reasons.append(f"Micro MC: ${mc:,.0f} (higher risk/reward)")
        elif 30000 < mc <= 50000:
            score += 0.2
            reasons.append(f"Upper range MC: ${mc:,.0f}")
        elif mc > 50000:
            score -= 0.1

        # Liquidity relative to MC
        if token.market_cap > 0:
            liq_ratio = token.liquidity / token.market_cap
            if liq_ratio > 0.3:
                score += 0.2
                reasons.append(f"Healthy liquidity ratio: {liq_ratio:.1%}")
            elif liq_ratio < 0.1:
                score -= 0.2
                reasons.append(f"Low liquidity ratio: {liq_ratio:.1%}")

        return max(-1.0, min(1.0, score)), reasons

    def generate_signal(self, token: TokenInfo,
                        momentum: Optional[MomentumData] = None,
                        holder_analysis: Optional[HolderAnalysis] = None) -> Signal:
        """Generate a trading signal from all available data."""
        reasons = []

        # Get momentum data if not provided
        if momentum is None:
            momentum = self.momentum_tracker.analyze_momentum(token.address)

        # Score each component
        m_score, m_reasons = self.score_momentum(momentum)
        reasons.extend(m_reasons)

        h_score, h_reasons = (0.0, [])
        if holder_analysis:
            h_score, h_reasons = self.score_holder_quality(holder_analysis)
            reasons.extend(h_reasons)

        v_score, v_reasons = self.score_volume(momentum)
        reasons.extend(v_reasons)

        mc_score, mc_reasons = self.score_market_cap(token)
        reasons.extend(mc_reasons)

        # Weighted combination
        combined = (
            m_score * self.WEIGHTS["momentum"] +
            h_score * self.WEIGHTS["holder_quality"] +
            v_score * self.WEIGHTS["volume"] +
            mc_score * self.WEIGHTS["market_cap"]
        )

        # Determine signal type
        if combined >= self.buy_threshold:
            signal_type = "BUY"
        elif combined <= self.sell_threshold:
            signal_type = "SELL"
        else:
            signal_type = "HOLD"

        # Confidence based on absolute combined score
        confidence = min(abs(combined), 1.0)

        # Risk level
        risk = "medium"
        if token.market_cap < 10000 or token.age_seconds < 600:
            risk = "high"
        elif holder_analysis and holder_analysis.quality_score > 0.6 and token.market_cap > 20000:
            risk = "low"

        # Suggested action
        action = ""
        if signal_type == "BUY":
            action = f"Consider entry at ${momentum.current_price:.8f}"
            if risk == "high":
                action += " — small position, tight stop"
        elif signal_type == "SELL":
            action = "Avoid entry or exit existing position"
        else:
            action = "Monitor for better entry conditions"

        signal = Signal(
            token_address=token.address,
            symbol=token.symbol,
            signal_type=signal_type,
            confidence=confidence,
            momentum_score=m_score,
            holder_score=h_score,
            volume_score=v_score,
            mc_score=mc_score,
            combined_score=combined,
            reasons=reasons,
            risk_level=risk,
            suggested_action=action,
        )

        logger.info(
            f"Signal for {token.symbol}: {signal_type} (conf={confidence:.2f}) "
            f"combined={combined:.3f} risk={risk}"
        )
        return signal

    def generate_signals(self, tokens: list[TokenInfo],
                         holder_analyses: Optional[dict[str, HolderAnalysis]] = None) -> list[Signal]:
        """Generate signals for multiple tokens, sorted by confidence."""
        signals = []
        for token in tokens:
            ha = holder_analyses.get(token.address) if holder_analyses else None
            try:
                signal = self.generate_signal(token, holder_analysis=ha)
                signals.append(signal)
            except Exception as e:
                logger.error(f"Error generating signal for {token.symbol}: {e}")

        # Sort by confidence descending
        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals
