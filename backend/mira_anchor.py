"""
MIRA On-Chain Audit Anchor
Anchors every MIRA decision to MiraAuditLog.sol on HashKey Chain.
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from enum import IntEnum
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# ── Action types (must match MiraAuditLog.sol enum) ──────────────────────────

class ActionType(IntEnum):
    SWAP_EXECUTED      = 0
    SWAP_QUOTED        = 1
    ALERT_FIRED        = 2
    PORTFOLIO_ANALYZED = 3
    RISK_FLAGGED       = 4
    YIELD_RECOMMENDED  = 5
    PAYMENT_CREATED    = 6
    STRATEGY_TRIGGERED = 7


# ── Minimal ABI ──────────────────────────────────────────────────────────────

AUDIT_LOG_ABI = [
    {
        "inputs": [
            {"name": "wallet",   "type": "address"},
            {"name": "action",   "type": "uint8"},
            {"name": "dataHash", "type": "bytes32"},
            {"name": "summary",  "type": "string"},
        ],
        "name": "anchor",
        "outputs": [{"name": "id", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "id",     "type": "uint256"},
            {"name": "txHash", "type": "bytes32"},
        ],
        "name": "confirm",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "wallet", "type": "address"},
            {"name": "n",      "type": "uint256"},
        ],
        "name": "getRecentEntries",
        "outputs": [{
            "components": [
                {"name": "id",        "type": "uint256"},
                {"name": "wallet",    "type": "address"},
                {"name": "action",    "type": "uint8"},
                {"name": "dataHash",  "type": "bytes32"},
                {"name": "summary",   "type": "string"},
                {"name": "timestamp", "type": "uint256"},
                {"name": "confirmed", "type": "bool"},
                {"name": "txHash",    "type": "bytes32"},
            ],
            "name": "",
            "type": "tuple[]",
        }],
        "stateMutability": "view",
        "type": "function",
    },
]


# ── Anchor client ─────────────────────────────────────────────────────────────

class MiraAnchor:
    def __init__(self):
        rpc = os.getenv("HASHKEY_RPC", "https://mainnet.hsk.xyz")
        self.w3 = Web3(Web3.HTTPProvider(rpc))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        contract_addr = os.getenv("MIRA_AUDIT_LOG_ADDRESS")
        self.contract = None
        if contract_addr:
            self.contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(contract_addr),
                abi=AUDIT_LOG_ABI,
            )

        pk = os.getenv("MIRA_AGENT_PRIVATE_KEY")
        self.account = self.w3.eth.account.from_key(pk) if pk else None
        self._enabled = bool(contract_addr and pk)

    def _data_hash(self, payload: dict) -> bytes:
        raw = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).digest()  # bytes32

    def anchor(
        self,
        wallet: str,
        action: ActionType,
        summary: str,
        payload: dict | None = None,
    ) -> int | None:
        """Anchor a MIRA action on-chain. Returns entry ID or None if disabled."""
        if not self._enabled:
            return None
        try:
            data_hash = self._data_hash(payload or {"summary": summary, "ts": int(time.time())})
            tx = self.contract.functions.anchor(
                Web3.to_checksum_address(wallet),
                int(action),
                data_hash,
                summary,
            ).build_transaction({
                "from":  self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "gas":   200_000,
                "gasPrice": self.w3.eth.gas_price,
            })
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            # Parse entry ID from logs
            entry_id = int(receipt["logs"][0]["topics"][1].hex(), 16) if receipt["logs"] else None
            return entry_id
        except Exception as e:
            print(f"[MIRA anchor] failed: {e}")
            return None

    def confirm(self, entry_id: int, tx_hash_hex: str) -> None:
        """Mark an anchored entry as confirmed with its resulting tx hash."""
        if not self._enabled or not entry_id:
            return
        try:
            tx_hash_bytes = bytes.fromhex(tx_hash_hex.removeprefix("0x")).ljust(32, b"\x00")
            tx = self.contract.functions.confirm(
                entry_id, tx_hash_bytes
            ).build_transaction({
                "from":  self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "gas":   100_000,
                "gasPrice": self.w3.eth.gas_price,
            })
            signed = self.account.sign_transaction(tx)
            self.w3.eth.send_raw_transaction(signed.raw_transaction)
        except Exception as e:
            print(f"[MIRA confirm] failed: {e}")

    def get_recent(self, wallet: str, n: int = 10) -> list[dict]:
        """Read recent audit entries for a wallet (no gas needed)."""
        if not self.contract:
            return []
        try:
            entries = self.contract.functions.getRecentEntries(
                Web3.to_checksum_address(wallet), n
            ).call()
            return [
                {
                    "id":        e[0],
                    "wallet":    e[1],
                    "action":    ActionType(e[2]).name,
                    "summary":   e[4],
                    "timestamp": e[5],
                    "confirmed": e[6],
                    "tx_hash":   "0x" + e[7].hex() if e[6] else None,
                }
                for e in entries
            ]
        except Exception:
            return []


# Singleton
mira_anchor = MiraAnchor()
# web3 anchor client
