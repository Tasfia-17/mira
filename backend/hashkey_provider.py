"""
High-level HashKey provider built on top of `hashkey_capabilities`.

Goal:
  - normalize live HashKey / HyperIndex capability responses into app-friendly
    Python dicts before we wire them into the existing Ava backend flows
  - keep field names explicit so we can later map them to feed / spotlight /
    confirm / portfolio screens with minimal frontend changes
"""

from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from plugins_func.functions import hashkey_capabilities as hk


CHAIN_NAME = "hashkey"
USDT_ADDRESS = "0xF1B50eD67A9e2CC94Ad3c477779E2d4cBfFf9029"
GECKO_TERMINAL_BASE = "https://api.geckoterminal.com/api/v2"
GECKO_NETWORK_ID = "hashkey"
FAST_MARKET_FEES = (3000, 500)
DEFAULT_CHART_POINTS = 12
MAX_TRANSFER_PAGES = 6
CHART_TRANSFER_PAGES = 2
PNL_TRANSFER_PAGES = 2
PORTFOLIO_TRADE_STATS_PAGES = 2
DEFAULT_WALLET_ACTIVITY_ITEMS = 50
WALLET_CACHE_TTL_SECONDS = 15
TRANSFER_CACHE_TTL_SECONDS = 15
SPOTLIGHT_CACHE_TTL_SECONDS = 30
GECKO_CACHE_TTL_SECONDS = 180

_TTL_CACHE: dict[tuple, tuple[float, object]] = {}


def _is_hex_address(value: str) -> bool:
    text = str(value or "").strip()
    return text.startswith("0x") and len(text) == 42


