"""
Risk Manager - Position sizing, stop-loss, take-profit, and max drawdown protection.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from src.config import (
    DEFAULT_POSITION_SIZE_PCT, MAX_POSITION_SIZE_PCT,
    STOP_LOSS_PCT, TAKE_PROFIT_LEVELS, MAX_DRAWDOWN_PCT, MAX_OPEN_POSITIONS,
)

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open or planned trading position."""
    token_address: str
    symbol: str
    entry_price: float
    size_usd: float
    stop_loss_price: float = 0.0
    take_profit_levels: list = None
    current_price: float = 0.0
    pnl_pct: float = 0.0
    pnl_usd: float = 0.0
    status: str = "open"  # "open", "closed", "stopped"
    entry_time: float = 0.0

    def __post_init__(self):
        if self.take_profit_levels is None:
            self.take_profit_levels = []

    @property
    def is_stop_hit(self) -> bool:
        return self.current_price > 0 and self.current_price <= self.stop_loss_price

    def update_price(self, price: float):
        """Update current price and P&L."""
        self.current_price = price
        if self.entry_price > 0:
            self.pnl_pct = ((price - self.entry_price) / self.entry_price) * 100
            self.pnl_usd = (price - self.entry_price) * (self.size_usd / self.entry_price)

    def to_dict(self) -> dict:
        return {
            "token_address": self.token_address,
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "size_usd": round(self.size_usd, 2),
            "stop_loss_price": self.stop_loss_price,
            "take_profit_levels": self.take_profit_levels,
            "pnl_pct": round(self.pnl_pct, 2),
            "pnl_usd": round(self.pnl_usd, 2),
            "status": self.status,
        }


