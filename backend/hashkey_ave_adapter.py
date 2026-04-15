"""
AVE-facing adapter for the HashKey provider.

This layer keeps frontend-impact low by shaping HashKey-native responses into
payloads that already look close to the current Ava Box surfaces.
"""

from __future__ import annotations

import math
import concurrent.futures
from datetime import datetime

from plugins_func.functions import hashkey_provider as provider


def _fmt_price(price) -> str:
    if price is None:
        return "N/A"
    price = float(price)
    if price == 0:
        return "$0"
    if price >= 1000:
        return f"${price:,.0f}"
    if price >= 1:
        return f"${price:.4f}"
    if price >= 0.01:
        return f"${price:.6f}"
    mag = math.floor(math.log10(abs(price)))
    decimals = max(2, -mag + 3)
    return f"${price:.{decimals}f}"


def _fmt_y_label(price) -> str:
    if price is None or price <= 0:
        return "N/A"
    price = float(price)
    if price >= 1000:
        return f"${price:,.0f}"
    if price >= 1:
        return f"${price:.2f}"
    if price >= 0.001:
        return f"${price:.4f}"
    exp = int(math.floor(math.log10(abs(price))))
    mantissa = price / (10 ** exp)
    return f"{mantissa:.2f}e{exp}"


def _fmt_change(pct) -> str:
    if pct is None:
        return "N/A"
    pct = float(pct)
    sign = "+" if pct >= 0 else "-"
    return f"{sign}{abs(pct):.2f}%"


def _fmt_volume(vol) -> str:
    if vol is None:
        return "N/A"
    try:
        vol = float(vol)
    except (TypeError, ValueError):
        return "N/A"
    if vol >= 1_000_000:
        return f"${vol/1_000_000:.1f}M"
    if vol >= 1_000:
        return f"${vol/1_000:.1f}K"
    return f"${vol:.0f}"


def _fmt_portfolio_value(vol) -> str:
    if vol is None:
        return "N/A"
    try:
        vol = float(vol)
    except (TypeError, ValueError):
        return "N/A"
    if vol >= 1_000_000:
        return f"${vol/1_000_000:.1f}M"
    if vol >= 1_000:
        return f"${vol/1_000:.1f}K"
    return f"${vol:.2f}"


def _fmt_signed_volume(vol) -> str:
    if vol is None:
        return "N/A"
    try:
        numeric = float(vol)
    except (TypeError, ValueError):
        return "N/A"
    sign = "+" if numeric >= 0 else "-"
    return f"{sign}{_fmt_volume(abs(numeric))}"


def _fmt_portfolio_pnl(vol) -> str:
    if vol is None:
        return "N/A"
    try:
        numeric = float(vol)
    except (TypeError, ValueError):
        return "N/A"
    sign = "+" if numeric >= 0 else "-"
    abs_value = abs(numeric)
    if abs_value >= 1_000:
        return f"{sign}{_fmt_volume(abs_value)}"
    return f"{sign}${abs_value:.2f}"


def _fmt_chart_time(ts: int) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%m/%d %H:%M")
    except Exception:
        return ""


def _derive_chart_change_pct(chart_prices: list) -> float | None:
    numeric = []
    for value in chart_prices or []:
        if value in (None, ""):
            continue
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            continue
    if len(numeric) < 2:
        return None
    first = numeric[0]
    last = numeric[-1]
    if not first:
        return None
    return ((last - first) / first) * 100.0


def _normalize_kline(points: list) -> list:
    vals = []
    for point in points or []:
        close = point.get("close") if isinstance(point, dict) else point
        if close in (None, ""):
            continue
        try:
            vals.append(float(close))
        except (TypeError, ValueError):
            continue
    if not vals:
        return [500] * 12
    if len(set(vals)) == 1:
        return [500] * len(vals)
    lo = min(vals)
    hi = max(vals)
    span = hi - lo
    return [int(round(((value - lo) / span) * 1000)) for value in vals]


