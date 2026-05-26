#!/usr/bin/env python3
"""
Simple crypto price tracker
Fetches real-time prices from CoinGecko API
"""
import requests
import sys
from datetime import datetime

def get_price(coin_id):
    """Get current price from CoinGecko"""
    url = f"https://api.coingecko.com/api/v3/simple/price"
    params = {
        'ids': coin_id,
        'vs_currencies': 'usd',
        'include_24hr_change': 'true'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if coin_id in data:
                price = data[coin_id]['usd']
                change = data[coin_id].get('usd_24h_change', 0)
                
                print(f"\n💰 {coin_id.upper()}")
                print(f"Price: ${price:,.2f}")
                print(f"24h Change: {change:+.2f}%")
                return True
        print(f"❌ Error: {response.status_code}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        coin = sys.argv[1]
    else:
        coin = "bitcoin"  # Default
    
    print(f"📈 Crypto Price Tracker")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    get_price(coin)
