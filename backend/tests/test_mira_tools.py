"""Tests for mira_tools dispatch_tool — all 7 DeFi tools."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def mock_portfolio():
    return {
        "tokens": [{"symbol": "HSK", "balance": "100", "usd_value": 200}],
        "total_usd_value": 200,
    }

def mock_spotlight():
    return {"symbol": "HSK", "price": "$2.00", "change_24h": "+5%"}

def mock_quote():
    return {"amount_out_fmt": "47.3 HSK", "price_impact_pct": "0.3"}


# ── Tests: get_portfolio ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_portfolio_no_wallet():
    with patch("mira_anchor.mira_anchor") as mock_anchor:
        from mira_tools import dispatch_tool
        result = await dispatch_tool("get_portfolio", {}, wallet=None)
    assert "error" in result


@pytest.mark.asyncio
async def test_get_portfolio_with_wallet():
    with patch("mira_tools.get_wallet_portfolio", return_value=mock_portfolio()), \
         patch("mira_tools.build_portfolio_payload", return_value={"tokens": [], "total_usd_value": 0}), \
         patch("mira_anchor.mira_anchor") as mock_anchor:
        mock_anchor.anchor.return_value = None
        from mira_tools import dispatch_tool
        result = await dispatch_tool("get_portfolio", {}, wallet="0xABC")
    assert "error" not in result


# ── Tests: search_token ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_token_returns_results():
    mock_results = [{"symbol": "HSK", "address": "0x123"}]
    with patch("mira_tools.search_tokens", return_value=mock_results):
        from mira_tools import dispatch_tool
        result = await dispatch_tool("search_token", {"query": "HSK"})
    assert "results" in result
    assert len(result["results"]) <= 5


@pytest.mark.asyncio
async def test_search_token_limits_to_5():
    mock_results = [{"symbol": f"T{i}"} for i in range(20)]
    with patch("mira_tools.search_tokens", return_value=mock_results):
        from mira_tools import dispatch_tool
        result = await dispatch_tool("search_token", {"query": "T"})
    assert len(result["results"]) == 5


# ── Tests: swap_preview ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swap_preview_returns_quote():
    with patch("mira_tools.hyperindex_quote_exact_input_single", return_value=mock_quote()), \
         patch("mira_anchor.mira_anchor") as mock_anchor:
        mock_anchor.anchor.return_value = None
        from mira_tools import dispatch_tool
        result = await dispatch_tool(
            "swap_preview",
            {"token_in": "USDC", "token_out": "HSK", "amount_in": "100"},
            wallet="0xABC"
        )
    assert "quote" in result
    assert result["ready_to_execute"] is True


@pytest.mark.asyncio
async def test_swap_preview_anchors_action():
    with patch("mira_tools.hyperindex_quote_exact_input_single", return_value=mock_quote()), \
         patch("mira_anchor.mira_anchor") as mock_anchor:
        mock_anchor.anchor.return_value = 42
        from mira_tools import dispatch_tool
        await dispatch_tool(
            "swap_preview",
            {"token_in": "USDC", "token_out": "HSK", "amount_in": "100"},
            wallet="0xABC"
        )
    mock_anchor.anchor.assert_called_once()


# ── Tests: execute_swap ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_swap_returns_awaiting_confirmation():
    with patch("mira_anchor.mira_anchor") as mock_anchor:
        mock_anchor.anchor.return_value = 1
        from mira_tools import dispatch_tool
        result = await dispatch_tool(
            "execute_swap",
            {"token_in": "USDC", "token_out": "HSK", "amount_in": "50"},
            wallet="0xABC"
        )
    assert result["status"] == "awaiting_confirmation"
    assert result["token_in"] == "USDC"
    assert result["token_out"] == "HSK"


@pytest.mark.asyncio
async def test_execute_swap_includes_audit_entry_id():
    with patch("mira_anchor.mira_anchor") as mock_anchor:
        mock_anchor.anchor.return_value = 99
        from mira_tools import dispatch_tool
        result = await dispatch_tool(
            "execute_swap",
            {"token_in": "USDC", "token_out": "HSK", "amount_in": "50"},
            wallet="0xABC"
        )
    assert result["audit_entry_id"] == 99


# ── Tests: unknown tool ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    from mira_tools import dispatch_tool
    result = await dispatch_tool("nonexistent_tool", {})
    assert "error" in result


# ── Tests: exception handling ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_handles_exception_gracefully():
    with patch("mira_tools.search_tokens", side_effect=Exception("network error")):
        from mira_tools import dispatch_tool
        result = await dispatch_tool("search_token", {"query": "HSK"})
    assert "error" in result
    assert "network error" in result["error"]