class RiskManager:
    """Manages trading risk: position sizing, stops, and portfolio limits."""

    def __init__(self, portfolio_value: float = 10000.0,
                 max_position_pct: float = MAX_POSITION_SIZE_PCT,
                 default_position_pct: float = DEFAULT_POSITION_SIZE_PCT,
                 stop_loss_pct: float = STOP_LOSS_PCT,
                 max_drawdown_pct: float = MAX_DRAWDOWN_PCT,
                 max_positions: int = MAX_OPEN_POSITIONS):
        self.portfolio_value = portfolio_value
        self.initial_portfolio = portfolio_value
        self.max_position_pct = max_position_pct
        self.default_position_pct = default_position_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_positions = max_positions
        self.positions: dict[str, Position] = {}
        self.closed_positions: list[Position] = []
        self.total_realized_pnl: float = 0.0

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    @property
    def current_drawdown(self) -> float:
        """Current drawdown from peak portfolio value."""
        if self.initial_portfolio == 0:
            return 0.0
        return max(0, (self.initial_portfolio - self.portfolio_value) / self.initial_portfolio)

    @property
    def is_drawdown_breached(self) -> bool:
        return self.current_drawdown >= self.max_drawdown_pct

    @property
    def available_capital(self) -> float:
        """Capital available for new positions."""
        committed = sum(p.size_usd for p in self.positions.values())
        return max(0, self.portfolio_value - committed)

    def calculate_position_size(self, risk_level: str = "medium",
                                confidence: float = 0.5) -> float:
        """Calculate position size based on risk level and confidence."""
        if self.is_drawdown_breached:
            logger.warning("Max drawdown breached — no new positions")
            return 0.0

        if self.open_position_count >= self.max_positions:
            logger.warning(f"Max positions ({self.max_positions}) reached")
            return 0.0

        # Base size from portfolio
        base_pct = self.default_position_pct

        # Adjust by risk level
        risk_multipliers = {"low": 1.2, "medium": 1.0, "high": 0.6}
        multiplier = risk_multipliers.get(risk_level, 1.0)

        # Adjust by confidence
        confidence_multiplier = 0.5 + confidence  # 0.5 to 1.5

        # Kelly-inspired sizing
        position_pct = base_pct * multiplier * confidence_multiplier
        position_pct = min(position_pct, self.max_position_pct)

        size = self.portfolio_value * position_pct

        # Don't exceed available capital
        size = min(size, self.available_capital)

        # Minimum position check
        if size < 10:
            return 0.0

        logger.info(f"Position size: ${size:.2f} ({position_pct:.1%} of portfolio)")
        return round(size, 2)

    def calculate_stop_loss(self, entry_price: float, risk_level: str = "medium") -> float:
        """Calculate stop-loss price."""
        stop_multipliers = {"low": 0.12, "medium": 0.15, "high": 0.20}
        pct = stop_multipliers.get(risk_level, self.stop_loss_pct)
        stop_price = entry_price * (1 - pct)
        return round(stop_price, 10)

    def calculate_take_profits(self, entry_price: float) -> list[dict]:
        """Calculate take-profit levels with prices and sizes to sell."""
        levels = []
        sell_pcts = [0.25, 0.25, 0.25, 0.25]  # Sell 25% at each level

        for i, tp_pct in enumerate(TAKE_PROFIT_LEVELS):
            tp_price = entry_price * (1 + tp_pct)
            levels.append({
                "level": i + 1,
                "target_pct": tp_pct * 100,
                "price": round(tp_price, 10),
                "sell_pct": sell_pcts[i] * 100 if i < len(sell_pcts) else 25,
            })

        return levels

    def open_position(self, token_address: str, symbol: str,
                      entry_price: float, risk_level: str = "medium",
                      confidence: float = 0.5) -> Optional[Position]:
        """Open a new position with proper risk management."""
        size = self.calculate_position_size(risk_level, confidence)
        if size <= 0:
            return None

        stop_loss = self.calculate_stop_loss(entry_price, risk_level)
        take_profits = self.calculate_take_profits(entry_price)

        position = Position(
            token_address=token_address,
            symbol=symbol,
            entry_price=entry_price,
            size_usd=size,
            stop_loss_price=stop_loss,
            take_profit_levels=take_profits,
            current_price=entry_price,
        )

        self.positions[token_address] = position
        logger.info(
            f"Opened position: {symbol} ${size:.2f} @ {entry_price} "
            f"SL={stop_loss:.10f} TPs={[tp['price'] for tp in take_profits]}"
        )
        return position

    def close_position(self, token_address: str, exit_price: float,
                       reason: str = "manual") -> Optional[Position]:
        """Close a position and calculate realized P&L."""
        position = self.positions.pop(token_address, None)
        if not position:
            logger.warning(f"No open position for {token_address}")
            return None

        position.current_price = exit_price
        position.update_price(exit_price)
        position.status = "stopped" if reason == "stop_loss" else "closed"

        self.total_realized_pnl += position.pnl_usd
        self.portfolio_value += position.pnl_usd
        self.closed_positions.append(position)

        logger.info(
            f"Closed position: {position.symbol} @ {exit_price} "
            f"PnL={position.pnl_pct:+.2f}% (${position.pnl_usd:+.2f}) reason={reason}"
        )
        return position

    def check_positions(self, price_map: dict[str, float]) -> list[dict]:
        """Check all open positions against current prices. Returns actions needed."""
        actions = []

        for addr, position in list(self.positions.items()):
            price = price_map.get(addr)
            if price is None:
                continue

            position.update_price(price)

            # Check stop loss
            if position.is_stop_hit:
                actions.append({
                    "action": "CLOSE",
                    "token_address": addr,
                    "symbol": position.symbol,
                    "reason": "stop_loss",
                    "current_price": price,
                    "pnl_pct": position.pnl_pct,
                })
                continue

            # Check take profit levels
            for tp in position.take_profit_levels:
                if price >= tp["price"] and not tp.get("hit", False):
                    tp["hit"] = True
                    actions.append({
                        "action": "PARTIAL_SELL",
                        "token_address": addr,
                        "symbol": position.symbol,
                        "reason": f"take_profit_{tp['level']}",
                        "sell_pct": tp["sell_pct"],
                        "target_price": tp["price"],
                        "current_price": price,
                    })

        # Check max drawdown
        if self.is_drawdown_breached:
            actions.append({
                "action": "CLOSE_ALL",
                "reason": "max_drawdown",
                "drawdown_pct": self.current_drawdown * 100,
            })

        return actions

    def get_portfolio_summary(self) -> dict:
        """Get current portfolio status."""
        total_unrealized = sum(p.pnl_usd for p in self.positions.values())
        positions_data = [p.to_dict() for p in self.positions.values()]

        return {
            "portfolio_value": round(self.portfolio_value, 2),
            "initial_portfolio": self.initial_portfolio,
            "open_positions": self.open_position_count,
            "max_positions": self.max_positions,
            "available_capital": round(self.available_capital, 2),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "total_realized_pnl": round(self.total_realized_pnl, 2),
            "current_drawdown_pct": round(self.current_drawdown * 100, 2),
            "max_drawdown_pct": self.max_drawdown_pct * 100,
            "drawdown_breached": self.is_drawdown_breached,
            "positions": positions_data,
        }

    def calculate_risk_reward(self, entry_price: float, risk_level: str = "medium") -> dict:
        """Calculate risk/reward metrics for a potential trade."""
        stop_loss = self.calculate_stop_loss(entry_price, risk_level)
        take_profits = self.calculate_take_profits(entry_price)

        risk_pct = ((entry_price - stop_loss) / entry_price) * 100

        rewards = []
        for tp in take_profits:
            reward_pct = ((tp["price"] - entry_price) / entry_price) * 100
            rr_ratio = reward_pct / risk_pct if risk_pct > 0 else 0
            rewards.append({
                "level": tp["level"],
                "reward_pct": round(reward_pct, 2),
                "risk_reward_ratio": round(rr_ratio, 2),
            })

        return {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "risk_pct": round(risk_pct, 2),
            "take_profits": rewards,
        }
