"""
MIRA Proactive Alert Engine
Monitors HashKey Chain in background and pushes alerts to connected sessions.
"""
from __future__ import annotations
import asyncio
import json
from typing import Callable
from hashkey_capabilities import (
    blockscout_get_token_price,
    hyperindex_quote_exact_input_single,
    HYPERINDEX_WHSK,
)
from hashkey_provider import get_wallet_portfolio

# Alert thresholds
PRICE_CHANGE_ALERT_PCT = 5.0   # alert if any held token moves >5% since last check
IDLE_CAPITAL_DAYS = 3          # alert if USDC idle for >3 days
CHECK_INTERVAL_SEC = 60        # check every 60 seconds


class AlertEngine:
    def __init__(self):
        self._sessions: dict[str, dict] = {}  # wallet -> {send_fn, last_prices, voice}
        self._running = False

    def register(self, wallet: str, send_fn: Callable, voice: str = "cool"):
        self._sessions[wallet] = {
            "send": send_fn,
            "voice": voice,
            "last_prices": {},
            "portfolio_snapshot": None,
        }

    def unregister(self, wallet: str):
        self._sessions.pop(wallet, None)

    async def start(self):
        self._running = True
        asyncio.create_task(self._loop())

    async def _loop(self):
        while self._running:
            await asyncio.sleep(CHECK_INTERVAL_SEC)
            for wallet, session in list(self._sessions.items()):
                try:
                    await self._check_wallet(wallet, session)
                except Exception:
                    pass

    async def _check_wallet(self, wallet: str, session: dict):
        portfolio = get_wallet_portfolio(wallet)
        tokens = portfolio.get("tokens", [])
        send = session["send"]

        for token in tokens:
            addr = token.get("address", "")
            symbol = token.get("symbol", "")
            current_price = float(token.get("price_usd") or 0)
            last_price = session["last_prices"].get(addr)

            if last_price and last_price > 0 and current_price > 0:
                change_pct = abs((current_price - last_price) / last_price * 100)
                if change_pct >= PRICE_CHANGE_ALERT_PCT:
                    direction = "up" if current_price > last_price else "down"
                    expression = "smirk" if direction == "up" else "stern"
                    summary = f"{symbol} moved {direction} {change_pct:.1f}%"
                    # Anchor alert on-chain
                    try:
                        from mira_anchor import mira_anchor, ActionType
                        mira_anchor.anchor(wallet, ActionType.ALERT_FIRED, summary,
                            {"symbol": symbol, "change_pct": change_pct, "direction": direction})
                    except Exception:
                        pass
                    await send({
                        "type": "alert",
                        "expression": expression,
                        "text": f"{symbol} just moved {direction} {change_pct:.1f}% in the last minute.",
                        "alert_type": "price_move",
                        "token": symbol,
                        "change_pct": change_pct,
                        "direction": direction,
                    })

            session["last_prices"][addr] = current_price


alert_engine = AlertEngine()
