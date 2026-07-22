import time
import httpx

PRICE_CACHE = {}
CACHE_TTL = 60  # Cache duration in seconds

CRYPTO_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "DOGE": "dogecoin",
}


async def get_live_price(symbol: str, asset_type: str) -> float:
    symbol_upper = symbol.upper()
    now = time.time()

    if symbol_upper in PRICE_CACHE:
        price, timestamp = PRICE_CACHE[symbol_upper]
        if now - timestamp < CACHE_TTL:
            return price

    price = 0.0
    async with httpx.AsyncClient() as client:
        try:
            if asset_type.lower() == "crypto":
                coin_id = CRYPTO_MAP.get(symbol_upper, symbol.lower())
                url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
                resp = await client.get(url, timeout=5.0)
                data = resp.json()
                price = float(data.get(coin_id, {}).get("usd", 0.0))
            else:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_upper}"
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = await client.get(url, headers=headers, timeout=5.0)
                data = resp.json()
                price = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
        except Exception:
            price = PRICE_CACHE.get(symbol_upper, (100.0, 0))[0]

    PRICE_CACHE[symbol_upper] = (price, now)
    return price