import asyncio
import time

import httpx

CACHE_TTL = 60  # seconds
_cache = {}

CRYPTO_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "AVAX": "avalanche-2",
}


async def fetch_price(client, kind, sym):
    if kind == "crypto":
        coin = CRYPTO_MAP.get(sym, sym.lower())
        r = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin, "vs_currencies": "usd"},
        )
        return float(r.json()[coin]["usd"])
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + sym
    r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    meta = r.json()["chart"]["result"][0]["meta"]
    return float(meta["regularMarketPrice"])


async def get_live_price(symbol, asset_type):
    """Live USD price, or None if unavailable. Never invents a price."""
    sym = symbol.upper()
    kind = asset_type.lower()
    key = (kind, sym)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[1] < CACHE_TTL:
        return hit[0]

    price = None
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            price = await fetch_price(client, kind, sym)
    except Exception:
        price = None

    if price and price > 0:
        _cache[key] = (price, now)
        return price
    if hit:
        return hit[0]
    return None


async def get_prices(items):
    results = await asyncio.gather(
        *(get_live_price(s, t) for s, t in items)
    )
    return {s: p for (s, _), p in zip(items, results)}