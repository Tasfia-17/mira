import copy
import json
import tempfile
import threading
import time
from pathlib import Path


VALID_TRADE_MODES = {"real", "paper"}
_STORE_LOCK = threading.Lock()

_CHAIN_SEEDS = {
    "solana": {"symbol": "SOL", "amount": "1"},
    "eth": {"symbol": "ETH", "amount": "1"},
    "base": {"symbol": "ETH", "amount": "1"},
    "bsc": {"symbol": "BNB", "amount": "1"},
    "hashkey": {"symbol": "HSK", "amount": "10000"},
}


class PaperStoreError(RuntimeError):
    """Raised when the paper-trading store cannot be read or written."""


def _has_hashkey_activity(raw_account: dict | None) -> bool:
    if not isinstance(raw_account, dict):
        return False

    for row in raw_account.get("positions", {}).values() if isinstance(raw_account.get("positions"), dict) else []:
        if isinstance(row, dict) and str(row.get("chain") or "").strip().lower() == "hashkey":
            return True

    for key in ("open_orders", "fills"):
        rows = raw_account.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and str(row.get("chain") or "").strip().lower() == "hashkey":
                return True

    return False


def _default_account() -> dict:
    timestamp = int(time.time())
    return {
        "selected_mode": "paper",
        "seeded": True,
        "updated_at": timestamp,
        "balances": copy.deepcopy(_CHAIN_SEEDS),
        "positions": {},
        "open_orders": [],
        "fills": [],
        "realized_pnl_usd": "0",
    }


def _load_store(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperStoreError(f"failed to read paper store at {path}") from exc
    if not isinstance(data, dict):
        raise PaperStoreError(f"paper store should be a dict at {path}")
    normalized: dict[str, dict] = {}
    for namespace, account in data.items():
        if isinstance(namespace, str) and isinstance(account, dict):
            normalized[namespace] = account
    return normalized


def _save_store(path: Path, data: dict[str, dict]) -> None:
    tmp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            prefix=f"{path.name}.tmp.",
        ) as tmp:
            tmp_path = Path(tmp.name)
            json.dump(data, tmp, ensure_ascii=False, indent=2, sort_keys=True)
            tmp.flush()
        tmp_path.replace(path)
    except OSError as exc:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise PaperStoreError(f"failed to write paper store at {path}") from exc


def _normalize_mode(value) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in VALID_TRADE_MODES else "paper"


def _merge_account(raw_account: dict | None) -> dict:
    account = _default_account()
    if not isinstance(raw_account, dict):
        return account

    account["selected_mode"] = _normalize_mode(raw_account.get("selected_mode"))
    account["seeded"] = bool(raw_account.get("seeded", True))
    account["updated_at"] = int(raw_account.get("updated_at") or account["updated_at"])
    account["realized_pnl_usd"] = str(raw_account.get("realized_pnl_usd") or "0")

    raw_balances = raw_account.get("balances")
    if isinstance(raw_balances, dict):
        for chain, seed in _CHAIN_SEEDS.items():
            raw_entry = raw_balances.get(chain)
            if isinstance(raw_entry, dict):
                account["balances"][chain] = {
                    "symbol": str(raw_entry.get("symbol") or seed["symbol"]),
                    "amount": str(raw_entry.get("amount") or seed["amount"]),
                }

    # Upgrade old HashKey demo seed accounts from 1 HSK -> 10000 HSK when the
    # account has no HashKey-specific trading history yet.
    hashkey_balance = account["balances"].get("hashkey")
    if (
        isinstance(hashkey_balance, dict)
        and str(hashkey_balance.get("amount") or "").strip() == "1"
        and not _has_hashkey_activity(raw_account)
    ):
        hashkey_balance["amount"] = _CHAIN_SEEDS["hashkey"]["amount"]

    raw_positions = raw_account.get("positions")
    if isinstance(raw_positions, dict):
        account["positions"] = raw_positions

    raw_orders = raw_account.get("open_orders")
    if isinstance(raw_orders, list):
        account["open_orders"] = [row for row in raw_orders if isinstance(row, dict)]

    raw_fills = raw_account.get("fills")
    if isinstance(raw_fills, list):
        account["fills"] = [row for row in raw_fills if isinstance(row, dict)]

    return account


def get_paper_account(path: Path, namespace: str) -> dict:
    namespace = str(namespace or "default").strip() or "default"
    with _STORE_LOCK:
        store = _load_store(path)
        account = _merge_account(store.get(namespace))
        store[namespace] = account
        _save_store(path, store)
    return copy.deepcopy(account)


def get_trade_mode(path: Path, namespace: str) -> str:
    return get_paper_account(path, namespace).get("selected_mode", "paper")


def set_trade_mode(path: Path, namespace: str, mode: str) -> str:
    normalized_mode = _normalize_mode(mode)
    namespace = str(namespace or "default").strip() or "default"
    with _STORE_LOCK:
        store = _load_store(path)
        account = _merge_account(store.get(namespace))
        account["selected_mode"] = normalized_mode
        account["updated_at"] = int(time.time())
        store[namespace] = account
        _save_store(path, store)
    return normalized_mode


def list_open_orders(path: Path, namespace: str) -> list[dict]:
    account = get_paper_account(path, namespace)
    rows = account.get("open_orders", [])
    return rows if isinstance(rows, list) else []


def mutate_account(path: Path, namespace: str, mutator):
    namespace = str(namespace or "default").strip() or "default"
    with _STORE_LOCK:
        store = _load_store(path)
        account = _merge_account(store.get(namespace))
        result = mutator(account)
        account["updated_at"] = int(time.time())
        store[namespace] = account
        _save_store(path, store)
    return copy.deepcopy(account), result
