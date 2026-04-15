"""Tests for MiraAnchor — on-chain audit trail module."""
import hashlib
import json
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    """Run without real credentials by default."""
    monkeypatch.delenv("MIRA_AUDIT_LOG_ADDRESS", raising=False)
    monkeypatch.delenv("MIRA_AGENT_PRIVATE_KEY", raising=False)


@pytest.fixture
def anchor_disabled():
    from mira_anchor import MiraAnchor
    a = MiraAnchor()
    assert not a._enabled
    return a


@pytest.fixture
def anchor_enabled(monkeypatch):
    monkeypatch.setenv("MIRA_AUDIT_LOG_ADDRESS", "0x" + "a" * 40)
    monkeypatch.setenv("MIRA_AGENT_PRIVATE_KEY",
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")  # anvil key

    with patch("mira_anchor.Web3") as mock_web3_cls:
        mock_w3 = MagicMock()
        mock_web3_cls.return_value = mock_w3
        mock_web3_cls.HTTPProvider = MagicMock()
        mock_web3_cls.to_checksum_address = lambda x: x
        mock_w3.eth.contract.return_value = MagicMock()
        mock_w3.eth.account.from_key.return_value = MagicMock(address="0xAgent")
        mock_w3.eth.gas_price = 1_000_000_000
        mock_w3.eth.get_transaction_count.return_value = 0

        from mira_anchor import MiraAnchor
        a = MiraAnchor()
        a._enabled = True
        yield a


# ── Tests: disabled mode ──────────────────────────────────────────────────────

def test_anchor_disabled_returns_none(anchor_disabled):
    from mira_anchor import ActionType
    result = anchor_disabled.anchor("0x1234", ActionType.SWAP_QUOTED, "test", {})
    assert result is None


def test_confirm_disabled_is_noop(anchor_disabled):
    # Should not raise
    anchor_disabled.confirm(1, "0xdeadbeef")


def test_get_recent_disabled_returns_empty(anchor_disabled):
    result = anchor_disabled.get_recent("0x1234")
    assert result == []


# ── Tests: data hash ──────────────────────────────────────────────────────────

def test_data_hash_is_deterministic():
    from mira_anchor import MiraAnchor
    a = MiraAnchor()
    payload = {"symbol": "HSK", "amount": "100", "ts": 1234567890}
    h1 = a._data_hash(payload)
    h2 = a._data_hash(payload)
    assert h1 == h2


def test_data_hash_is_32_bytes():
    from mira_anchor import MiraAnchor
    a = MiraAnchor()
    h = a._data_hash({"test": "value"})
    assert len(h) == 32


def test_data_hash_differs_for_different_payloads():
    from mira_anchor import MiraAnchor
    a = MiraAnchor()
    h1 = a._data_hash({"amount": "100"})
    h2 = a._data_hash({"amount": "200"})
    assert h1 != h2


def test_data_hash_matches_sha256():
    from mira_anchor import MiraAnchor
    a = MiraAnchor()
    payload = {"key": "value"}
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    expected = hashlib.sha256(raw).digest()
    assert a._data_hash(payload) == expected


# ── Tests: ActionType enum ────────────────────────────────────────────────────

def test_action_types_match_contract():
    from mira_anchor import ActionType
    assert ActionType.SWAP_EXECUTED      == 0
    assert ActionType.SWAP_QUOTED        == 1
    assert ActionType.ALERT_FIRED        == 2
    assert ActionType.PORTFOLIO_ANALYZED == 3
    assert ActionType.RISK_FLAGGED       == 4
    assert ActionType.YIELD_RECOMMENDED  == 5
    assert ActionType.PAYMENT_CREATED    == 6
    assert ActionType.STRATEGY_TRIGGERED == 7


# ── Tests: anchor with mocked web3 ───────────────────────────────────────────

def test_anchor_calls_contract_function(anchor_enabled):
    from mira_anchor import ActionType

    mock_fn = MagicMock()
    mock_fn.build_transaction.return_value = {"gas": 200_000}
    anchor_enabled.contract.functions.anchor.return_value = mock_fn

    mock_signed = MagicMock()
    mock_signed.raw_transaction = b"raw"
    anchor_enabled.account.sign_transaction.return_value = mock_signed

    mock_receipt = MagicMock()
    mock_receipt.__getitem__ = lambda self, k: [] if k == "logs" else None
    anchor_enabled.w3.eth.send_raw_transaction.return_value = b"txhash"
    anchor_enabled.w3.eth.wait_for_transaction_receipt.return_value = {"logs": []}

    result = anchor_enabled.anchor(
        "0xWallet", ActionType.SWAP_QUOTED, "Swap quoted: 100 USDC → HSK", {"amount": "100"}
    )
    anchor_enabled.contract.functions.anchor.assert_called_once()


def test_anchor_returns_none_on_exception(anchor_enabled):
    from mira_anchor import ActionType
    anchor_enabled.contract.functions.anchor.side_effect = Exception("RPC error")
    result = anchor_enabled.anchor("0xWallet", ActionType.ALERT_FIRED, "test", {})
    assert result is None
# 20 Python tests
