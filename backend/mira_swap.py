"""
MIRA Swap Executor — signs and sends HyperIndex V3 swaps via ethers.js bridge
The frontend holds the wallet signer; backend sends the unsigned tx, frontend signs it.
"""
from __future__ import annotations
import json
from hashkey_capabilities import (
    hyperindex_quote_exact_input_single,
    HYPERINDEX_V3_ROUTER,
    HYPERINDEX_WHSK,
    HASHKEY_NATIVE_ADDRESS,
    _normalize_address,
)

# HyperIndex V3 exactInputSingle ABI (minimal)
EXACT_INPUT_SINGLE_ABI = [{
    "inputs": [{
        "components": [
            {"name": "tokenIn",           "type": "address"},
            {"name": "tokenOut",          "type": "address"},
            {"name": "fee",               "type": "uint24"},
            {"name": "recipient",         "type": "address"},
            {"name": "deadline",          "type": "uint256"},
            {"name": "amountIn",          "type": "uint256"},
            {"name": "amountOutMinimum",  "type": "uint256"},
            {"name": "sqrtPriceLimitX96", "type": "uint160"},
        ],
        "name": "params",
        "type": "tuple",
    }],
    "name": "exactInputSingle",
    "outputs": [{"name": "amountOut", "type": "uint256"}],
    "stateMutability": "payable",
    "type": "function",
}]


def build_swap_tx(
    token_in: str,
    token_out: str,
    amount_in_wei: int,
    recipient: str,
    fee: int = 3000,
    slippage_bps: int = 100,
) -> dict:
    """
    Build an unsigned swap transaction payload for the frontend to sign.
    Returns a dict the frontend can pass directly to ethers signer.sendTransaction().
    """
    # Get quote for minimum output
    try:
        quote = hyperindex_quote_exact_input_single(
            token_in=token_in,
            token_out=token_out,
            amount_in=str(amount_in_wei),
            fee=fee,
        )
        amount_out_raw = int(quote.get("amount_out_raw", 0))
    except Exception:
        amount_out_raw = 0

    # Apply slippage
    amount_out_min = int(amount_out_raw * (10000 - slippage_bps) / 10000)

    import time
    deadline = int(time.time()) + 300  # 5 min

    # Encode calldata for exactInputSingle
    # We return the raw params — frontend uses ethers Interface to encode
    is_native_in = token_in.lower() in (HASHKEY_NATIVE_ADDRESS, "hsk", "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
    actual_token_in = HYPERINDEX_WHSK if is_native_in else token_in

    return {
        "to": HYPERINDEX_V3_ROUTER,
        "value": hex(amount_in_wei) if is_native_in else "0x0",
        "router_abi": EXACT_INPUT_SINGLE_ABI,
        "method": "exactInputSingle",
        "params": {
            "tokenIn":           actual_token_in,
            "tokenOut":          token_out,
            "fee":               fee,
            "recipient":         recipient,
            "deadline":          deadline,
            "amountIn":          amount_in_wei,
            "amountOutMinimum":  amount_out_min,
            "sqrtPriceLimitX96": 0,
        },
        "quote": quote,
    }
# HyperIndex V3 swap builder
