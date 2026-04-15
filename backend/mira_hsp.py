"""
MIRA HSP Tool — lets users pay for DeFi actions via HashKey Settlement Protocol
Wraps OutcomeX's hsp_adapter for use as a MIRA tool
"""
from __future__ import annotations
import os
from hsp_adapter import HspAdapter, HspConfig

def get_hsp_adapter() -> HspAdapter | None:
    """Return configured HSP adapter if credentials are set."""
    merchant_id  = os.getenv("HSP_MERCHANT_ID")
    private_key  = os.getenv("HSP_PRIVATE_KEY")
    if not merchant_id or not private_key:
        return None
    cfg = HspConfig(
        merchant_id=merchant_id,
        private_key_pem=private_key,
        base_url=os.getenv("HSP_BASE_URL", "https://open-api.hashkey.com"),
        supported_currencies=("USDC", "USDT"),
    )
    return HspAdapter(cfg)


async def create_payment_link(amount_usd: float, description: str, order_id: str) -> dict:
    """Create an HSP checkout link for a given USD amount."""
    adapter = get_hsp_adapter()
    if not adapter:
        return {"error": "HSP not configured. Set HSP_MERCHANT_ID and HSP_PRIVATE_KEY."}
    try:
        amount_cents = int(amount_usd * 100)
        cart = adapter.create_cart(
            order_id=order_id,
            amount_cents=amount_cents,
            description=description,
        )
        return {
            "checkout_url": cart.checkout_url,
            "cart_id": cart.cart_id,
            "amount_usd": amount_usd,
            "expires_at": str(cart.expires_at),
        }
    except Exception as e:
        return {"error": str(e)}