def _merge_search_row_with_spotlight(row: dict) -> dict:
    addr = str(row.get("addr") or row.get("token_id") or "").strip()
    if not addr:
        return dict(row)

    try:
        snapshot = provider.get_token_spotlight(addr, interval="60")
    except Exception:
        return dict(row)

    chart_change_pct = _derive_chart_change_pct(snapshot.get("chart_prices") or [])
    explicit_change = snapshot.get("change_24h")
    if explicit_change and explicit_change != "N/A":
        change_text = _fmt_change(explicit_change)
        change_positive = 0 if str(explicit_change).startswith("-") else 1
    elif chart_change_pct is not None:
        change_text = _fmt_change(chart_change_pct)
        change_positive = 1 if chart_change_pct >= 0 else 0
    else:
        change_text = "N/A"
        change_positive = -1

    merged = dict(row)
    merged.update(
        {
            "addr": addr,
            "token_id": str(snapshot.get("token_id") or row.get("token_id") or addr).replace("-hashkey", ""),
            "chain": "hashkey",
            "symbol": str(snapshot.get("symbol") or row.get("symbol") or "?"),
            "price": _fmt_price(snapshot.get("price_usd")) if snapshot.get("price_usd") is not None else str(row.get("price") or "N/A"),
            "price_raw": snapshot.get("price_usd"),
            "change_24h": change_text,
            "change_positive": change_positive,
            "volume_24h": _fmt_volume(snapshot.get("volume_24h_usd")),
            "market_cap": _fmt_volume(snapshot.get("market_cap_usd")),
            "pair_address": str(snapshot.get("pair_address") or ""),
            "pair": str(snapshot.get("pair") or ""),
            "liquidity": _fmt_volume(snapshot.get("liquidity_usd")),
            "source": "hashkey_live",
            "source_tag": "hashkey",
            "contract_tail": addr[-4:] if len(addr) >= 4 else addr,
        }
    )
    return merged


def _search_row_score(row: dict, *, keyword: str = "") -> tuple:
    symbol = str(row.get("symbol") or "").strip().upper()
    name = str(row.get("name") or "").strip().upper()
    keyword_text = str(keyword or "").strip().upper()
    exact_symbol = int(bool(keyword_text) and symbol == keyword_text)
    symbol_starts = int(bool(keyword_text) and symbol.startswith(keyword_text))
    name_contains = int(bool(keyword_text) and keyword_text in name)
    verified = int(bool(row.get("verified")))
    clean_symbol = int("/" not in symbol and "-" not in symbol)
    not_poolish = int(not any(term in name.lower() for term in ("debt", "liquidity", "pool", "amm", "test")))
    shorter = -len(symbol or "ZZZZZZZZ")
    return (exact_symbol, symbol_starts, name_contains, verified, clean_symbol, not_poolish, shorter)


def _looks_feed_worthy_hashkey_row(row: dict, *, keyword: str = "") -> bool:
    symbol = str(row.get("symbol") or "").strip().upper()
    keyword_text = str(keyword or "").strip().upper()
    price = str(row.get("price") or "").strip().upper()
    pair_address = str(row.get("pair_address") or "").strip()
    name = str(row.get("name") or "").strip().lower()
    if not symbol:
        return False
    if "/" in symbol:
        return False
    if "debt" in name or "liquidity" in name or "pool" in name:
        return False
    if keyword_text and keyword_text not in symbol and keyword_text not in name.upper():
        return False
    if price in {"", "N/A"} and not pair_address:
        return False
    return True


