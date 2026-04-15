"""Tests for hashkey_capabilities — RPC, BlockScout, HyperIndex."""
import pytest
from unittest.mock import patch, MagicMock
import json


# ── Tests: address normalization ──────────────────────────────────────────────

def test_normalize_address_valid():
    from hashkey_capabilities import _normalize_address
    result = _normalize_address("0xABCDEF1234567890ABCDef1234567890abcdef12")
    assert result == "0x" + "abcdef1234567890abcdef1234567890abcdef12"


def test_normalize_address_invalid_raises():
    from hashkey_capabilities import _normalize_address
    with pytest.raises(ValueError):
        _normalize_address("not_an_address")


def test_normalize_address_too_short_raises():
    from hashkey_capabilities import _normalize_address
    with pytest.raises(ValueError):
        _normalize_address("0x1234")


# ── Tests: HTTP helper ────────────────────────────────────────────────────────

def test_http_json_get_success():
    from hashkey_capabilities import _http_json
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"result": "ok"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = _http_json("https://example.com/api")
    assert result == {"result": "ok"}


def test_http_json_raises_on_http_error():
    from hashkey_capabilities import _http_json, HashKeyApiError
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        "url", 404, "Not Found", {}, None
    )):
        with pytest.raises(HashKeyApiError):
            _http_json("https://example.com/api")


# ── Tests: constants ──────────────────────────────────────────────────────────

def test_hashkey_rpc_url():
    from hashkey_capabilities import HASHKEY_MAINNET_RPC
    assert "hsk.xyz" in HASHKEY_MAINNET_RPC


def test_native_symbol():
    from hashkey_capabilities import HASHKEY_NATIVE_SYMBOL
    assert HASHKEY_NATIVE_SYMBOL == "HSK"


def test_hyperindex_addresses_are_valid_evm():
    from hashkey_capabilities import HYPERINDEX_V3_ROUTER, HYPERINDEX_V3_QUOTER, HYPERINDEX_WHSK
    for addr in (HYPERINDEX_V3_ROUTER, HYPERINDEX_V3_QUOTER, HYPERINDEX_WHSK):
        assert addr.startswith("0x")
        assert len(addr) == 42


# ── Tests: token search ───────────────────────────────────────────────────────

def test_search_tokens_returns_list():
    mock_data = {"items": [{"symbol": "HSK", "address": "0x123"}]}
    with patch("hashkey_capabilities._http_json", return_value=mock_data):
        from hashkey_capabilities import search_tokens
        result = search_tokens("HSK")
    assert isinstance(result, list)


def test_search_tokens_empty_returns_list():
    with patch("hashkey_capabilities._http_json", return_value={"items": []}):
        from hashkey_capabilities import search_tokens
        result = search_tokens("UNKNOWN")
    assert isinstance(result, list)
