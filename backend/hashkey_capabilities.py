"""
Minimal HashKey Chain capability layer for Ava Box.

This module intentionally uses only the standard library so we can validate
HashKey-native read paths before wiring them into the existing AVE backend.

Current scope:
  - RPC health / chain info
  - BlockScout token search and wallet inspection
  - HyperIndex V3 pool lookup
  - HyperIndex V3 exact-input quote
  - Native HSK -> token market-buy simulation via eth_call
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request


HASHKEY_MAINNET_RPC = "https://mainnet.hsk.xyz"
HASHKEY_BLOCKSCOUT_V2 = "https://hashkey.blockscout.com/api/v2"

HASHKEY_NATIVE_SYMBOL = "HSK"
HASHKEY_NATIVE_ADDRESS = "0x0000000000000000000000000000000000000000"
HYPERINDEX_WHSK = "0xb210d2120d57b758ee163cffb43e73728c471cf1"
HYPERINDEX_V3_ROUTER = "0x862de2db0d74fb20f1ab9777b7893631cb91e761"
HYPERINDEX_V3_QUOTER = "0x1e7bce2cb6b1f3f61232878605790f09ed22c8e5"
HYPERINDEX_V3_SUPPORTED_FEES = (100, 500, 3000, 10000)

_HEX_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

_SELECTOR_SYMBOL = "0x95d89b41"
_SELECTOR_NAME = "0x06fdde03"
_SELECTOR_DECIMALS = "0x313ce567"
_SELECTOR_BALANCE_OF = "0x70a08231"
_SELECTOR_ALLOWANCE = "0xdd62ed3e"
_SELECTOR_GET_POOL = "0x1698ee82"
_SELECTOR_QUOTE_EXACT_INPUT_SINGLE = "0xc6a5026a"
_SELECTOR_EXACT_INPUT_SINGLE = "0x414bf389"


class HashKeyApiError(RuntimeError):
    """Raised when a HashKey RPC / explorer capability call fails."""


def _http_json(url: str, *, payload: dict | None = None, timeout: int = 15) -> dict | list:
    data = None
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "AvaBox-HashKey-Smoke/1.0",
    }
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode()
        method = "POST"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode() if exc.fp else ""
        raise HashKeyApiError(f"HTTP {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise HashKeyApiError(f"Network error for {url}: {exc}") from exc


def _normalize_address(address: str) -> str:
    text = str(address or "").strip()
    if not _HEX_ADDRESS_RE.match(text):
        raise ValueError(f"Invalid EVM address: {address}")
    return "0x" + text[2:].lower()


def _quote_url(base: str, **params: str) -> str:
    filtered = {key: value for key, value in params.items() if value is not None}
    if not filtered:
        return base
    return f"{base}?{urllib.parse.urlencode(filtered)}"


def _rpc_call(method: str, params: list) -> str | dict | list:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    response = _http_json(HASHKEY_MAINNET_RPC, payload=payload)
    if not isinstance(response, dict):
        raise HashKeyApiError(f"Unexpected RPC response for {method}: {response!r}")
    if response.get("error"):
        raise HashKeyApiError(f"RPC {method} failed: {response['error']}")
    return response.get("result")


def _rpc_eth_call(
    to: str,
    data: str,
    *,
    from_address: str | None = None,
    value: int | None = None,
    block: str = "latest",
) -> str:
    tx = {
        "to": _normalize_address(to),
        "data": data,
    }
    if from_address:
        tx["from"] = _normalize_address(from_address)
    if value is not None:
        tx["value"] = hex(int(value))
    result = _rpc_call("eth_call", [tx, block])
    if not isinstance(result, str):
        raise HashKeyApiError(f"Unexpected eth_call result: {result!r}")
    return result


def _encode_uint(value: int) -> str:
    numeric = int(value)
    if numeric < 0:
        raise ValueError(f"uint cannot be negative: {value}")
    return f"{numeric:064x}"


def _encode_address(address: str) -> str:
    return ("0" * 24) + _normalize_address(address)[2:]


def _decode_uint(result_hex: str, word_index: int = 0) -> int:
    body = str(result_hex or "")
    if body.startswith("0x"):
        body = body[2:]
    start = word_index * 64
    end = start + 64
    if len(body) < end:
        raise HashKeyApiError(f"Result too short to decode uint at word {word_index}: {result_hex}")
    return int(body[start:end], 16)


def _decode_address(result_hex: str, word_index: int = 0) -> str:
    body = str(result_hex or "")
    if body.startswith("0x"):
        body = body[2:]
    start = word_index * 64
    end = start + 64
    if len(body) < end:
        raise HashKeyApiError(f"Result too short to decode address at word {word_index}: {result_hex}")
    return "0x" + body[end - 40:end].lower()


def _decode_string(result_hex: str) -> str:
    body = str(result_hex or "")
    if body.startswith("0x"):
        body = body[2:]
    if len(body) < 128:
        raise HashKeyApiError(f"Result too short to decode string: {result_hex}")
    offset = int(body[0:64], 16)
    length_index = offset * 2
    length = int(body[length_index:length_index + 64], 16)
    data_index = length_index + 64
    data_hex = body[data_index:data_index + length * 2]
    return bytes.fromhex(data_hex).decode("utf-8")


def _encode_get_pool_call(token_a: str, token_b: str, fee: int) -> str:
    return _SELECTOR_GET_POOL + _encode_address(token_a) + _encode_address(token_b) + _encode_uint(fee)


def _encode_quote_exact_input_single_call(
    token_in: str,
    token_out: str,
    amount_in: int,
    fee: int,
    *,
    sqrt_price_limit_x96: int = 0,
) -> str:
    return (
        _SELECTOR_QUOTE_EXACT_INPUT_SINGLE
        + _encode_address(token_in)
        + _encode_address(token_out)
        + _encode_uint(amount_in)
        + _encode_uint(fee)
        + _encode_uint(sqrt_price_limit_x96)
    )


def _encode_exact_input_single_call(
    token_in: str,
    token_out: str,
    fee: int,
    recipient: str,
    deadline: int,
    amount_in: int,
    amount_out_minimum: int,
    *,
    sqrt_price_limit_x96: int = 0,
) -> str:
    return (
        _SELECTOR_EXACT_INPUT_SINGLE
        + _encode_address(token_in)
        + _encode_address(token_out)
        + _encode_uint(fee)
        + _encode_address(recipient)
        + _encode_uint(deadline)
        + _encode_uint(amount_in)
        + _encode_uint(amount_out_minimum)
        + _encode_uint(sqrt_price_limit_x96)
    )


def _as_wrapped_native(address: str) -> str:
    normalized = _normalize_address(address)
    if normalized == HASHKEY_NATIVE_ADDRESS:
        return HYPERINDEX_WHSK
    return normalized


def rpc_chain_id() -> int:
    return int(str(_rpc_call("eth_chainId", [])), 16)


def rpc_block_number() -> int:
    return int(str(_rpc_call("eth_blockNumber", [])), 16)


def rpc_get_balance(address: str) -> int:
    return int(str(_rpc_call("eth_getBalance", [_normalize_address(address), "latest"])), 16)


def erc20_symbol(address: str) -> str:
    return _decode_string(_rpc_eth_call(_normalize_address(address), _SELECTOR_SYMBOL))


def erc20_name(address: str) -> str:
    return _decode_string(_rpc_eth_call(_normalize_address(address), _SELECTOR_NAME))


def erc20_decimals(address: str) -> int:
    return _decode_uint(_rpc_eth_call(_normalize_address(address), _SELECTOR_DECIMALS))


def erc20_balance_of(token_address: str, owner_address: str) -> int:
    data = _SELECTOR_BALANCE_OF + _encode_address(owner_address)
    return _decode_uint(_rpc_eth_call(_normalize_address(token_address), data))


def erc20_allowance(token_address: str, owner_address: str, spender_address: str) -> int:
    data = _SELECTOR_ALLOWANCE + _encode_address(owner_address) + _encode_address(spender_address)
    return _decode_uint(_rpc_eth_call(_normalize_address(token_address), data))


def search_tokens(query: str) -> list[dict]:
    url = _quote_url(f"{HASHKEY_BLOCKSCOUT_V2}/search", q=query)
    response = _http_json(url)
    if not isinstance(response, dict):
        raise HashKeyApiError(f"Unexpected BlockScout search response: {response!r}")
    return [item for item in response.get("items", []) if isinstance(item, dict) and item.get("type") == "token"]


def get_token_detail(address: str) -> dict:
    return _http_json(f"{HASHKEY_BLOCKSCOUT_V2}/tokens/{_normalize_address(address)}")


def get_address_token_balances(address: str) -> list[dict]:
    response = _http_json(f"{HASHKEY_BLOCKSCOUT_V2}/addresses/{_normalize_address(address)}/token-balances")
    if not isinstance(response, list):
        raise HashKeyApiError(f"Unexpected token balance response: {response!r}")
    return response


def get_address_token_transfers(address: str, page_params: dict | None = None) -> dict:
    url = _quote_url(
        f"{HASHKEY_BLOCKSCOUT_V2}/addresses/{_normalize_address(address)}/token-transfers",
        **(page_params or {}),
    )
    response = _http_json(url)
    if not isinstance(response, dict):
        raise HashKeyApiError(f"Unexpected token transfer response: {response!r}")
    return response


def get_v3_pool(token_a: str, token_b: str, fee: int) -> str | None:
    data = _encode_get_pool_call(_as_wrapped_native(token_a), _as_wrapped_native(token_b), fee)
    pool = _decode_address(_rpc_eth_call(HYPERINDEX_V3_ROUTER, data))
    if pool == HASHKEY_NATIVE_ADDRESS:
        return None
    return pool


def list_v3_pools(
    token_a: str,
    token_b: str,
    *,
    fees: tuple[int, ...] = HYPERINDEX_V3_SUPPORTED_FEES,
) -> list[dict]:
    pools = []
    for fee in fees:
        try:
            pool = get_v3_pool(token_a, token_b, fee)
        except HashKeyApiError:
            continue
        if pool:
            pools.append({"fee": fee, "pool_address": pool})
    return pools


def quote_exact_input_single(
    token_in: str,
    token_out: str,
    amount_in: int,
    fee: int,
    *,
    sqrt_price_limit_x96: int = 0,
) -> dict:
    data = _encode_quote_exact_input_single_call(
        _as_wrapped_native(token_in),
        _as_wrapped_native(token_out),
        amount_in,
        fee,
        sqrt_price_limit_x96=sqrt_price_limit_x96,
    )
    result = _rpc_eth_call(HYPERINDEX_V3_QUOTER, data)
    return {
        "token_in": _as_wrapped_native(token_in),
        "token_out": _as_wrapped_native(token_out),
        "amount_in": int(amount_in),
        "fee": int(fee),
        "amount_out": _decode_uint(result, 0),
        "sqrt_price_x96_after": _decode_uint(result, 1),
        "initialized_ticks_crossed": _decode_uint(result, 2),
        "gas_estimate": _decode_uint(result, 3),
    }


def quote_best_exact_input(
    token_in: str,
    token_out: str,
    amount_in: int,
    *,
    fees: tuple[int, ...] = HYPERINDEX_V3_SUPPORTED_FEES,
) -> dict | None:
    best = None
    for fee in fees:
        try:
            quote = quote_exact_input_single(token_in, token_out, amount_in, fee)
        except HashKeyApiError:
            continue
        if best is None or quote["amount_out"] > best["amount_out"]:
            best = quote
    return best


def simulate_native_buy_exact_input_single(
    token_out: str,
    amount_in: int,
    *,
    fee: int,
    recipient: str,
    from_address: str,
    deadline: int,
    amount_out_minimum: int = 1,
    sqrt_price_limit_x96: int = 0,
) -> dict:
    """
    Simulate a native HSK -> token swap via router exactInputSingle.

    HyperIndex treats native HSK as payable value while the swap path itself uses
    WHSK as tokenIn. This eth_call proves that the router entry is live before we
    wire real execution into the backend.
    """

    data = _encode_exact_input_single_call(
        HYPERINDEX_WHSK,
        token_out,
        fee,
        recipient,
        deadline,
        amount_in,
        amount_out_minimum,
        sqrt_price_limit_x96=sqrt_price_limit_x96,
    )
    result = _rpc_eth_call(
        HYPERINDEX_V3_ROUTER,
        data,
        from_address=from_address,
        value=amount_in,
    )
    return {
        "token_in": HYPERINDEX_WHSK,
        "token_out": _normalize_address(token_out),
        "fee": int(fee),
        "amount_in": int(amount_in),
        "amount_out": _decode_uint(result, 0),
        "recipient": _normalize_address(recipient),
        "from_address": _normalize_address(from_address),
        "deadline": int(deadline),
    }


def simulate_sell_exact_input_single(
    token_in: str,
    amount_in: int,
    *,
    token_out: str = HASHKEY_NATIVE_ADDRESS,
    fee: int,
    recipient: str,
    from_address: str,
    deadline: int,
    amount_out_minimum: int = 1,
    sqrt_price_limit_x96: int = 0,
) -> dict:
    """
    Simulate an ERC20 -> native HSK sell path through the V3 router.

    This is mainly used to verify the real sell interface wiring. If the wallet
    lacks allowance, the router currently reverts with `STF`, which is still a
    valid proof that the execution path is correctly wired.
    """

    data = _encode_exact_input_single_call(
        token_in,
        _as_wrapped_native(token_out),
        fee,
        recipient,
        deadline,
        amount_in,
        amount_out_minimum,
        sqrt_price_limit_x96=sqrt_price_limit_x96,
    )
    result = _rpc_eth_call(
        HYPERINDEX_V3_ROUTER,
        data,
        from_address=from_address,
        value=0,
    )
    return {
        "token_in": _normalize_address(token_in),
        "token_out": _as_wrapped_native(token_out),
        "fee": int(fee),
        "amount_in": int(amount_in),
        "amount_out": _decode_uint(result, 0),
        "recipient": _normalize_address(recipient),
        "from_address": _normalize_address(from_address),
        "deadline": int(deadline),
    }
# HashKey Chain capability layer
