
    def calculate_position_size(self, account_balance, risk_pct, entry, stop_loss):
        """Calculate position size based on risk percentage."""
        risk_amount = account_balance * (risk_pct / 100)
        price_risk = abs(entry - stop_loss)
        if price_risk == 0:
            return 0
        position_size = risk_amount / price_risk
        # Cap at 10% of account
        max_size = account_balance * 0.10 / entry
        return min(position_size, max_size)