def build_search_feed_payload(keyword: str, *, limit: int = 20) -> dict:
    rows = provider.search_tokens(keyword, limit=max(limit + 4, 8))
    ranked_rows = sorted(rows, key=lambda row: _search_row_score(row, keyword=keyword), reverse=True)
    candidate_rows = ranked_rows[: min(max(limit + 2, 4), 6)]
    enriched = []
    if candidate_rows:
        max_workers = min(4, len(candidate_rows))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            enriched = list(pool.map(_merge_search_row_with_spotlight, candidate_rows))

    preferred = [row for row in enriched if _looks_feed_worthy_hashkey_row(row, keyword=keyword)]
    fallback = [row for row in enriched if row not in preferred]
    if len(preferred) < limit:
        for raw_row in ranked_rows:
            if raw_row in preferred or raw_row in fallback:
                continue
            fallback.append(raw_row)
            if len(preferred) + len(fallback) >= limit:
                break
    rows = (preferred + fallback)[:limit]
    return {
        "tokens": rows,
        "chain": "hashkey",
        "source_label": "HASHKEY SEARCH",
        "mode": "search",
        "search_query": keyword,
        "cursor": 0,
    }


def build_market_buy_confirm_payload(token_address: str, *, amount_hsk: str, wallet_address: str) -> dict:
    preview = provider.market_buy_preview(token_address, amount_hsk=amount_hsk, wallet_address=wallet_address)
    return {
        "symbol": preview["token_out_symbol"],
        "chain": "hashkey",
        "token_id": preview["token_out_address"],
        "source_tag": "hashkey",
        "action": "BUY",
        "amount_native": f"{preview['amount_in_native']} HSK",
        "amount_usd": "",
        "out_amount": f"{preview['router_amount_out']} {preview['token_out_symbol']}",
        "slippage_pct": None,
        "timeout_sec": None,
        "mode_label": "",
        "diagnostics": {
            "fee_tier": preview["best_fee_tier"],
            "quote_gas_estimate": preview["quote_gas_estimate"],
            "execution_path": preview["execution_path"],
        },
    }


def build_market_sell_confirm_payload(token_address: str, *, amount_raw: int | str, wallet_address: str) -> dict:
    preview = provider.market_sell_preview(token_address, amount_raw=amount_raw, wallet_address=wallet_address)
    payload = {
        "symbol": preview["token_in_symbol"],
        "chain": "hashkey",
        "token_id": preview["token_in_address"],
        "source_tag": "hashkey",
        "action": "SELL",
        "amount_native": f"{preview['amount_in']} {preview['token_in_symbol']}",
        "amount_usd": "",
        "out_amount": f"{preview['quote_amount_out']} HSK",
        "slippage_pct": None,
        "timeout_sec": None,
        "mode_label": "",
        "diagnostics": {
            "fee_tier": preview["best_fee_tier"],
            "quote_gas_estimate": preview["quote_gas_estimate"],
            "allowance_raw": preview["allowance_raw"],
            "allowance_sufficient": preview["allowance_sufficient"],
            "execution_path": preview["execution_path"],
            "status": preview["status"],
            "error": preview.get("error", ""),
            "likely_allowance_issue": preview.get("likely_allowance_issue", False),
        },
    }
    return payload


def build_portfolio_payload(wallet_address: str) -> dict:
    snapshot = provider.get_wallet_holdings_with_pnl(wallet_address)
    rows = []
    for item in snapshot["holdings"]:
        pnl_value = item.get("total_pnl_usd")
        rows.append(
            {
                "addr": item["addr"],
                "token_id": item["token_id"],
                "chain": "hashkey",
                "symbol": item["symbol"],
                "price": _fmt_price(item.get("price_usd")),
                "price_raw": float(item.get("price_usd") or 0.0),
                "change_24h": "N/A",
                "change_positive": True,
                "volume_24h": item["balance"],
                "market_cap": "N/A",
                "source": "hashkey_wallet",
                "risk_level": "UNKNOWN",
                "balance": item["balance"],
                "raw_balance": item["raw_balance"],
                "holders_count": item["holders_count"],
                "value_usd": _fmt_portfolio_value(item.get("value_usd")),
                "avg_cost_usd": _fmt_price(item.get("avg_cost_usd")),
                "pnl": _fmt_portfolio_pnl(pnl_value) if pnl_value is not None else "N/A",
                "pnl_pct": _fmt_change(item.get("pnl_percent")) if item.get("pnl_percent") is not None else "N/A",
                "pnl_positive": 1 if pnl_value is not None and float(pnl_value) >= 0 else (0 if pnl_value is not None else -1),
            }
        )
    return {
        "wallet_address": wallet_address,
        "chain": "hashkey",
        "tokens": rows,
        "total_usd": _fmt_portfolio_value(snapshot.get("total_value_usd")),
        "pnl": _fmt_portfolio_pnl(snapshot.get("total_pnl_usd")) if snapshot.get("total_pnl_usd") is not None else "N/A",
        "pnl_pct": _fmt_change(snapshot.get("total_pnl_pct")) if snapshot.get("total_pnl_pct") is not None else "N/A",
        "has_pnl": bool(snapshot.get("has_pnl")),
    }