def _http_json(url: str, *, timeout: int = 20) -> dict | list:
    headers = {
        "Accept": "application/json",
        "User-Agent": "AvaBox-HashKey-Market/1.0",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode() if exc.fp else ""
        raise hk.HashKeyApiError(f"HTTP {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise hk.HashKeyApiError(f"Network error for {url}: {exc}") from exc


def _interval_step_seconds(interval: str) -> int:
    value = str(interval or "60").strip().lower()
    if value == "s1":
        return 1
    if value == "1":
        return 60
    if value == "5":
        return 5 * 60
    if value == "60":
        return 60 * 60
    if value == "240":
        return 4 * 60 * 60
    if value == "1440":
        return 24 * 60 * 60
    return 60 * 60


def _parse_timestamp(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def _raw_to_decimal(raw_amount: int | str, decimals: int | str) -> Decimal:
    try:
        raw_value = Decimal(str(raw_amount))
        decimals_value = int(decimals)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return Decimal("0")

    if decimals_value < 0:
        decimals_value = 0
    return raw_value / (Decimal(10) ** decimals_value)


def _human_amount(raw_amount: int | str, decimals: int | str) -> str:
    amount = _raw_to_decimal(raw_amount, decimals)
    text = format(amount.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _decimal_to_float(value: Decimal | str | int | float | None) -> float | None:
    try:
        numeric = Decimal(str(value))
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return None
    return float(numeric)


def _address_eq(left: str, right: str) -> bool:
    return str(left or "").strip().lower() == str(right or "").strip().lower()


def _signed_wallet_amount(entry: dict, wallet_address: str) -> Decimal:
    token = entry.get("token") or {}
    total = entry.get("total") or {}
    amount = _raw_to_decimal(total.get("value") or "0", token.get("decimals") or 0)
    wallet_lower = str(wallet_address or "").strip().lower()
    from_hash = str((entry.get("from") or {}).get("hash") or "").strip().lower()
    to_hash = str((entry.get("to") or {}).get("hash") or "").strip().lower()
    if to_hash == wallet_lower and from_hash != wallet_lower:
        return amount
    if from_hash == wallet_lower and to_hash != wallet_lower:
        return -amount
    return Decimal("0")


def _wallet_direction(entry: dict, wallet_address: str) -> str:
    signed = _signed_wallet_amount(entry, wallet_address)
    if signed > 0:
        return "in"
    if signed < 0:
        return "out"
    return "other"


def _quote_token_price_in_usdt(token_address: str, *, decimals: int) -> tuple[float | None, dict | None]:
    return _quote_token_price_in_usdt_cached(str(token_address or "").strip().lower(), int(decimals or 0))


def _quote_hsk_price_in_usdt() -> tuple[float | None, dict | None]:
    return _quote_hsk_price_in_usdt_cached()


@lru_cache(maxsize=1)
def _quote_hsk_price_in_usdt_cached() -> tuple[float | None, dict | None]:
    best = hk.quote_best_exact_input(hk.HYPERINDEX_WHSK, USDT_ADDRESS, 10**18, fees=FAST_MARKET_FEES)
    if not best:
        return None, None
    amount_out = _raw_to_decimal(best["amount_out"], 6)
    return _decimal_to_float(amount_out), best


@lru_cache(maxsize=256)
def _quote_token_price_in_usdt_cached(token_address: str, decimals: int) -> tuple[float | None, dict | None]:
    amount_in = 10 ** max(int(decimals or 0), 0)
    best = hk.quote_best_exact_input(token_address, USDT_ADDRESS, amount_in, fees=FAST_MARKET_FEES)
    if not best:
        return None, None
    amount_out = _raw_to_decimal(best["amount_out"], 6)
    return _decimal_to_float(amount_out), best


def _token_price_usd(
    token_address: str,
    *,
    decimals: int,
    hsk_usdt: float | None = None,
) -> float | None:
    normalized = str(token_address or "").strip().lower()
    if not normalized:
        return None
    if normalized == USDT_ADDRESS.lower():
        return 1.0
    if normalized in {hk.HYPERINDEX_WHSK.lower(), hk.HASHKEY_NATIVE_ADDRESS.lower()}:
        if hsk_usdt is None:
            hsk_usdt, _ = _quote_hsk_price_in_usdt()
        return hsk_usdt

    try:
        direct_price, _ = _quote_token_price_in_usdt(normalized, decimals=decimals)
    except Exception:
        direct_price = None
    if direct_price is not None:
        return direct_price

    if hsk_usdt is None:
        hsk_usdt, _ = _quote_hsk_price_in_usdt()
    if not hsk_usdt:
        return None
    try:
        via_hsk_price, _ = _quote_token_price_via_hsk(normalized, decimals=decimals)
    except Exception:
        via_hsk_price = None
    return via_hsk_price


def _fetch_wallet_transfer_entries(
    wallet_address: str,
    *,
    max_pages: int = MAX_TRANSFER_PAGES,
    items_count: int = DEFAULT_WALLET_ACTIVITY_ITEMS,
) -> list[dict]:
    cache_key = ("wallet_transfers", str(wallet_address or "").strip().lower(), int(max_pages or 0), int(items_count or 0))
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached
    page_params = {"items_count": items_count}
    entries: list[dict] = []
    for _ in range(max(1, int(max_pages or 1))):
        payload = hk.get_address_token_transfers(wallet_address, page_params=page_params)
        page_items = payload.get("items") or []
        if not page_items:
            break
        entries.extend([item for item in page_items if isinstance(item, dict)])
        next_page = payload.get("next_page_params")
        if not next_page:
            break
        page_params = next_page
    return _ttl_cache_set(cache_key, entries, ttl=TRANSFER_CACHE_TTL_SECONDS)


def _fetch_pool_transfer_entries(
    pool_address: str,
    *,
    max_pages: int = CHART_TRANSFER_PAGES,
    items_count: int = DEFAULT_WALLET_ACTIVITY_ITEMS,
) -> list[dict]:
    normalized_pool = str(pool_address or "").strip().lower()
    cache_key = ("pool_transfers", normalized_pool, int(max_pages or 0), int(items_count or 0))
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached
    page_params = {"items_count": items_count}
    entries: list[dict] = []
    for _ in range(max(1, int(max_pages or 1))):
        payload = hk.get_address_token_transfers(pool_address, page_params=page_params)
        page_items = payload.get("items") or []
        if not page_items:
            break
        entries.extend([item for item in page_items if isinstance(item, dict)])
        next_page = payload.get("next_page_params")
        if not next_page:
            break
        page_params = next_page
    return _ttl_cache_set(cache_key, entries, ttl=TRANSFER_CACHE_TTL_SECONDS)


def _quote_token_price_via_hsk(token_address: str, *, decimals: int) -> tuple[float | None, dict | None]:
    return _quote_token_price_via_hsk_cached(str(token_address or "").strip().lower(), int(decimals or 0))


@lru_cache(maxsize=256)
def _quote_token_price_via_hsk_cached(token_address: str, decimals: int) -> tuple[float | None, dict | None]:
    hsk_usdt, _ = _quote_hsk_price_in_usdt()
    if not hsk_usdt:
        return None, None
    amount_in = 10 ** max(int(decimals or 0), 0)
    best = hk.quote_best_exact_input(token_address, hk.HYPERINDEX_WHSK, amount_in, fees=FAST_MARKET_FEES)
    if not best:
        return None, None
    token_in_hsk = _raw_to_decimal(best["amount_out"], 18)
    return _decimal_to_float(token_in_hsk * Decimal(str(hsk_usdt))), best


def _blank_trade_stats() -> dict:
    return {
        "position_qty": Decimal("0"),
        "cost_basis_usd": Decimal("0"),
        "realized_pnl_usd": Decimal("0"),
        "total_bought_qty": Decimal("0"),
        "total_bought_usd": Decimal("0"),
        "total_sold_qty": Decimal("0"),
        "total_sold_usd": Decimal("0"),
        "priced_buy_count": 0,
        "priced_sell_count": 0,
        "priced_event_count": 0,
        "first_buy_ts": 0,
        "last_buy_ts": 0,
        "first_sell_ts": 0,
        "last_sell_ts": 0,
    }


def _update_trade_timestamp(stats: dict, *, ts: int, side: str) -> None:
    if ts <= 0:
        return
    if side == "buy":
        if not int(stats.get("first_buy_ts") or 0) or ts < int(stats.get("first_buy_ts") or 0):
            stats["first_buy_ts"] = ts
        if ts > int(stats.get("last_buy_ts") or 0):
            stats["last_buy_ts"] = ts
        return
    if not int(stats.get("first_sell_ts") or 0) or ts < int(stats.get("first_sell_ts") or 0):
        stats["first_sell_ts"] = ts
    if ts > int(stats.get("last_sell_ts") or 0):
        stats["last_sell_ts"] = ts


def _wallet_trade_groups(
    wallet_address: str,
    *,
    max_pages: int = PNL_TRANSFER_PAGES,
) -> list[dict]:
    cache_key = ("wallet_trade_groups", str(wallet_address or "").strip().lower(), int(max_pages or 0))
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached

    raw_entries = _fetch_wallet_transfer_entries(wallet_address, max_pages=max_pages)
    groups = {}
    for entry in raw_entries:
        tx_hash = str(entry.get("transaction_hash") or "").strip().lower()
        if not tx_hash:
            continue
        token = entry.get("token") or {}
        token_addr = str(token.get("address_hash") or "").strip().lower()
        if not token_addr:
            continue
        signed_amount = _signed_wallet_amount(entry, wallet_address)
        if signed_amount == 0:
            continue
        timestamp = _parse_timestamp(entry.get("timestamp"))
        group = groups.setdefault(
            tx_hash,
            {
                "timestamp": timestamp,
                "method": str(entry.get("method") or "").strip(),
                "deltas": {},
            },
        )
        if timestamp > int(group.get("timestamp") or 0):
            group["timestamp"] = timestamp
        group["deltas"][token_addr] = group["deltas"].get(token_addr, Decimal("0")) + signed_amount

    ordered = sorted(groups.values(), key=lambda row: int(row.get("timestamp") or 0))
    return _ttl_cache_set(cache_key, ordered, ttl=TRANSFER_CACHE_TTL_SECONDS)


def _wallet_trade_stats_map(
    wallet_address: str,
    *,
    max_pages: int = PNL_TRANSFER_PAGES,
) -> dict:
    cache_key = ("wallet_trade_stats", str(wallet_address or "").strip().lower(), int(max_pages or 0))
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached

    hsk_usdt, _ = _quote_hsk_price_in_usdt()
    stats_map: dict[str, dict] = {}
    for group in _wallet_trade_groups(wallet_address, max_pages=max_pages):
        deltas = group.get("deltas") or {}
        timestamp = int(group.get("timestamp") or 0)
        usdt_delta = Decimal(str(deltas.get(USDT_ADDRESS.lower()) or "0"))
        whsk_delta = Decimal(str(deltas.get(hk.HYPERINDEX_WHSK.lower()) or "0"))

        counter_usd = None
        if usdt_delta != 0:
            counter_usd = abs(usdt_delta)
        elif whsk_delta != 0 and hsk_usdt is not None:
            counter_usd = abs(whsk_delta) * Decimal(str(hsk_usdt))

        for token_addr, target_delta_raw in deltas.items():
            token_addr_text = str(token_addr or "").strip().lower()
            if not token_addr_text or token_addr_text == hk.HASHKEY_NATIVE_ADDRESS.lower():
                continue
            target_delta = Decimal(str(target_delta_raw or "0"))
            if target_delta == 0:
                continue

            stats = stats_map.setdefault(token_addr_text, _blank_trade_stats())
            trade_qty = abs(target_delta)
            if trade_qty <= 0:
                continue

            if target_delta > 0:
                if counter_usd is None:
                    continue
                stats["position_qty"] += trade_qty
                stats["cost_basis_usd"] += counter_usd
                stats["total_bought_qty"] += trade_qty
                stats["total_bought_usd"] += counter_usd
                stats["priced_buy_count"] += 1
                stats["priced_event_count"] += 1
                _update_trade_timestamp(stats, ts=timestamp, side="buy")
            else:
                avg_cost = (stats["cost_basis_usd"] / stats["position_qty"]) if stats["position_qty"] > 0 else Decimal("0")
                if counter_usd is not None:
                    stats["realized_pnl_usd"] += counter_usd - (avg_cost * trade_qty)
                    stats["total_sold_qty"] += trade_qty
                    stats["total_sold_usd"] += counter_usd
                    stats["priced_sell_count"] += 1
                    stats["priced_event_count"] += 1
                    _update_trade_timestamp(stats, ts=timestamp, side="sell")
                qty_reduction = min(trade_qty, stats["position_qty"])
                stats["cost_basis_usd"] -= avg_cost * qty_reduction
                if stats["cost_basis_usd"] < 0:
                    stats["cost_basis_usd"] = Decimal("0")
                stats["position_qty"] -= qty_reduction
                if stats["position_qty"] < 0:
                    stats["position_qty"] = Decimal("0")

    return _ttl_cache_set(cache_key, stats_map, ttl=TRANSFER_CACHE_TTL_SECONDS)


def _estimate_pool_liquidity_usd(
    pool_address: str,
    *,
    token_address: str,
    token_decimals: int,
    token_usd_price: float,
    quote_token_address: str,
    quote_token_decimals: int,
    quote_token_usd_price: float,
) -> float | None:
    try:
        token_reserve_raw = hk.erc20_balance_of(token_address, pool_address)
        quote_reserve_raw = hk.erc20_balance_of(quote_token_address, pool_address)
    except Exception:
        return None

    token_reserve = _raw_to_decimal(token_reserve_raw, token_decimals)
    quote_reserve = _raw_to_decimal(quote_reserve_raw, quote_token_decimals)
    token_side_usd = token_reserve * Decimal(str(token_usd_price))
    quote_side_usd = quote_reserve * Decimal(str(quote_token_usd_price))
    if token_side_usd <= 0 and quote_side_usd > 0:
        return _decimal_to_float(quote_side_usd * Decimal("2"))
    total = token_side_usd + quote_side_usd
    return _decimal_to_float(total)


def _build_flat_chart(*, price_usd: float | None, interval: str, points: int = DEFAULT_CHART_POINTS) -> tuple[list[float], list[int]]:
    if not price_usd or price_usd <= 0:
        return [], []
    count = max(2, int(points or DEFAULT_CHART_POINTS))
    step = _interval_step_seconds(interval)
    end_ts = int(time.time())
    times = [end_ts - step * (count - 1 - idx) for idx in range(count)]
    prices = [float(price_usd)] * count
    return prices, times


def _select_primary_pool(pools: list[dict], preferred_fee: int | None = None) -> dict | None:
    if not pools:
        return None
    if preferred_fee is not None:
        for pool in pools:
            if int(pool.get("fee") or 0) == int(preferred_fee):
                return pool
    return pools[0]


def _historical_close_chart_from_pool_transfers(
    pool_address: str,
    *,
    base_token_address: str,
    base_decimals: int,
    quote_token_address: str,
    quote_decimals: int,
    quote_token_usd_price: float,
    interval: str,
    points: int = DEFAULT_CHART_POINTS,
) -> tuple[list[float], list[int]]:
    if str(interval or "60") != "60":
        return [], []
    pool_text = str(pool_address or "").strip()
    if not (pool_text.startswith("0x") and len(pool_text) == 42):
        return [], []

    now_ts = int(time.time())
    bucket_size = 60 * 60
    lookback_seconds = bucket_size * max(12, int(points or DEFAULT_CHART_POINTS))
    cutoff_ts = now_ts - lookback_seconds
    base_token = str(base_token_address or "").strip().lower()
    quote_token = str(quote_token_address or "").strip().lower()

    tx_rows = {}
    for entry in _fetch_pool_transfer_entries(pool_text, max_pages=CHART_TRANSFER_PAGES):
        token = entry.get("token") or {}
        token_address = str(token.get("address_hash") or "").strip().lower()
        if token_address not in {base_token, quote_token}:
            continue

        tx_hash = str(entry.get("transaction_hash") or "").strip().lower()
        ts = _parse_timestamp(entry.get("timestamp"))
        if not tx_hash or not ts or ts < cutoff_ts:
            continue

        amount = _raw_to_decimal((entry.get("total") or {}).get("value") or "0", token.get("decimals") or 0)
        if amount <= 0:
            continue

        row = tx_rows.setdefault(tx_hash, {"timestamp": ts, "base": Decimal("0"), "quote": Decimal("0")})
        if ts > int(row.get("timestamp") or 0):
            row["timestamp"] = ts
        if token_address == base_token:
            row["base"] += amount
        elif token_address == quote_token:
            row["quote"] += amount

    bucket_closes = {}
    for row in tx_rows.values():
        base_amount = row.get("base") or Decimal("0")
        quote_amount = row.get("quote") or Decimal("0")
        ts = int(row.get("timestamp") or 0)
        if ts <= 0 or base_amount <= 0 or quote_amount <= 0:
            continue
        price_quote = quote_amount / base_amount
        price_usd = _decimal_to_float(price_quote * Decimal(str(quote_token_usd_price)))
        if not price_usd or price_usd <= 0:
            continue

        bucket_ts = (ts // bucket_size) * bucket_size
        existing = bucket_closes.get(bucket_ts)
        if existing is None or ts > existing["timestamp"]:
            bucket_closes[bucket_ts] = {
                "timestamp": ts,
                "bucket_ts": bucket_ts,
                "price_usd": float(price_usd),
            }

    if not bucket_closes:
        return [], []

    sorted_buckets = [bucket_closes[key] for key in sorted(bucket_closes.keys())]
    sorted_buckets = sorted_buckets[-max(2, int(points or DEFAULT_CHART_POINTS)):]
    prices = [item["price_usd"] for item in sorted_buckets]
    times = [item["bucket_ts"] for item in sorted_buckets]
    return prices, times


def _spotlight_pair_metrics(token_address: str, *, token_decimals: int) -> dict:
    normalized = str(token_address or "").strip()

    if normalized.lower() == USDT_ADDRESS.lower():
        pools = hk.list_v3_pools(hk.HYPERINDEX_WHSK, USDT_ADDRESS, fees=FAST_MARKET_FEES)
        hsk_usdt, _ = _quote_hsk_price_in_usdt()
        primary_pool = _select_primary_pool(pools, 3000)
        liquidity_usd = None
        if primary_pool:
            liquidity_usd = _estimate_pool_liquidity_usd(
                primary_pool["pool_address"],
                token_address=USDT_ADDRESS,
                token_decimals=6,
                token_usd_price=1.0,
                quote_token_address=hk.HYPERINDEX_WHSK,
                quote_token_decimals=18,
                quote_token_usd_price=(hsk_usdt or 0.0),
            )
        return {
            "pair_label": "HSK",
            "pair_address": primary_pool["pool_address"] if primary_pool else "",
            "pair_quote_symbol": "HSK",
            "pair_quote_address": hk.HYPERINDEX_WHSK,
            "price_usd": 1.0,
            "best_quote": None,
            "liquidity_usd": liquidity_usd,
        }

    if normalized.lower() == hk.HYPERINDEX_WHSK.lower():
        price_usd, quote = _quote_hsk_price_in_usdt()
        pools = hk.list_v3_pools(hk.HYPERINDEX_WHSK, USDT_ADDRESS, fees=FAST_MARKET_FEES)
        primary_pool = _select_primary_pool(pools, int(quote["fee"]) if quote else None)
        liquidity_usd = None
        if primary_pool and price_usd:
            liquidity_usd = _estimate_pool_liquidity_usd(
                primary_pool["pool_address"],
                token_address=hk.HYPERINDEX_WHSK,
                token_decimals=18,
                token_usd_price=price_usd,
                quote_token_address=USDT_ADDRESS,
                quote_token_decimals=6,
                quote_token_usd_price=1.0,
            )
        return {
            "pair_label": "HSK / USDT",
            "pair_address": primary_pool["pool_address"] if primary_pool else "",
            "pair_quote_symbol": "USDT",
            "pair_quote_address": USDT_ADDRESS,
            "price_usd": price_usd,
            "best_quote": quote,
            "liquidity_usd": liquidity_usd,
        }

    direct_price, direct_quote = _quote_token_price_in_usdt(normalized, decimals=token_decimals)
    direct_pools = hk.list_v3_pools(normalized, USDT_ADDRESS, fees=FAST_MARKET_FEES)
    if direct_quote or direct_pools:
        primary_pool = _select_primary_pool(direct_pools, int(direct_quote["fee"]) if direct_quote else None)
        liquidity_usd = None
        if primary_pool:
            liquidity_usd = _estimate_pool_liquidity_usd(
                primary_pool["pool_address"],
                token_address=normalized,
                token_decimals=token_decimals,
                token_usd_price=(direct_price or 0.0),
                quote_token_address=USDT_ADDRESS,
                quote_token_decimals=6,
                quote_token_usd_price=1.0,
            )
        return {
            "pair_label": "USDT",
            "pair_address": primary_pool["pool_address"] if primary_pool else "",
            "pair_quote_symbol": "USDT",
            "pair_quote_address": USDT_ADDRESS,
            "price_usd": direct_price,
            "best_quote": direct_quote,
            "liquidity_usd": liquidity_usd,
        }

    via_hsk_price, via_hsk_quote = _quote_token_price_via_hsk(normalized, decimals=token_decimals)
    hsk_pools = hk.list_v3_pools(normalized, hk.HYPERINDEX_WHSK, fees=FAST_MARKET_FEES)
    primary_pool = _select_primary_pool(hsk_pools, int(via_hsk_quote["fee"]) if via_hsk_quote else None)
    hsk_usdt, _ = _quote_hsk_price_in_usdt()
    liquidity_usd = None
    if primary_pool and hsk_usdt:
        liquidity_usd = _estimate_pool_liquidity_usd(
            primary_pool["pool_address"],
            token_address=normalized,
            token_decimals=token_decimals,
            token_usd_price=(via_hsk_price or 0.0),
            quote_token_address=hk.HYPERINDEX_WHSK,
            quote_token_decimals=18,
            quote_token_usd_price=hsk_usdt,
        )
    return {
        "pair_label": "HSK",
        "pair_address": primary_pool["pool_address"] if primary_pool else "",
        "pair_quote_symbol": "HSK",
        "pair_quote_address": hk.HYPERINDEX_WHSK,
        "price_usd": via_hsk_price,
        "best_quote": via_hsk_quote,
        "liquidity_usd": liquidity_usd,
    }


def _token_summary_from_search_item(item: dict) -> dict:
    address = str(item.get("address_hash") or "").strip()
    symbol = str(item.get("symbol") or "?").strip() or "?"
    return {
        "addr": address,
        "token_id": address,
        "chain": CHAIN_NAME,
        "symbol": symbol,
        "name": str(item.get("name") or symbol).strip() or symbol,
        "token_type": str(item.get("token_type") or "").strip(),
        "verified": bool(item.get("is_smart_contract_verified")),
        "icon_url": str(item.get("icon_url") or "").strip(),
        "source": "hashkey_blockscout",
        "price": "N/A",
        "change_24h": "N/A",
        "volume_24h": "N/A",
        "market_cap": "N/A",
    }


def search_tokens(keyword: str, *, limit: int = 20) -> list[dict]:
    items = hk.search_tokens(keyword)
    return [_token_summary_from_search_item(item) for item in items[:limit]]


def get_token_metadata(address: str) -> dict:
    normalized = str(address or "").strip().lower()
    try:
        return copy.deepcopy(_get_token_metadata_cached(normalized))
    except Exception:
        return _fallback_token_metadata(normalized)


@lru_cache(maxsize=512)
def _get_token_detail_cached(address: str) -> dict:
    return hk.get_token_detail(address)


def _fallback_token_metadata(address: str) -> dict:
    normalized = str(address or "").strip().lower()
    snapshot = _gt_best_snapshot_for_token(normalized)
    symbol = str((snapshot or {}).get("symbol") or "?").strip() or "?"
    return {
        "addr": normalized,
        "token_id": normalized,
        "chain": CHAIN_NAME,
        "symbol": symbol,
        "name": symbol,
        "decimals": 18,
        "holders_count": 0,
        "icon_url": "",
        "verified": False,
        "source": "hashkey_fallback",
    }


@lru_cache(maxsize=512)
def _get_token_metadata_cached(address: str) -> dict:
    detail = _get_token_detail_cached(address)
    return {
        "addr": str(detail.get("address_hash") or address).strip(),
        "token_id": str(detail.get("address_hash") or address).strip(),
        "chain": CHAIN_NAME,
        "symbol": str(detail.get("symbol") or "?").strip() or "?",
        "name": str(detail.get("name") or "").strip(),
        "decimals": int(detail.get("decimals") or 0),
        "holders_count": int(detail.get("holders_count") or 0),
        "icon_url": str(detail.get("icon_url") or "").strip(),
        "verified": True,
        "source": "hashkey_blockscout",
    }


def get_token_market_snapshot(address: str) -> dict:
    normalized = str(address or "").strip().lower()
    cache_key = ("token_market_snapshot", normalized)
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached

    gecko_snapshot = _gt_best_snapshot_for_token(normalized)
    if gecko_snapshot is not None:
        return _ttl_cache_set(cache_key, gecko_snapshot, ttl=TRANSFER_CACHE_TTL_SECONDS)

    token_meta = get_token_metadata(address)
    decimals = int(token_meta.get("decimals") or 0)
    metrics = _spotlight_pair_metrics(token_meta["addr"], token_decimals=decimals)

    total_supply = None
    try:
        detail = _get_token_detail_cached(token_meta["addr"])
    except Exception:
        detail = {}
    raw_total_supply = detail.get("total_supply")
    if raw_total_supply not in (None, ""):
        total_supply = _raw_to_decimal(raw_total_supply, decimals)

    market_cap_usd = None
    if total_supply is not None and metrics.get("price_usd") is not None:
        market_cap_usd = _decimal_to_float(total_supply * Decimal(str(metrics["price_usd"])))

    pair_quote_symbol = str(metrics.get("pair_quote_symbol") or "USDT")
    symbol = token_meta["symbol"]
    if symbol == pair_quote_symbol:
        pair_display = f"{symbol} / HSK"
    else:
        pair_display = f"{symbol} / {pair_quote_symbol}"

    snapshot = {
        "addr": token_meta["addr"],
        "token_id": token_meta["token_id"],
        "chain": CHAIN_NAME,
        "symbol": symbol,
        "name": token_meta["name"],
        "decimals": decimals,
        "verified": token_meta["verified"],
        "holders_count": token_meta["holders_count"],
        "pair": pair_display,
        "pair_address": str(metrics.get("pair_address") or ""),
        "pair_quote_symbol": pair_quote_symbol,
        "pair_quote_address": str(metrics.get("pair_quote_address") or ""),
        "price_usd": metrics.get("price_usd"),
        "liquidity_usd": metrics.get("liquidity_usd"),
        "market_cap_usd": market_cap_usd,
        "volume_24h_usd": None,
        "change_24h": None,
        "source": "hashkey_live",
    }
    return _ttl_cache_set(cache_key, snapshot, ttl=TRANSFER_CACHE_TTL_SECONDS)


def get_wallet_portfolio(wallet_address: str) -> dict:
    balances = hk.get_address_token_balances(wallet_address)
    holdings = []
    for entry in balances:
        if not isinstance(entry, dict):
            continue
        token = entry.get("token") or {}
        raw_value = str(entry.get("value") or "0")
        decimals = int(token.get("decimals") or 0)
        holdings.append(
            {
                "addr": str(token.get("address_hash") or "").strip(),
                "token_id": str(token.get("address_hash") or "").strip(),
                "chain": CHAIN_NAME,
                "symbol": str(token.get("symbol") or "?").strip() or "?",
                "name": str(token.get("name") or "").strip(),
                "decimals": decimals,
                "raw_balance": raw_value,
                "balance": _human_amount(raw_value, decimals),
                "icon_url": str(token.get("icon_url") or "").strip(),
                "holders_count": int(token.get("holders_count") or 0),
            }
        )
    return {
        "wallet_address": wallet_address,
        "chain": CHAIN_NAME,
        "holdings": holdings,
    }


def get_wallet_holdings_valued(wallet_address: str) -> dict:
    normalized_wallet = str(wallet_address or "").strip().lower()
    cache_key = ("wallet_holdings_valued", normalized_wallet)
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached
    portfolio = get_wallet_portfolio(wallet_address)
    holdings = list(portfolio.get("holdings") or [])
    native_raw_balance = hk.rpc_get_balance(wallet_address)
    hsk_usdt, _ = _quote_hsk_price_in_usdt()
    native_balance = _raw_to_decimal(native_raw_balance, 18)
    if native_balance > 0:
        holdings.append(
            {
                "addr": hk.HASHKEY_NATIVE_ADDRESS,
                "token_id": hk.HASHKEY_NATIVE_ADDRESS,
                "chain": CHAIN_NAME,
                "symbol": hk.HASHKEY_NATIVE_SYMBOL,
                "name": "HashKey Chain Native",
                "decimals": 18,
                "raw_balance": str(native_raw_balance),
                "balance": _human_amount(native_raw_balance, 18),
                "icon_url": "",
                "holders_count": 0,
                "is_native": True,
            }
        )

    enriched = []
    total_value_usd = Decimal("0")
    priced_count = 0
    for holding in holdings:
        decimals = int(holding.get("decimals") or 0)
        balance_decimal = _raw_to_decimal(holding.get("raw_balance") or "0", decimals)
        price_usd = _token_price_usd(holding.get("addr") or "", decimals=decimals, hsk_usdt=hsk_usdt)
        value_usd = None
        if price_usd is not None:
            value_usd = _decimal_to_float(balance_decimal * Decimal(str(price_usd)))
            if value_usd is not None:
                total_value_usd += Decimal(str(value_usd))
                priced_count += 1
        enriched.append(
            {
                **holding,
                "balance_decimal": balance_decimal,
                "price_usd": price_usd,
                "value_usd": value_usd,
            }
        )

    enriched.sort(
        key=lambda row: Decimal(str(row.get("value_usd"))) if row.get("value_usd") is not None else Decimal("-1"),
        reverse=True,
    )
    result = {
        "wallet_address": wallet_address,
        "chain": CHAIN_NAME,
        "holdings": enriched,
        "total_value_usd": _decimal_to_float(total_value_usd),
        "priced_holdings_count": priced_count,
        "native_balance": _human_amount(native_raw_balance, 18),
        "native_price_usd": hsk_usdt,
    }
    return _ttl_cache_set(cache_key, result, ttl=WALLET_CACHE_TTL_SECONDS)


def get_wallet_overview(wallet_address: str) -> dict:
    snapshot = get_wallet_holdings_valued(wallet_address)
    raw_entries = _fetch_wallet_transfer_entries(wallet_address, max_pages=3)
    unique_txs = {
        str(entry.get("transaction_hash") or "").strip().lower()
        for entry in raw_entries
        if str(entry.get("transaction_hash") or "").strip()
    }
    return {
        "wallet_address": wallet_address,
        "chain": CHAIN_NAME,
        "total_value_usd": snapshot.get("total_value_usd"),
        "holdings_count": len(snapshot.get("holdings") or []),
        "priced_holdings_count": snapshot.get("priced_holdings_count", 0),
        "native_balance": snapshot.get("native_balance"),
        "trade_count": len(unique_txs),
    }


def get_wallet_holdings_with_pnl(wallet_address: str) -> dict:
    snapshot = get_wallet_holdings_valued(wallet_address)
    stats_map = _wallet_trade_stats_map(wallet_address, max_pages=PORTFOLIO_TRADE_STATS_PAGES)

    enriched = []
    total_value_usd = Decimal("0")
    total_pnl_usd = Decimal("0")
    total_cost_usd = Decimal("0")
    has_pnl = False

    for holding in snapshot.get("holdings") or []:
        addr = str(holding.get("addr") or "").strip().lower()
        current_balance = Decimal(str(holding.get("balance_decimal") or "0"))
        current_value_usd = holding.get("value_usd")
        current_value_decimal = (
            Decimal(str(current_value_usd))
            if current_value_usd not in (None, "")
            else None
        )
        if current_value_decimal is not None:
            total_value_usd += current_value_decimal

        stats = stats_map.get(addr) or _blank_trade_stats()
        position_qty = Decimal(str(stats.get("position_qty") or "0"))
        cost_basis_usd = Decimal(str(stats.get("cost_basis_usd") or "0"))
        realized_pnl_usd = Decimal(str(stats.get("realized_pnl_usd") or "0"))
        avg_cost_usd = (cost_basis_usd / position_qty) if position_qty > 0 else None
        remaining_cost_usd = (
            avg_cost_usd * current_balance
            if avg_cost_usd is not None and current_balance > 0
            else None
        )
        unrealized_pnl_usd = (
            current_value_decimal - remaining_cost_usd
            if current_value_decimal is not None and remaining_cost_usd is not None
            else None
        )
        total_token_pnl = realized_pnl_usd
        if unrealized_pnl_usd is not None:
            total_token_pnl += unrealized_pnl_usd

        pnl_percent = None
        if remaining_cost_usd is not None and remaining_cost_usd > 0 and unrealized_pnl_usd is not None:
            pnl_percent = _decimal_to_float((unrealized_pnl_usd / remaining_cost_usd) * Decimal("100"))

        has_token_pnl = bool(
            int(stats.get("priced_event_count") or 0)
            or realized_pnl_usd != 0
            or unrealized_pnl_usd is not None
        )
        if has_token_pnl:
            has_pnl = True
            total_pnl_usd += total_token_pnl
            if remaining_cost_usd is not None:
                total_cost_usd += remaining_cost_usd

        enriched.append(
            {
                **holding,
                "avg_cost_usd": _decimal_to_float(avg_cost_usd) if avg_cost_usd is not None else None,
                "remaining_cost_usd": _decimal_to_float(remaining_cost_usd) if remaining_cost_usd is not None else None,
                "realized_pnl_usd": _decimal_to_float(realized_pnl_usd),
                "unrealized_pnl_usd": _decimal_to_float(unrealized_pnl_usd) if unrealized_pnl_usd is not None else None,
                "total_pnl_usd": _decimal_to_float(total_token_pnl) if has_token_pnl else None,
                "pnl_percent": pnl_percent,
                "priced_event_count": int(stats.get("priced_event_count") or 0),
                "current_balance": _decimal_to_float(current_balance),
            }
        )

    enriched.sort(
        key=lambda row: Decimal(str(row.get("value_usd"))) if row.get("value_usd") is not None else Decimal("-1"),
        reverse=True,
    )

    total_pnl_pct = None
    if has_pnl and total_cost_usd > 0:
        total_pnl_pct = _decimal_to_float((total_pnl_usd / total_cost_usd) * Decimal("100"))

    return {
        "wallet_address": wallet_address,
        "chain": CHAIN_NAME,
        "holdings": enriched,
        "total_value_usd": _decimal_to_float(total_value_usd),
        "total_pnl_usd": _decimal_to_float(total_pnl_usd) if has_pnl else None,
        "total_pnl_pct": total_pnl_pct,
        "has_pnl": has_pnl,
    }


def get_wallet_activity(wallet_address: str, *, limit: int = 20) -> dict:
    payload = hk.get_address_token_transfers(wallet_address, page_params={"items_count": max(limit, 20)})
    items = []
    for entry in (payload.get("items") or [])[:limit]:
        if not isinstance(entry, dict):
            continue
        token = entry.get("token") or {}
        total = entry.get("total") or {}
        signed_amount = _signed_wallet_amount(entry, wallet_address)
        amount_usd = None
        token_address = str(token.get("address_hash") or "").strip()
        decimals = int(token.get("decimals") or 0)
        if _address_eq(token_address, USDT_ADDRESS):
            amount_usd = abs(float(signed_amount))
        elif _address_eq(token_address, hk.HYPERINDEX_WHSK):
            hsk_usdt, _ = _quote_hsk_price_in_usdt()
            if hsk_usdt is not None:
                amount_usd = abs(float(signed_amount * Decimal(str(hsk_usdt))))
        items.append(
            {
                "tx_hash": str(entry.get("transaction_hash") or "").strip(),
                "timestamp": str(entry.get("timestamp") or "").strip(),
                "method": str(entry.get("method") or "").strip(),
                "transfer_type": str(entry.get("type") or "").strip(),
                "token_symbol": str(token.get("symbol") or "?").strip() or "?",
                "token_address": token_address,
                "amount_raw": str(total.get("value") or "0"),
                "amount": _human_amount(total.get("value") or "0", total.get("decimals") or 0),
                "signed_amount": format(signed_amount.normalize(), "f") if signed_amount else "0",
                "direction": _wallet_direction(entry, wallet_address),
                "amount_usd": amount_usd,
                "from": str((entry.get("from") or {}).get("hash") or "").strip(),
                "to": str((entry.get("to") or {}).get("hash") or "").strip(),
            }
        )
    return {
        "wallet_address": wallet_address,
        "chain": CHAIN_NAME,
        "items": items,
        "next_page_params": payload.get("next_page_params"),
    }


def get_wallet_token_pnl(wallet_address: str, token_address: str) -> dict:
    token_meta = get_token_metadata(token_address)
    target_address = str(token_meta.get("addr") or token_address).strip().lower()
    hsk_usdt, _ = _quote_hsk_price_in_usdt()
    current_price_usd = _token_price_usd(target_address, decimals=int(token_meta.get("decimals") or 0), hsk_usdt=hsk_usdt)

    current_balance = Decimal("0")
    holdings_snapshot = get_wallet_holdings_valued(wallet_address)
    for holding in holdings_snapshot.get("holdings") or []:
        if _address_eq(holding.get("addr"), target_address):
            current_balance = Decimal(str(holding.get("balance_decimal") or "0"))
            break

    stats_map = _wallet_trade_stats_map(wallet_address, max_pages=PNL_TRANSFER_PAGES)
    stats = stats_map.get(target_address) or _blank_trade_stats()
    position_qty = Decimal(str(stats.get("position_qty") or "0"))
    cost_basis_usd = Decimal(str(stats.get("cost_basis_usd") or "0"))
    realized_pnl_usd = Decimal(str(stats.get("realized_pnl_usd") or "0"))
    priced_buy_count = int(stats.get("priced_buy_count") or 0)
    priced_sell_count = int(stats.get("priced_sell_count") or 0)
    priced_event_count = int(stats.get("priced_event_count") or 0)
    total_bought_qty = Decimal(str(stats.get("total_bought_qty") or "0"))
    total_bought_usd = Decimal(str(stats.get("total_bought_usd") or "0"))
    total_sold_qty = Decimal(str(stats.get("total_sold_qty") or "0"))
    total_sold_usd = Decimal(str(stats.get("total_sold_usd") or "0"))

    remaining_cost_usd = None
    unrealized_pnl_usd = None
    current_value_usd = None
    if current_price_usd is not None:
        current_value_usd = current_balance * Decimal(str(current_price_usd))
    if current_balance > 0 and position_qty > 0:
        avg_cost = cost_basis_usd / position_qty if position_qty > 0 else Decimal("0")
        remaining_cost_usd = avg_cost * current_balance
    if current_value_usd is not None and remaining_cost_usd is not None:
        unrealized_pnl_usd = current_value_usd - remaining_cost_usd

    total_pnl_usd = realized_pnl_usd
    if unrealized_pnl_usd is not None:
        total_pnl_usd += unrealized_pnl_usd

    pnl_percent = None
    if remaining_cost_usd and remaining_cost_usd > 0 and unrealized_pnl_usd is not None:
        pnl_percent = _decimal_to_float((unrealized_pnl_usd / remaining_cost_usd) * Decimal("100"))

    average_purchase_price_usd = None
    if total_bought_qty > 0:
        average_purchase_price_usd = _decimal_to_float(total_bought_usd / total_bought_qty)

    average_sold_price_usd = None
    if total_sold_qty > 0:
        average_sold_price_usd = _decimal_to_float(total_sold_usd / total_sold_qty)

    return {
        "wallet_address": wallet_address,
        "chain": CHAIN_NAME,
        "token_address": token_meta["addr"],
        "token_symbol": token_meta["symbol"],
        "current_balance": _decimal_to_float(current_balance),
        "current_price_usd": current_price_usd,
        "current_value_usd": _decimal_to_float(current_value_usd) if current_value_usd is not None else None,
        "realized_pnl_usd": _decimal_to_float(realized_pnl_usd),
        "unrealized_pnl_usd": _decimal_to_float(unrealized_pnl_usd) if unrealized_pnl_usd is not None else None,
        "total_pnl_usd": _decimal_to_float(total_pnl_usd),
        "remaining_cost_usd": _decimal_to_float(remaining_cost_usd) if remaining_cost_usd is not None else None,
        "pnl_percent": pnl_percent,
        "priced_buy_count": priced_buy_count,
        "priced_sell_count": priced_sell_count,
        "priced_event_count": priced_event_count,
        "average_purchase_price_usd": average_purchase_price_usd,
        "total_purchased_usd": _decimal_to_float(total_bought_usd) if total_bought_usd > 0 else None,
        "average_sold_price_usd": average_sold_price_usd,
        "total_sold_usd": _decimal_to_float(total_sold_usd) if total_sold_usd > 0 else None,
        "first_purchase_time": int(stats.get("first_buy_ts") or 0) or None,
        "last_purchase_time": int(stats.get("last_buy_ts") or 0) or None,
        "first_sold_time": int(stats.get("first_sell_ts") or 0) or None,
        "last_sold_time": int(stats.get("last_sell_ts") or 0) or None,
    }


def _ttl_cache_get(key: tuple) -> object | None:
    entry = _TTL_CACHE.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if expires_at <= time.time():
        _TTL_CACHE.pop(key, None)
        return None
    return copy.deepcopy(value)


def _ttl_cache_set(key: tuple, value: object, *, ttl: int) -> object:
    _TTL_CACHE[key] = (time.time() + max(1, int(ttl or 1)), copy.deepcopy(value))
    return copy.deepcopy(value)


def _gt_token_address_from_id(token_id: str) -> str:
    text = str(token_id or "").strip().lower()
    prefix = f"{GECKO_NETWORK_ID}_"
    if text.startswith(prefix):
        return text[len(prefix):]
    return text


def _gt_pool_symbols(name: str) -> tuple[str, str]:
    text = str(name or "").strip()
    if " / " not in text:
        return "?", "?"
    left, right = text.split(" / ", 1)
    return left.strip() or "?", right.strip() or "?"


def _gt_get_token_pools(token_address: str) -> list[dict]:
    normalized = str(token_address or "").strip().lower()
    if not _is_hex_address(normalized):
        return []
    cache_key = ("gt_token_pools", normalized)
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached
    url = f"{GECKO_TERMINAL_BASE}/networks/{GECKO_NETWORK_ID}/tokens/{normalized}/pools"
    try:
        payload = _http_json(url)
    except Exception:
        return []
    return _ttl_cache_set(cache_key, list(payload.get("data") or []), ttl=GECKO_CACHE_TTL_SECONDS)


def _gt_get_network_pools() -> list[dict]:
    cache_key = ("gt_network_pools", GECKO_NETWORK_ID)
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached
    url = f"{GECKO_TERMINAL_BASE}/networks/{GECKO_NETWORK_ID}/pools?page=1"
    try:
        payload = _http_json(url)
    except Exception:
        return []
    return _ttl_cache_set(cache_key, list(payload.get("data") or []), ttl=GECKO_CACHE_TTL_SECONDS)


def _gt_get_pool_ohlcv(pool_address: str, *, interval: str) -> tuple[list[float], list[int]]:
    normalized = str(pool_address or "").strip().lower()
    if not _is_hex_address(normalized):
        return [], []

    interval_value = str(interval or "60").strip().lower()
    timeframe = "hour"
    aggregate = 1
    if interval_value in {"s1", "1"}:
        timeframe = "minute"
        aggregate = 1
    elif interval_value == "5":
        timeframe = "minute"
        aggregate = 5
    elif interval_value == "60":
        timeframe = "hour"
        aggregate = 1
    elif interval_value == "240":
        timeframe = "hour"
        aggregate = 4
    elif interval_value == "1440":
        timeframe = "day"
        aggregate = 1

    cache_key = ("gt_ohlcv", normalized, timeframe, aggregate)
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        f"{GECKO_TERMINAL_BASE}/networks/{GECKO_NETWORK_ID}/pools/{normalized}/ohlcv/"
        f"{timeframe}?aggregate={aggregate}&limit={DEFAULT_CHART_POINTS}"
    )
    try:
        payload = _http_json(url)
        candles = (((payload or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    except Exception:
        candles = []

    prices: list[float] = []
    times: list[int] = []
    for candle in reversed(list(candles)):
        if not isinstance(candle, list) or len(candle) < 5:
            continue
        try:
            times.append(int(candle[0]))
            prices.append(float(candle[4]))
        except (TypeError, ValueError):
            continue
    return _ttl_cache_set(cache_key, (prices, times), ttl=SPOTLIGHT_CACHE_TTL_SECONDS)


def _gt_snapshot_from_pool_record(pool_record: dict, token_address: str) -> dict | None:
    if not isinstance(pool_record, dict):
        return None
    attrs = pool_record.get("attributes") or {}
    rel = pool_record.get("relationships") or {}
    base_rel = ((rel.get("base_token") or {}).get("data") or {}).get("id")
    quote_rel = ((rel.get("quote_token") or {}).get("data") or {}).get("id")
    base_addr = _gt_token_address_from_id(base_rel)
    quote_addr = _gt_token_address_from_id(quote_rel)
    target = str(token_address or "").strip().lower()
    if target not in {base_addr, quote_addr}:
        return None

    base_symbol, quote_symbol = _gt_pool_symbols(attrs.get("name") or attrs.get("pool_name") or "")
    reserve_usd = _decimal_to_float(attrs.get("reserve_in_usd"))
    volume_map = attrs.get("volume_usd") or {}
    change_map = attrs.get("price_change_percentage") or {}
    market_cap = attrs.get("market_cap_usd")
    if market_cap in (None, "", "null"):
        market_cap = attrs.get("fdv_usd")

    is_base = target == base_addr
    return {
        "addr": target,
        "token_id": target,
        "chain": CHAIN_NAME,
        "symbol": base_symbol if is_base else quote_symbol,
        "pair": f"{base_symbol} / {quote_symbol}",
        "pair_address": str(attrs.get("address") or "").strip().lower(),
        "pair_quote_symbol": quote_symbol if is_base else base_symbol,
        "pair_quote_address": quote_addr if is_base else base_addr,
        "price_usd": _decimal_to_float(attrs.get("base_token_price_usd" if is_base else "quote_token_price_usd")),
        "liquidity_usd": reserve_usd,
        "market_cap_usd": _decimal_to_float(market_cap),
        "volume_24h_usd": _decimal_to_float(volume_map.get("h24")),
        "change_24h": _decimal_to_float(change_map.get("h24")),
        "gt_score": reserve_usd or 0.0,
        "source": "geckoterminal",
    }


def _gt_best_snapshot_for_token(token_address: str) -> dict | None:
    normalized = str(token_address or "").strip().lower()
    if not _is_hex_address(normalized):
        return None
    best = None
    for pool in _gt_get_token_pools(normalized):
        snapshot = _gt_snapshot_from_pool_record(pool, normalized)
        if not snapshot:
            continue
        if best is None or float(snapshot.get("gt_score") or 0.0) > float(best.get("gt_score") or 0.0):
            best = snapshot
    return best


def get_network_market_tokens(limit: int = 20) -> list[dict]:
    cache_key = ("network_market_tokens", int(limit or 20))
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached
    unique: dict[str, dict] = {}
    pool_records: dict[str, dict] = {}
    seed_tokens: set[str] = set()

    for pool in _gt_get_network_pools():
        attrs = pool.get("attributes") or {}
        rel = pool.get("relationships") or {}
        pool_addr = str(attrs.get("address") or "").strip().lower()
        if _is_hex_address(pool_addr):
            pool_records[pool_addr] = pool
        for token_rel in ("base_token", "quote_token"):
            token_id = ((rel.get(token_rel) or {}).get("data") or {}).get("id")
            addr = _gt_token_address_from_id(token_id)
            if _is_hex_address(addr):
                seed_tokens.add(addr)

    for token_addr in list(seed_tokens):
        for pool in _gt_get_token_pools(token_addr):
            attrs = pool.get("attributes") or {}
            pool_addr = str(attrs.get("address") or "").strip().lower()
            if _is_hex_address(pool_addr) and pool_addr not in pool_records:
                pool_records[pool_addr] = pool

    for pool in pool_records.values():
        rel = pool.get("relationships") or {}
        for token_rel in ("base_token", "quote_token"):
            token_id = ((rel.get(token_rel) or {}).get("data") or {}).get("id")
            addr = _gt_token_address_from_id(token_id)
            if not _is_hex_address(addr):
                continue
            snapshot = _gt_snapshot_from_pool_record(pool, addr)
            if not snapshot or snapshot.get("price_usd") is None:
                continue
            current = unique.get(addr)
            if current is None or float(snapshot.get("gt_score") or 0.0) > float(current.get("gt_score") or 0.0):
                unique[addr] = snapshot
    rows = sorted(unique.values(), key=lambda item: float(item.get("gt_score") or 0.0), reverse=True)
    return _ttl_cache_set(cache_key, rows[: max(1, int(limit or 1))], ttl=GECKO_CACHE_TTL_SECONDS)


def get_token_spotlight(address: str, *, interval: str = "60") -> dict:
    normalized = str(address or "").strip().lower()
    interval_value = str(interval or "60").strip()
    cache_key = ("token_spotlight", normalized, interval_value)
    cached = _ttl_cache_get(cache_key)
    if cached is not None:
        return cached

    market = get_token_market_snapshot(address)
    token_meta = get_token_metadata(address)
    decimals = int(token_meta.get("decimals") or 0)
    price_usd = market.get("price_usd")
    market_cap_usd = market.get("market_cap_usd")

    quote_token_address = str(market.get("pair_quote_address") or "")
    quote_token_symbol = str(market.get("pair_quote_symbol") or "")
    chart_prices, chart_times = _gt_get_pool_ohlcv(str(market.get("pair_address") or ""), interval=interval)
    if not chart_prices:
        quote_token_usd_price = 1.0 if quote_token_symbol == "USDT" else float(_quote_hsk_price_in_usdt()[0] or 0.0)
        chart_prices, chart_times = _historical_close_chart_from_pool_transfers(
            str(market.get("pair_address") or ""),
            base_token_address=token_meta["addr"],
            base_decimals=decimals,
            quote_token_address=quote_token_address,
            quote_decimals=6 if quote_token_symbol == "USDT" else 18,
            quote_token_usd_price=quote_token_usd_price,
            interval=interval,
            points=DEFAULT_CHART_POINTS,
        )
    if not chart_prices:
        chart_prices, chart_times = _build_flat_chart(price_usd=price_usd, interval=interval)
    chart_is_flat = not chart_prices or len(set(chart_prices)) <= 1

    snapshot = {
        "addr": token_meta["addr"],
        "token_id": token_meta["token_id"],
        "chain": CHAIN_NAME,
        "symbol": market["symbol"],
        "name": token_meta["name"],
        "decimals": decimals,
        "verified": token_meta["verified"],
        "holders_count": token_meta["holders_count"],
        "pair": market["pair"],
        "pair_address": str(market.get("pair_address") or ""),
        "pair_quote_symbol": str(market.get("pair_quote_symbol") or "USDT"),
        "price_usd": price_usd,
        "change_24h": market.get("change_24h"),
        "liquidity_usd": market.get("liquidity_usd"),
        "volume_24h_usd": market.get("volume_24h_usd"),
        "market_cap_usd": market_cap_usd,
        "top100_concentration": None,
        "chart_prices": chart_prices,
        "chart_times": chart_times,
        "chart_is_flat": chart_is_flat,
        "chart_source": "pool_transfers_hourly_close" if not chart_is_flat else "flat_fallback",
        "source": "hashkey_live",
    }
    return _ttl_cache_set(cache_key, snapshot, ttl=SPOTLIGHT_CACHE_TTL_SECONDS)


def market_buy_preview(token_out: str, *, amount_hsk: Decimal | float | str, wallet_address: str) -> dict:
    amount_decimal = Decimal(str(amount_hsk))
    amount_wei = int(amount_decimal * (Decimal(10) ** 18))
    token_meta = get_token_metadata(token_out)
    best_quote = hk.quote_best_exact_input(hk.HYPERINDEX_WHSK, token_out, amount_wei)
    if not best_quote:
        raise hk.HashKeyApiError(f"No buy quote available for {token_out}")

    simulated = hk.simulate_native_buy_exact_input_single(
        token_out,
        amount_wei,
        fee=int(best_quote["fee"]),
        recipient=wallet_address,
        from_address=wallet_address,
        deadline=2_000_000_000,
    )

    out_raw = simulated["amount_out"]
    return {
        "trade_side": "buy",
        "chain": CHAIN_NAME,
        "wallet_address": wallet_address,
        "token_in_symbol": hk.HASHKEY_NATIVE_SYMBOL,
        "token_in_address": hk.HASHKEY_NATIVE_ADDRESS,
        "token_out_symbol": token_meta["symbol"],
        "token_out_address": token_meta["addr"],
        "amount_in_native": str(amount_decimal),
        "amount_in_wei": amount_wei,
        "best_fee_tier": int(best_quote["fee"]),
        "quote_amount_out_raw": int(best_quote["amount_out"]),
        "quote_amount_out": _human_amount(best_quote["amount_out"], token_meta["decimals"]),
        "router_amount_out_raw": int(out_raw),
        "router_amount_out": _human_amount(out_raw, token_meta["decimals"]),
        "quote_gas_estimate": int(best_quote["gas_estimate"]),
        "status": "ok",
        "execution_path": "hyperindex_v3_exact_input_single_native_buy",
    }


def market_sell_preview(
    token_in: str,
    *,
    amount_raw: int | str,
    wallet_address: str,
) -> dict:
    token_meta = get_token_metadata(token_in)
    raw_value = int(str(amount_raw))
    allowance = hk.erc20_allowance(token_in, wallet_address, hk.HYPERINDEX_V3_ROUTER)
    best_quote = hk.quote_best_exact_input(token_in, hk.HYPERINDEX_WHSK, raw_value)
    if not best_quote:
        raise hk.HashKeyApiError(f"No sell quote available for {token_in}")

    result = {
        "trade_side": "sell",
        "chain": CHAIN_NAME,
        "wallet_address": wallet_address,
        "token_in_symbol": token_meta["symbol"],
        "token_in_address": token_meta["addr"],
        "token_out_symbol": hk.HASHKEY_NATIVE_SYMBOL,
        "token_out_address": hk.HASHKEY_NATIVE_ADDRESS,
        "amount_in_raw": raw_value,
        "amount_in": _human_amount(raw_value, token_meta["decimals"]),
        "best_fee_tier": int(best_quote["fee"]),
        "quote_amount_out_raw": int(best_quote["amount_out"]),
        "quote_amount_out": _human_amount(best_quote["amount_out"], 18),
        "quote_gas_estimate": int(best_quote["gas_estimate"]),
        "allowance_raw": allowance,
        "allowance_sufficient": allowance >= raw_value,
        "execution_path": "hyperindex_v3_exact_input_single_sell",
    }

    try:
        simulated = hk.simulate_sell_exact_input_single(
            token_in,
            raw_value,
            fee=int(best_quote["fee"]),
            recipient=wallet_address,
            from_address=wallet_address,
            deadline=2_000_000_000,
        )
        result.update(
            {
                "status": "ok",
                "router_amount_out_raw": int(simulated["amount_out"]),
                "router_amount_out": _human_amount(simulated["amount_out"], 18),
                "error": "",
            }
        )
    except Exception as exc:  # pragma: no cover - integration path
        error_text = str(exc)
        lowered = error_text.lower()
        result.update(
            {
                "status": "revert",
                "router_amount_out_raw": 0,
                "router_amount_out": "0",
                "error": error_text,
                "likely_allowance_issue": "stf" in lowered or "allowance" in lowered or "transferfrom" in lowered,
            }
        )
    return result
# Wallet and token data provider
