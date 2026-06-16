
    def detect_bullish_divergence(self, prices, rsi_values, lookback=14):
        """Detect bullish RSI divergence (price lower low, RSI higher low)."""
        if len(prices) < lookback * 2:
            return False
        
        recent_prices = prices[-lookback:]
        recent_rsi = rsi_values[-lookback:]
        
        price_low = min(recent_prices)
        prev_price_low = min(prices[-lookback*2:-lookback])
        
        rsi_low = min(recent_rsi)
        prev_rsi_low = min(rsi_values[-lookback*2:-lookback])
        
        return price_low < prev_price_low and rsi_low > prev_rsi_low
