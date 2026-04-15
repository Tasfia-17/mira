"""
MIRA Backend Server — Full version
Voice + DeFi intelligence companion on HashKey Chain
AWS Bedrock (Claude) + AWS Polly + HashKey Chain + Proactive Alerts + Swap Execution
"""
import asyncio
import json
import os
import base64
import boto3
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

load_dotenv()

from hashkey_provider import get_wallet_portfolio
from hashkey_ave_adapter import build_portfolio_payload, build_spotlight_payload, build_feed_payload
from mira_tools import MIRA_TOOLS, dispatch_tool
from mira_swap import build_swap_tx
from mira_alerts import alert_engine

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
polly   = boto3.client("polly",           region_name=os.getenv("AWS_REGION", "us-east-1"))

VOICE_OPTIONS = {
    "cool":  {"VoiceId": "Joanna", "Engine": "neural"},
    "warm":  {"VoiceId": "Salli",  "Engine": "neural"},
    "sharp": {"VoiceId": "Ivy",    "Engine": "neural"},
}

MIRA_SYSTEM_PROMPT = """You are MIRA, an on-chain DeFi intelligence companion on HashKey Chain.
You see everything in the user's wallet. You speak like a trusted advisor — direct, warm, never robotic.
You proactively surface what matters. You never hide risk.

Rules:
- Keep responses concise and spoken-friendly (no markdown, no bullet lists in speech)
- Always ground answers in real on-chain data from tools
- When you detect risk, shift to a stern tone
- When the user profits, acknowledge it warmly
- For swap requests: use swap_preview first, then ask for confirmation before building the tx
- You have tools: get_portfolio, get_spotlight, search_token, get_activity, swap_preview, execute_swap

Chain: HashKey Chain (HSK). Native token: HSK. DEX: HyperIndex V3.
"""


def synth(text: str, voice_key: str = "cool") -> str:
    v = VOICE_OPTIONS.get(voice_key, VOICE_OPTIONS["cool"])
    r = polly.synthesize_speech(Text=text, OutputFormat="mp3", VoiceId=v["VoiceId"], Engine=v["Engine"])
    return base64.b64encode(r["AudioStream"].read()).decode()


def expression_for(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["risk", "warning", "careful", "danger", "liquidat", "scam", "rug"]):
        return "stern"
    if any(w in t for w in ["profit", "gain", "up", "nice", "great", "well done", "congrat"]):
        return "smirk"
    if any(w in t for w in ["found", "opportunity", "suggest", "recommend", "detected"]):
        return "focused"
    return "calm"


async def bedrock_loop(messages: list) -> str:
    """Run agentic tool-use loop, return final text."""
    loop_msgs = list(messages)
    while True:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": MIRA_SYSTEM_PROMPT,
            "messages": loop_msgs,
            "tools": MIRA_TOOLS,
        }
        resp = bedrock.invoke_model(
            modelId=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
            body=json.dumps(body),
            contentType="application/json",
        )
        result = json.loads(resp["body"].read())

        if result.get("stop_reason") == "tool_use":
            tool_results = []
            for block in result["content"]:
                if block["type"] == "tool_use":
                    out = await dispatch_tool(block["name"], block["input"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(out, default=str),
                    })
            loop_msgs.append({"role": "assistant", "content": result["content"]})
            loop_msgs.append({"role": "user",      "content": tool_results})
        else:
            for block in result["content"]:
                if block.get("type") == "text":
                    return block["text"]
            return ""


@app.on_event("startup")
async def startup():
    await alert_engine.start()


@app.get("/api/audit/{wallet}")
async def get_audit(wallet: str):
    from mira_anchor import mira_anchor
    entries = mira_anchor.get_recent(wallet, n=20)
    return {"entries": entries}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    session = {"wallet": None, "voice": "cool", "history": [], "pending_swap": None, "paper_mode": False}

    async def push(data: dict):
        try:
            await ws.send_json(data)
        except Exception:
            pass

    # Register for proactive alerts
    alert_engine.register("__pending__", push)

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            t = msg.get("type")

            # ── Wallet connect ──────────────────────────────────────────
            if t == "wallet_connect":
                wallet = msg["address"]
                session["wallet"] = wallet
                session["voice"]  = msg.get("voice", "cool")

                alert_engine.unregister("__pending__")
                alert_engine.register(wallet, push, session["voice"])

                portfolio = get_wallet_portfolio(wallet)
                payload   = build_portfolio_payload(portfolio)

                greeting_prompt = (
                    f"User connected wallet {wallet[:8]}... "
                    f"Portfolio: {json.dumps(payload, default=str)[:600]}. "
                    "Greet them in 2-3 spoken sentences. Tell them what you see."
                )
                session["history"] = [{"role": "user", "content": greeting_prompt}]
                text = await bedrock_loop(session["history"])
                session["history"].append({"role": "assistant", "content": text})

                await push({
                    "type": "greeting",
                    "text": text,
                    "audio": synth(text, session["voice"]),
                    "expression": "calm",
                    "portfolio": payload,
                })

            # ── Chat / voice message ────────────────────────────────────
            elif t == "message":
                user_text = msg["text"]
                session["history"].append({"role": "user", "content": user_text})
                text = await bedrock_loop(session["history"])
                session["history"].append({"role": "assistant", "content": text})

                await push({
                    "type": "response",
                    "text": text,
                    "audio": synth(text, session["voice"]),
                    "expression": expression_for(text),
                })

            # ── Swap confirm (user approved the preview) ────────────────
            elif t == "swap_confirm":
                swap = session.get("pending_swap")
                if not swap:
                    await push({"type": "error", "text": "No pending swap."})
                    continue
                # Build unsigned tx for frontend to sign
                tx = build_swap_tx(
                    token_in=swap["token_in"],
                    token_out=swap["token_out"],
                    amount_in_wei=swap["amount_in_wei"],
                    recipient=session["wallet"],
                    slippage_bps=swap.get("slippage_bps", 100),
                )
                session["pending_swap"] = None
                await push({"type": "swap_tx", "tx": tx})

            # ── Swap rejected ───────────────────────────────────────────
            elif t == "swap_reject":
                session["pending_swap"] = None
                text = "Swap cancelled. Let me know if you want to try something else."
                await push({
                    "type": "response",
                    "text": text,
                    "audio": synth(text, session["voice"]),
                    "expression": "calm",
                })

            # ── Swap result (frontend reports tx hash) ──────────────────
            elif t == "swap_result":
                tx_hash = msg.get("tx_hash", "")
                success = msg.get("success", False)
                text = (
                    f"Swap confirmed on-chain. Transaction: {tx_hash[:10]}..."
                    if success else
                    "Swap failed. Want me to try again with higher slippage?"
                )
                await push({
                    "type": "response",
                    "text": text,
                    "audio": synth(text, session["voice"]),
                    "expression": "smirk" if success else "stern",
                })

            # ── Paper mode toggle ───────────────────────────────────────
            elif t == "set_paper_mode":
                session["paper_mode"] = msg.get("enabled", False)
                mode = "paper trading" if session["paper_mode"] else "live trading"
                text = f"Switched to {mode} mode."
                await push({
                    "type": "response", "text": text,
                    "audio": synth(text, session["voice"]),
                    "expression": "focused",
                    "paper_balance": 10000 if session["paper_mode"] else None,
                })

            # ── Voice selection ─────────────────────────────────────────
            elif t == "set_voice":
                session["voice"] = msg.get("voice", "cool")
                await push({"type": "voice_set", "voice": session["voice"]})

    except WebSocketDisconnect:
        if session["wallet"]:
            alert_engine.unregister(session["wallet"])


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
