"""
MIRA DeFi Tools — HashKey Chain actions exposed to Claude via tool use
"""
import json
from hashkey_provider import (
    get_wallet_portfolio,
    get_token_spotlight,
    search_tokens,
    get_wallet_activity,
)
from hashkey_ave_adapter import (
    build_portfolio_payload,
    build_spotlight_payload,
    build_feed_payload,
)
from hashkey_capabilities import (
    hyperindex_quote_exact_input_single,
    blockscout_search,
)

MIRA_TOOLS = [
    {
        "name": "get_portfolio",
        "description": "Get the user's full wallet portfolio on HashKey Chain — token balances, USD values, PnL per token.",
        "input_schema": {
            "type": "object",
            "properties": {
                "wallet": {"type": "string", "description": "Wallet address (optional, uses session wallet if omitted)"}
            },
        },
    },
    {
        "name": "get_spotlight",
        "description": "Get detailed token info — price, chart, liquidity, holders, 24h volume, market cap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_address": {"type": "string", "description": "Token contract address on HashKey Chain"},
                "symbol": {"type": "string", "description": "Token symbol e.g. HSK, USDC"},
            },
        },
    },
    {
        "name": "search_token",
        "description": "Search for a token by name or symbol on HashKey Chain.",
        "input_schema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Token name or symbol to search"},
            },
        },
    },
    {
        "name": "get_activity",
        "description": "Get recent transaction history for the user's wallet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "wallet": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "swap_preview",
        "description": "Preview a token swap — get quote, price impact, and estimated output before executing.",
        "input_schema": {
            "type": "object",
            "required": ["token_in", "token_out", "amount_in"],
            "properties": {
                "token_in":  {"type": "string", "description": "Input token address or symbol"},
                "token_out": {"type": "string", "description": "Output token address or symbol"},
                "amount_in": {"type": "string", "description": "Amount to swap (human readable)"},
            },
        },
    },
    {
        "name": "execute_swap",
        "description": "Execute a token swap after user confirmation. Only call after swap_preview and user confirms.",
        "input_schema": {
            "type": "object",
            "required": ["token_in", "token_out", "amount_in"],
            "properties": {
                "token_in":     {"type": "string"},
                "token_out":    {"type": "string"},
                "amount_in":    {"type": "string"},
                "slippage_bps": {"type": "integer", "default": 100},
            },
        },
    },
    {
        "name": "create_payment_link",
        "description": "Create an HSP (HashKey Settlement Protocol) stablecoin payment link for USDC/USDT.",
        "input_schema": {
            "type": "object",
            "required": ["amount_usd", "description"],
            "properties": {
                "amount_usd":  {"type": "number", "description": "Amount in USD"},
                "description": {"type": "string", "description": "Payment description"},
                "order_id":    {"type": "string", "description": "Optional order reference"},
            },
        },
    },
]


async def dispatch_tool(name: str, inputs: dict, wallet: str = None) -> dict:
    """Route tool calls to HashKey Chain data functions, anchoring every action on-chain."""
    from mira_anchor import mira_anchor, ActionType
    try:
        if name == "get_portfolio":
            addr = inputs.get("wallet") or wallet
            if not addr:
                return {"error": "No wallet connected"}
            raw = get_wallet_portfolio(addr)
            result = build_portfolio_payload(raw)
            mira_anchor.anchor(addr, ActionType.PORTFOLIO_ANALYZED,
                f"Portfolio analyzed: {len(result.get('tokens',[]))} tokens", result)
            return result

        elif name == "get_spotlight":
            addr = inputs.get("token_address")
            symbol = inputs.get("symbol")
            if not addr and symbol:
                results = search_tokens(symbol)
                if results:
                    addr = results[0].get("address")
            if not addr:
                return {"error": "Token not found"}
            raw = get_token_spotlight(addr)
            result = build_spotlight_payload(raw)
            if wallet:
                mira_anchor.anchor(wallet, ActionType.PORTFOLIO_ANALYZED,
                    f"Token spotlight: {symbol or addr[:8]}", {"token": addr})
            return result

        elif name == "search_token":
            results = search_tokens(inputs["query"])
            return {"results": results[:5]}

        elif name == "get_activity":
            addr = inputs.get("wallet") or wallet
            if not addr:
                return {"error": "No wallet connected"}
            activity = get_wallet_activity(addr, limit=inputs.get("limit", 10))
            return {"activity": activity}

        elif name == "swap_preview":
            quote = hyperindex_quote_exact_input_single(
                token_in=inputs["token_in"],
                token_out=inputs["token_out"],
                amount_in=inputs["amount_in"],
            )
            if wallet:
                mira_anchor.anchor(wallet, ActionType.SWAP_QUOTED,
                    f"Swap quoted: {inputs['amount_in']} {inputs['token_in']} → {inputs['token_out']}",
                    {"quote": quote, "inputs": inputs})
            return {"quote": quote, "ready_to_execute": True}

        elif name == "execute_swap":
            if wallet:
                entry_id = mira_anchor.anchor(wallet, ActionType.SWAP_EXECUTED,
                    f"Swap executed: {inputs['amount_in']} {inputs['token_in']} → {inputs['token_out']}",
                    inputs)
            return {
                "status": "awaiting_confirmation",
                "token_in": inputs["token_in"],
                "token_out": inputs["token_out"],
                "amount_in": inputs["amount_in"],
                "slippage_bps": inputs.get("slippage_bps", 100),
                "audit_entry_id": entry_id if wallet else None,
                "message": "Swap confirmation sent. Waiting for user approval.",
            }

        elif name == "create_payment_link":
            from mira_hsp import create_payment_link
            import uuid
            result = await create_payment_link(
                amount_usd=float(inputs.get("amount_usd", 0)),
                description=inputs.get("description", "MIRA DeFi Payment"),
                order_id=inputs.get("order_id", str(uuid.uuid4())[:8]),
            )
            if wallet and "error" not in result:
                mira_anchor.anchor(wallet, ActionType.PAYMENT_CREATED,
                    f"HSP payment link: ${inputs.get('amount_usd')} USDC", result)
            return result

        return {"error": f"Unknown tool: {name}"}

    except Exception as e:
        return {"error": str(e)}
# 7 DeFi tools for Bedrock tool use
# anchor wired into tools
