"""Text-first AVE skill tools for the server-side agent path."""

import os
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Iterable

from plugins_func.functions.ave_tools import (
    _data_get,
    _fmt_price,
    _hashkey_wallet_address,
    _normalize_chain_name,
    _normalize_portfolio_wallets,
    ave_portfolio,
    ave_portfolio_activity_detail,
)
from plugins_func.functions import hashkey_provider
from plugins_func.functions.ave_trade_mgr import _trade_get
from plugins_func.register import Action, ActionResponse, ToolType, register_function

if TYPE_CHECKING:
    from core.connection import ConnectionHandler


_SUPPORTED_CHAIN_HINTS = ("solana", "bsc", "eth", "base", "hashkey")


def _short_addr(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= 12:
        return text
    return f"{text[:6]}...{text[-4:]}"


def _pick_first(mapping: dict, *keys, default=None):
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def _pick_list(data) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("list", "items", "records", "rows", "result"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    nested_data = data.get("data")
    if isinstance(nested_data, list):
        return nested_data
    if isinstance(nested_data, dict):
        for key in ("list", "items", "records", "rows", "result"):
            value = nested_data.get(key)
            if isinstance(value, list):
                return value
    return []


def _pct_text(value) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return text if text.endswith("%") else f"{text}%"


def _fmt_amount_text(value) -> str:
    if value in (None, ""):
        return ""
    try:
        numeric = Decimal(str(value))
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return str(value).strip()
    text = f"{numeric:,.6f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _chain_from_state(conn: "ConnectionHandler") -> str:
    state = getattr(conn, "ave_state", {})
    if not isinstance(state, dict):
        return ""
    current = state.get("current_token")
    if isinstance(current, dict):
        chain = _normalize_chain_name(current.get("chain"))
        if chain:
            return chain
    for key in ("last_orders_chain", "feed_chain"):
        chain = _normalize_chain_name(state.get(key))
        if chain:
            return chain
    return ""


def _current_token(conn: "ConnectionHandler") -> dict:
    state = getattr(conn, "ave_state", {})
    if not isinstance(state, dict):
        return {}
    token = state.get("current_token")
    return token if isinstance(token, dict) else {}


def _load_proxy_wallets(conn: "ConnectionHandler") -> list:
    state = getattr(conn, "ave_state", {})
    if isinstance(state, dict):
        cached = state.get("portfolio_wallets")
        if isinstance(cached, list) and cached:
            return cached

    assets_id = os.environ.get("AVE_PROXY_WALLET_ID", "").strip()
    if not assets_id:
        return []

    response = _trade_get(
        "/v1/thirdParty/user/getUserByAssetsId",
        {"assetsIds": assets_id},
    )
    wallets = _normalize_portfolio_wallets(response.get("data", []))
    if isinstance(state, dict):
        state["portfolio_wallets"] = wallets
    return wallets


def _resolve_wallet_target(
    conn: "ConnectionHandler",
    wallet_address: str = "",
    chain: str = "",
) -> tuple[str, str]:
    requested_chain = _normalize_chain_name(chain)
    preferred_chain = requested_chain or _chain_from_state(conn)
    wallet_text = str(wallet_address or "").strip()

    # The LLM sometimes copies the short address form from prior tool output
    # (for example `0xe540...d481`). Treat that as a pointer to the current
    # wallet context instead of failing address validation downstream.
    if wallet_text and "..." in wallet_text:
        wallet_text = ""

    # In the real AI path the model may hallucinate a concrete wallet address
    # after seeing prior summaries. If the latest user turns did not actually
    # mention that address, prefer the configured/current HashKey wallet.
    if wallet_text and preferred_chain == "hashkey":
        try:
            default_hashkey_wallet = _hashkey_wallet_address(conn)
        except Exception:
            default_hashkey_wallet = ""
        if default_hashkey_wallet and not _recent_user_messages_mention_wallet(conn, wallet_text):
            wallet_text = default_hashkey_wallet

    if wallet_text:
        if not preferred_chain:
            raise ValueError("请补充链信息，例如 solana、bsc、eth、base 或 hashkey。")
        return wallet_text, preferred_chain

    try:
        default_hashkey_wallet = _hashkey_wallet_address(conn)
    except Exception:
        default_hashkey_wallet = ""

    if preferred_chain == "hashkey":
        return default_hashkey_wallet, "hashkey"

    # In the HashKey build, generic "wallet" queries should prefer the live
    # HashKey wallet instead of drifting to unrelated proxy-wallet chains.
    if default_hashkey_wallet:
        return default_hashkey_wallet, "hashkey"

    wallets = _load_proxy_wallets(conn)
    if not wallets:
        raise ValueError("未提供钱包地址，且未配置可解析的 AVE_PROXY_WALLET_ID。")

    for wallet in wallets:
        for address_info in wallet.get("addresses", []):
            chain_name = _normalize_chain_name(address_info.get("chain"))
            address = str(address_info.get("address", "") or "").strip()
            if not chain_name or not address:
                continue
            if preferred_chain and chain_name == preferred_chain:
                return address, chain_name

    first_wallet = wallets[0] if wallets else {}
    first_address = (first_wallet.get("addresses") or [{}])[0]
    fallback_address = str(first_address.get("address", "") or "").strip()
    fallback_chain = _normalize_chain_name(first_address.get("chain"), "solana")
    if not fallback_address:
        raise ValueError("代理钱包已配置，但没有可用链地址。")
    return fallback_address, fallback_chain


def _recent_user_messages_mention_wallet(conn: "ConnectionHandler", wallet_address: str) -> bool:
    dialogue = getattr(conn, "dialogue", None)
    messages = getattr(dialogue, "dialogue", None)
    if not isinstance(messages, list):
        return False

    wallet_text = str(wallet_address or "").strip().lower()
    if not wallet_text:
        return False

    short_wallet = _short_addr(wallet_text).lower()
    for msg in reversed(messages[-8:]):
        if getattr(msg, "role", "") != "user":
            continue
        content = str(getattr(msg, "content", "") or "").lower()
        if wallet_text in content or short_wallet in content:
            return True
    return False


def _metric_parts(parts: Iterable[str]) -> str:
    values = [part for part in parts if part]
    return "；".join(values)


def _success_response(text: str, result: str = "") -> ActionResponse:
    return ActionResponse(action=Action.RESPONSE, result=result or text, response=text)


def _error_response(text: str) -> ActionResponse:
    return ActionResponse(action=Action.RESPONSE, result=text, response=text)


def _try_open_hashkey_portfolio_surface(conn: "ConnectionHandler") -> None:
    if not getattr(conn, "loop", None):
        return
    try:
        executor = getattr(conn, "executor", None)
        if executor and hasattr(executor, "submit"):
            executor.submit(ave_portfolio, conn, chain_filter="hashkey")
            return
        ave_portfolio(conn, chain_filter="hashkey")
    except Exception:
        return


def _try_open_hashkey_token_surface(
    conn: "ConnectionHandler",
    *,
    token_address: str,
    token_symbol: str = "",
) -> None:
    if not getattr(conn, "loop", None):
        return
    token_text = str(token_address or "").strip()
    if not token_text:
        return
    try:
        executor = getattr(conn, "executor", None)
        if executor and hasattr(executor, "submit"):
            executor.submit(
                ave_portfolio_activity_detail,
                conn,
                addr=token_text,
                chain="hashkey",
                symbol=str(token_symbol or "").strip(),
            )
            return
        ave_portfolio_activity_detail(
            conn,
            addr=token_text,
            chain="hashkey",
            symbol=str(token_symbol or "").strip(),
        )
    except Exception:
        return


def _current_hashkey_token(conn: "ConnectionHandler") -> dict:
    current = _current_token(conn)
    if _normalize_chain_name(current.get("chain")) != "hashkey":
        return {}
    return current


def _resolve_hashkey_token_address(token_address: str = "", token_symbol: str = "") -> tuple[str, str]:
    token_text = str(token_address or "").strip()
    symbol_text = str(token_symbol or "").strip()
    if token_text:
        return token_text, symbol_text
    if not symbol_text or symbol_text == "该 token":
        return "", symbol_text

    matches = hashkey_provider.search_tokens(symbol_text, limit=10)
    if not matches:
        return "", symbol_text

    normalized_symbol = symbol_text.upper()
    for row in matches:
        candidate_symbol = str(row.get("symbol") or "").strip().upper()
        if candidate_symbol == normalized_symbol:
            return str(row.get("addr") or row.get("token_id") or "").strip(), str(row.get("symbol") or symbol_text).strip()

    first = matches[0]
    return (
        str(first.get("addr") or first.get("token_id") or "").strip(),
        str(first.get("symbol") or symbol_text).strip(),
    )


def _wallet_overview_summary(chain: str, wallet_address: str, payload: dict) -> str:
    data = payload.get("data", payload)
    total_value = _pick_first(
        data,
        "total_value_usd",
        "totalValueUsd",
        "total_usd",
        "portfolio_value_usd",
    )
    win_rate = _pick_first(data, "win_rate", "winRate", "total_win_rate")
    trade_count = _pick_first(data, "trade_count", "tradeCount", "tx_count", "total_tx_count")
    pnl_usd = _pick_first(data, "total_pnl_usd", "totalPnlUsd", "realized_pnl_usd", "pnl_usd")

    summary = _metric_parts(
        (
            f"总资产 {_fmt_price(total_value)}" if total_value not in (None, "") else "",
            f"胜率 {_pct_text(win_rate)}" if win_rate not in (None, "") else "",
            f"交易 {trade_count} 笔" if trade_count not in (None, "") else "",
            f"PnL {_fmt_price(pnl_usd)}" if pnl_usd not in (None, "") else "",
        )
    )
    if not summary:
        field_count = len(data) if isinstance(data, dict) else 0
        summary = f"已返回 {field_count} 个统计字段"
    return f"钱包概览（{chain}，{_short_addr(wallet_address)}）：{summary}。"


def _wallet_tokens_summary(chain: str, wallet_address: str, payload: dict) -> str:
    rows = _pick_list(payload.get("data", payload))
    if not rows:
        return f"钱包持仓（{chain}，{_short_addr(wallet_address)}）为空。"

    preview = []
    for row in rows[:5]:
        symbol = _pick_first(row, "symbol", "token_symbol", "name", default="TOKEN")
        value_usd = _pick_first(row, "value_usd", "valueUsd", "amount_usd", "total_value_usd")
        if value_usd not in (None, ""):
            preview.append(f"{symbol} {_fmt_price(value_usd)}")
        else:
            balance = _pick_first(row, "balance", "amount", "balance_formatted", default="?")
            preview.append(f"{symbol} {balance}")
    return (
        f"钱包持仓（{chain}，{_short_addr(wallet_address)}）共 {len(rows)} 个："
        + "，".join(preview)
        + "。"
    )


def _history_action_label(row: dict) -> str:
    action = str(_pick_first(row, "side", "type", "action", "trade_type", default="交易")).strip().lower()
    mapping = {
        "buy": "买入",
        "sell": "卖出",
        "swap": "兑换",
        "transfer": "转账",
    }
    return mapping.get(action, action or "交易")


def _wallet_history_summary(chain: str, wallet_address: str, payload: dict) -> str:
    rows = _pick_list(payload.get("data", payload))
    if not rows:
        return f"钱包历史（{chain}，{_short_addr(wallet_address)}）暂无记录。"

    preview = []
    for row in rows[:3]:
        symbol = _pick_first(row, "symbol", "token_symbol", "base_symbol", "name", default="TOKEN")
        action = _history_action_label(row)
        amount_usd = _pick_first(row, "amount_usd", "amountUsd", "value_usd", "trade_value_usd")
        amount_text = _fmt_price(amount_usd) if amount_usd not in (None, "") else "金额未知"
        preview.append(f"{action} {symbol} {amount_text}")
    return (
        f"钱包最近 {len(rows)} 笔（{chain}，{_short_addr(wallet_address)}）："
        + "；".join(preview)
        + "。"
    )


def _wallet_pnl_summary(chain: str, wallet_address: str, token_symbol: str, payload: dict) -> str:
    data = payload.get("data", payload)
    pnl_usd = _pick_first(data, "total_pnl_usd", "totalPnlUsd", "pnl_usd", "profit_usd")
    pnl_pct = _pick_first(data, "pnl_percent", "pnlPercent", "profit_percent", "roi")
    win_rate = _pick_first(data, "win_rate", "winRate")

    summary = _metric_parts(
        (
            f"PnL {_fmt_price(pnl_usd)}" if pnl_usd not in (None, "") else "",
            f"{_pct_text(pnl_pct)}" if pnl_pct not in (None, "") else "",
            f"胜率 {_pct_text(win_rate)}" if win_rate not in (None, "") else "",
        )
    )
    if not summary:
        summary = "接口返回了结果，但没有可直接展示的盈亏字段"
    return f"钱包在 {token_symbol}（{chain}）上的表现：{summary}。"


def _hashkey_wallet_overview_summary(payload: dict) -> str:
    total_value = payload.get("total_value_usd")
    holdings_count = payload.get("holdings_count")
    priced_count = payload.get("priced_holdings_count")
    trade_count = payload.get("trade_count")
    native_balance = payload.get("native_balance")
    parts = _metric_parts(
        (
            f"总资产 {_fmt_price(total_value)}" if total_value not in (None, "") else "",
            f"持仓 {holdings_count} 个" if holdings_count not in (None, "") else "",
            f"可定价 {priced_count} 个" if priced_count not in (None, "") else "",
            f"最近交易 {trade_count} 笔" if trade_count not in (None, "") else "",
            f"原生余额 {_fmt_amount_text(native_balance)} HSK" if native_balance not in (None, "", "0") else "",
        )
    )
    return f"HashKey 钱包概览（{_short_addr(payload.get('wallet_address'))}）：{parts or '暂无可展示数据'}。"


def _hashkey_wallet_tokens_summary(payload: dict) -> str:
    rows = payload.get("holdings") or []
    if not rows:
        return f"HashKey 钱包持仓（{_short_addr(payload.get('wallet_address'))}）为空。"

    preview = []
    for row in rows[:5]:
        symbol = _pick_first(row, "symbol", "token_symbol", "name", default="TOKEN")
        value_usd = _pick_first(row, "value_usd", "valueUsd")
        balance = _pick_first(row, "balance", "amount", default="?")
        if value_usd not in (None, ""):
            preview.append(f"{symbol} {_fmt_price(value_usd)}")
        else:
            preview.append(f"{symbol} {_fmt_amount_text(balance)}")
    return (
        f"HashKey 钱包持仓（{_short_addr(payload.get('wallet_address'))}）共 {len(rows)} 个："
        + "，".join(preview)
        + "。"
    )


def _hashkey_wallet_history_summary(payload: dict) -> str:
    rows = payload.get("items") or []
    if not rows:
        return f"HashKey 钱包历史（{_short_addr(payload.get('wallet_address'))}）暂无记录。"

    preview = []
    for row in rows[:3]:
        symbol = _pick_first(row, "token_symbol", "symbol", default="TOKEN")
        direction = str(row.get("direction") or "").strip().lower()
        if direction == "in":
            action = "转入"
        elif direction == "out":
            action = "转出"
        else:
            action = str(row.get("method") or row.get("transfer_type") or "变动").strip() or "变动"
        amount_text = str(row.get("amount") or "?").strip() or "?"
        amount_usd = row.get("amount_usd")
        if amount_usd not in (None, ""):
            preview.append(f"{action} {symbol} {_fmt_amount_text(amount_text)}（约 {_fmt_price(amount_usd)}）")
        else:
            preview.append(f"{action} {symbol} {_fmt_amount_text(amount_text)}")
    return (
        f"HashKey 最近 {len(rows)} 条代币历史（{_short_addr(payload.get('wallet_address'))}）："
        + "；".join(preview)
        + "。"
    )


def _hashkey_wallet_pnl_summary(payload: dict) -> str:
    symbol = str(payload.get("token_symbol") or "该 token").strip() or "该 token"
    summary = _metric_parts(
        (
            f"总 PnL {_fmt_price(payload.get('total_pnl_usd'))}" if payload.get("total_pnl_usd") not in (None, "") else "",
            f"已实现 {_fmt_price(payload.get('realized_pnl_usd'))}" if payload.get("realized_pnl_usd") not in (None, "") else "",
            f"未实现 {_fmt_price(payload.get('unrealized_pnl_usd'))}" if payload.get("unrealized_pnl_usd") not in (None, "") else "",
            f"现持仓 {_fmt_amount_text(payload.get('current_balance'))} {symbol}" if payload.get("current_balance") not in (None, "") else "",
            f"现值 {_fmt_price(payload.get('current_value_usd'))}" if payload.get("current_value_usd") not in (None, "") else "",
        )
    )
    suffix = ""
    if payload.get("priced_event_count", 0):
        suffix = "（基于可定价链上交易估算）"
    return f"HashKey 钱包在 {symbol} 上的表现：{summary or '暂时无法估算'}{suffix}。"


ave_wallet_overview_desc = {
    "type": "function",
    "function": {
        "name": "ave_wallet_overview",
        "description": "查看钱包/地址概览统计。适合用户说“看我的钱包”“看我的钱包概览”“这个地址怎么样”“这个钱包胜率如何”。如果用户只是泛泛地想看钱包情况、没有明确要求看持仓列表，默认用这个工具。wallet_address 可省略；省略时优先解析当前代理钱包地址。",
        "parameters": {
            "type": "object",
            "properties": {
                "wallet_address": {
                    "type": "string",
                    "description": "目标钱包地址；不填时优先使用当前代理钱包地址。",
                },
                "chain": {
                    "type": "string",
                    "description": "链名，例如 solana、bsc、eth、base、hashkey。",
                },
            },
            "required": [],
        },
    },
}


@register_function("ave_wallet_overview", ave_wallet_overview_desc, ToolType.SYSTEM_CTL)
def ave_wallet_overview(
    conn: "ConnectionHandler",
    wallet_address: str = "",
    chain: str = "",
):
    try:
        resolved_wallet, resolved_chain = _resolve_wallet_target(conn, wallet_address, chain)
        if resolved_chain == "hashkey":
            payload = hashkey_provider.get_wallet_overview(resolved_wallet)
            _try_open_hashkey_portfolio_surface(conn)
            text = _hashkey_wallet_overview_summary(payload)
            return _success_response(text, result="wallet_overview_hashkey")
        payload = _data_get(
            "/address/walletinfo",
            {
                "wallet_address": resolved_wallet,
                "chain": resolved_chain,
            },
        )
        text = _wallet_overview_summary(resolved_chain, resolved_wallet, payload)
        return _success_response(text, result="wallet_overview")
    except ValueError as exc:
        return _error_response(str(exc))
    except Exception as exc:
        return ActionResponse(action=Action.ERROR, response=str(exc))


ave_wallet_tokens_desc = {
    "type": "function",
    "function": {
        "name": "ave_wallet_tokens",
        "description": "查看钱包/地址持仓列表。只在用户明确想看“持仓列表”“有哪些币”“钱包里都有什么”时使用；不要替代泛泛的“看我的钱包/看看这个钱包”。wallet_address 可省略；省略时优先解析当前代理钱包地址。",
        "parameters": {
            "type": "object",
            "properties": {
                "wallet_address": {
                    "type": "string",
                    "description": "目标钱包地址；不填时优先使用当前代理钱包地址。",
                },
                "chain": {
                    "type": "string",
                    "description": "链名，例如 solana、bsc、eth、base、hashkey。",
                },
            },
            "required": [],
        },
    },
}


@register_function("ave_wallet_tokens", ave_wallet_tokens_desc, ToolType.SYSTEM_CTL)
def ave_wallet_tokens(
    conn: "ConnectionHandler",
    wallet_address: str = "",
    chain: str = "",
):
    try:
        resolved_wallet, resolved_chain = _resolve_wallet_target(conn, wallet_address, chain)
        if resolved_chain == "hashkey":
            payload = hashkey_provider.get_wallet_holdings_valued(resolved_wallet)
            _try_open_hashkey_portfolio_surface(conn)
            text = _hashkey_wallet_tokens_summary(payload)
            return _success_response(text, result="wallet_tokens_hashkey")
        payload = _data_get(
            "/address/walletinfo/tokens",
            {
                "wallet_address": resolved_wallet,
                "chain": resolved_chain,
            },
        )
        text = _wallet_tokens_summary(resolved_chain, resolved_wallet, payload)
        return _success_response(text, result="wallet_tokens")
    except ValueError as exc:
        return _error_response(str(exc))
    except Exception as exc:
        return ActionResponse(action=Action.ERROR, response=str(exc))


ave_wallet_history_desc = {
    "type": "function",
    "function": {
        "name": "ave_wallet_history",
        "description": "查看钱包/地址最近交易历史。适合用户说“看这个钱包最近交易”“我的钱包最近做了什么”“这个地址最近买卖了什么”。wallet_address 可省略；省略时优先解析当前代理钱包地址。",
        "parameters": {
            "type": "object",
            "properties": {
                "wallet_address": {
                    "type": "string",
                    "description": "目标钱包地址；不填时优先使用当前代理钱包地址。",
                },
                "chain": {
                    "type": "string",
                    "description": "链名，例如 solana、bsc、eth、base、hashkey。",
                },
                "token_address": {
                    "type": "string",
                    "description": "可选；只看某个 token 的历史。",
                },
            },
            "required": [],
        },
    },
}


@register_function("ave_wallet_history", ave_wallet_history_desc, ToolType.SYSTEM_CTL)
def ave_wallet_history(
    conn: "ConnectionHandler",
    wallet_address: str = "",
    chain: str = "",
    token_address: str = "",
):
    try:
        resolved_wallet, resolved_chain = _resolve_wallet_target(conn, wallet_address, chain)
        if resolved_chain == "hashkey":
            payload = hashkey_provider.get_wallet_activity(resolved_wallet)
            current_hashkey = _current_hashkey_token(conn)
            resolved_token = str(token_address or current_hashkey.get("addr") or "").strip()
            resolved_symbol = str(current_hashkey.get("symbol") or "").strip()
            if resolved_token:
                _try_open_hashkey_token_surface(
                    conn,
                    token_address=resolved_token,
                    token_symbol=resolved_symbol,
                )
            else:
                _try_open_hashkey_portfolio_surface(conn)
            text = _hashkey_wallet_history_summary(payload)
            return _success_response(text, result="wallet_history_hashkey")
        params = {
            "wallet_address": resolved_wallet,
            "chain": resolved_chain,
        }
        if token_address:
            params["token_address"] = token_address
        payload = _data_get("/address/tx", params)
        text = _wallet_history_summary(resolved_chain, resolved_wallet, payload)
        return _success_response(text, result="wallet_history")
    except ValueError as exc:
        return _error_response(str(exc))
    except Exception as exc:
        return ActionResponse(action=Action.ERROR, response=str(exc))


ave_wallet_pnl_desc = {
    "type": "function",
    "function": {
        "name": "ave_wallet_pnl",
        "description": "查看钱包在某个 token 上的盈亏。适合用户说“这个钱包在这只币上赚了吗”“看我的钱包在 BONK 上的 PnL”。token_address 可省略；若当前 AVE 页面已选中 token，则优先使用当前 token。",
        "parameters": {
            "type": "object",
            "properties": {
                "wallet_address": {
                    "type": "string",
                    "description": "目标钱包地址；不填时优先使用当前代理钱包地址。",
                },
                "chain": {
                    "type": "string",
                    "description": "链名，例如 solana、bsc、eth、base、hashkey。",
                },
                "token_address": {
                    "type": "string",
                    "description": "目标 token 合约地址；不填时优先使用当前 AVE token。",
                },
                "token_symbol": {
                    "type": "string",
                    "description": "可选；仅用于结果文案展示。",
                },
            },
            "required": [],
        },
    },
}


@register_function("ave_wallet_pnl", ave_wallet_pnl_desc, ToolType.SYSTEM_CTL)
def ave_wallet_pnl(
    conn: "ConnectionHandler",
    wallet_address: str = "",
    chain: str = "",
    token_address: str = "",
    token_symbol: str = "",
):
    try:
        current = _current_token(conn)
        current_hashkey = _current_hashkey_token(conn)
        resolved_wallet, resolved_chain = _resolve_wallet_target(
            conn,
            wallet_address,
            chain or _normalize_chain_name(current_hashkey.get("chain") or current.get("chain")),
        )
        if resolved_chain == "hashkey":
            resolved_token, resolved_symbol = _resolve_hashkey_token_address(
                token_address or current_hashkey.get("addr") or "",
                token_symbol or current_hashkey.get("symbol") or "",
            )
            if not resolved_token:
                return _error_response("请补充 token 地址或可识别的 token symbol，或先打开目标代币详情页。")
            payload = hashkey_provider.get_wallet_token_pnl(resolved_wallet, resolved_token)
            if resolved_symbol and not payload.get("token_symbol"):
                payload["token_symbol"] = resolved_symbol
            _try_open_hashkey_token_surface(
                conn,
                token_address=resolved_token,
                token_symbol=str(payload.get("token_symbol") or resolved_symbol or "").strip(),
            )
            text = _hashkey_wallet_pnl_summary(payload)
            return _success_response(text, result="wallet_pnl_hashkey")

        resolved_token = str(token_address or current.get("addr") or "").strip()
        resolved_symbol = str(token_symbol or current.get("symbol") or "该 token").strip()
        if not resolved_token:
            return _error_response("请补充 token 地址，或先打开目标代币详情页。")

        payload = _data_get(
            "/address/pnl",
            {
                "wallet_address": resolved_wallet,
                "chain": resolved_chain,
                "token_address": resolved_token,
            },
        )
        text = _wallet_pnl_summary(resolved_chain, resolved_wallet, resolved_symbol, payload)
        return _success_response(text, result="wallet_pnl")
    except ValueError as exc:
        return _error_response(str(exc))
    except Exception as exc:
        return ActionResponse(action=Action.ERROR, response=str(exc))