def build_spotlight_payload(token_address: str, *, interval: str = "60") -> dict:
    snapshot = provider.get_token_spotlight(token_address, interval=interval)
    chart_prices = list(snapshot.get("chart_prices") or [])
    chart_times = list(snapshot.get("chart_times") or [])
    price_values = [float(value) for value in chart_prices if value is not None]
    derived_change_pct = _derive_chart_change_pct(chart_prices)
    change_pct = snapshot.get("change_24h")
    if change_pct is None:
        change_pct = derived_change_pct

    if price_values:
        price_min = min(price_values)
        price_max = max(price_values)
        price_mid = (price_min + price_max) / 2.0
        chart = _normalize_kline([{"close": value, "time": chart_times[idx] if idx < len(chart_times) else 0} for idx, value in enumerate(price_values)])
    else:
        price_min = price_max = price_mid = 0.0
        chart = [500] * 12

    point_count = len(chart_times)
    return {
        "symbol": snapshot["symbol"],
        "chain": "hashkey",
        "token_id": f"{snapshot['addr']}-hashkey",
        "source_tag": "hashkey",
        "addr": snapshot["addr"],
        "interval": str(interval or "60"),
        "pair": snapshot.get("pair") or f"{snapshot['symbol']} / USDT",
        "price": _fmt_price(snapshot.get("price_usd")),
        "price_raw": float(snapshot.get("price_usd") or 0),
        "change_24h": _fmt_change(change_pct) if change_pct is not None else "N/A",
        "change_positive": (float(change_pct or 0) >= 0) if change_pct is not None else -1,
        "holders": f"{int(snapshot.get('holders_count') or 0):,}" if snapshot.get("holders_count") not in (None, "") else "N/A",
        "liquidity": _fmt_volume(snapshot.get("liquidity_usd")),
        "volume_24h": _fmt_volume(snapshot.get("volume_24h_usd")),
        "market_cap": _fmt_volume(snapshot.get("market_cap_usd")),
        "top100_concentration": "N/A",
        "contract_short": (
            f"{snapshot['addr'][:4]}...{snapshot['addr'][-4:]}"
            if len(str(snapshot.get("addr") or "")) > 8
            else str(snapshot.get("addr") or "N/A")
        ),
        "chart": chart,
        "chart_min": _fmt_price(price_min) if price_values else "--",
        "chart_max": _fmt_price(price_max) if price_values else "--",
        "chart_min_y": _fmt_y_label(price_min) if price_values else "--",
        "chart_mid_y": _fmt_y_label(price_mid) if price_values else "--",
        "chart_max_y": _fmt_y_label(price_max) if price_values else "--",
        "chart_t_start": _fmt_chart_time(chart_times[0]) if point_count > 0 else "",
        "chart_t_mid": _fmt_chart_time(chart_times[point_count // 2]) if point_count > 0 else "",
        "chart_t_end": "now",
        "is_honeypot": False,
        "is_mintable": False,
        "is_freezable": False,
        "risk_level": "UNKNOWN",
        "pair_address": snapshot.get("pair_address", ""),
        "chart_is_flat": bool(snapshot.get("chart_is_flat")),
        "chart_source": snapshot.get("chart_source", ""),
        "_raw_chart_prices": chart_prices,
        "_raw_chart_times": chart_times,
    }
