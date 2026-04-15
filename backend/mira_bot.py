"""
MIRA — Telegram DeFi Agent for HashKey Chain
Your on-chain operator. She sees everything.

Commands:
  /start       — introduce MIRA, ask for wallet
  /wallet      — set/show wallet address
  /portfolio   — full portfolio summary
  /price <sym> — token price + 24h change
  /swap        — initiate a swap
  /yield       — best yield opportunities
  /alerts      — toggle price alerts
  /help        — command list
  
  Or just talk to her naturally.
"""
import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

import boto3
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

load_dotenv()

from mira_tools import MIRA_TOOLS, dispatch_tool
from mira_alerts import alert_engine
from hashkey_provider import get_wallet_portfolio
from hashkey_ave_adapter import build_portfolio_payload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AWS clients
bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
polly   = boto3.client("polly",           region_name=os.getenv("AWS_REGION", "us-east-1"))
transcribe_client = boto3.client("transcribe", region_name=os.getenv("AWS_REGION", "us-east-1"))

# User state: {telegram_user_id: {wallet, history, alerts_on}}
USER_STATE: dict[int, dict] = {}

MIRA_SYSTEM = """You are MIRA, a DeFi operator on HashKey Chain. You live in Telegram.
You are direct, sharp, and never waste words. You speak like the smartest trader the user knows.
You have real-time access to the user's wallet and HashKey Chain data via tools.

Rules:
- Keep replies short and spoken-friendly — this is a chat, not a report
- Use numbers and facts, not vague advice
- When risk is high, say so bluntly
- When the user profits, acknowledge it with personality
- Never say "I'm an AI" — you're MIRA
- For swaps: always show quote first, ask for confirmation
- Format portfolio as clean text, not markdown tables (Telegram renders poorly)
"""


def get_user(uid: int) -> dict:
    if uid not in USER_STATE:
        USER_STATE[uid] = {"wallet": None, "history": [], "alerts": False, "pending_swap": None}
    return USER_STATE[uid]


async def bedrock_reply(user_id: int, user_text: str) -> str:
    """Run MIRA's agentic loop and return final text response."""
    state = get_user(user_id)
    wallet = state.get("wallet")

    state["history"].append({"role": "user", "content": user_text})
    # Keep last 20 messages to avoid token overflow
    if len(state["history"]) > 20:
        state["history"] = state["history"][-20:]

    messages = list(state["history"])

    while True:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "system": MIRA_SYSTEM + (f"\nUser wallet: {wallet}" if wallet else "\nNo wallet connected yet."),
            "messages": messages,
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
                    out = await dispatch_tool(block["name"], block["input"], wallet=wallet)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(out, default=str),
                    })
            messages.append({"role": "assistant", "content": result["content"]})
            messages.append({"role": "user",      "content": tool_results})
        else:
            text = next((b["text"] for b in result["content"] if b.get("type") == "text"), "")
            state["history"].append({"role": "assistant", "content": text})
            return text


async def voice_to_text(file_path: str) -> str:
    """Transcribe voice message using AWS Transcribe (or fallback to local whisper)."""
    try:
        # Upload to S3 then transcribe — simplified: use presigned approach
        # For hackathon: use a quick local approach with boto3 streaming
        import subprocess
        result = subprocess.run(
            ["python3", "-c", f"""
import boto3, json, time, uuid, os
s3 = boto3.client('s3', region_name='{os.getenv("AWS_REGION","us-east-1")}')
bucket = os.getenv('AWS_S3_BUCKET', 'mira-voice-tmp')
key = f'voice/{{uuid.uuid4()}}.ogg'
try:
    s3.create_bucket(Bucket=bucket)
except: pass
s3.upload_file('{file_path}', bucket, key)
tc = boto3.client('transcribe', region_name='{os.getenv("AWS_REGION","us-east-1")}')
job = f'mira-{{uuid.uuid4().hex[:8]}}'
tc.start_transcription_job(TranscriptionJobName=job, Media={{'MediaFileUri': f's3://{{bucket}}/{{key}}'}}, MediaFormat='ogg', LanguageCode='en-US')
for _ in range(30):
    time.sleep(2)
    r = tc.get_transcription_job(TranscriptionJobName=job)
    status = r['TranscriptionJob']['TranscriptionJobStatus']
    if status == 'COMPLETED':
        import urllib.request
        url = r['TranscriptionJob']['Transcript']['TranscriptFileUri']
        with urllib.request.urlopen(url) as f:
            data = json.loads(f.read())
        print(data['results']['transcripts'][0]['transcript'])
        break
    elif status == 'FAILED':
        print('')
        break
"""],
            capture_output=True, text=True, timeout=90
        )
        return result.stdout.strip() or ""
    except Exception:
        return ""


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name or "there"
    await update.message.reply_photo(
        photo=open(Path(__file__).parent.parent / "frontend/public/mira-avatar.png", "rb"),
        caption=f"Hey {name}. I'm MIRA — your on-chain operator for HashKey Chain.\n\n"
                f"I watch your wallet 24/7, execute swaps, and tell you what's actually happening in the market.\n\n"
                f"Send me your wallet address to get started, or type /help."
    )


async def cmd_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = get_user(uid)
    args = ctx.args

    if not args:
        w = state.get("wallet")
        if w:
            await update.message.reply_text(f"Current wallet: `{w}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("No wallet set. Send: /wallet 0x...")
        return

    wallet = args[0].strip()
    if not wallet.startswith("0x") or len(wallet) != 42:
        await update.message.reply_text("That doesn't look like a valid address. Try again.")
        return

    state["wallet"] = wallet
    state["history"] = []  # reset context for new wallet

    await update.message.reply_text(f"Got it. Loading your portfolio...")

    reply = await bedrock_reply(uid, f"My wallet is {wallet}. Load my portfolio and greet me with what you see.")
    await update.message.reply_text(reply)

    # Register for proactive alerts
    async def push_alert(data: dict):
        try:
            await ctx.bot.send_message(chat_id=update.effective_chat.id, text=f"⚡ {data.get('text','')}")
        except Exception:
            pass
    alert_engine.register(wallet, push_alert)


async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = get_user(uid)
    if not state.get("wallet"):
        await update.message.reply_text("Set your wallet first: /wallet 0x...")
        return
    await update.message.reply_text("Checking your portfolio...")
    reply = await bedrock_reply(uid, "Show me my full portfolio with PnL.")
    await update.message.reply_text(reply)


async def cmd_yield(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text("Scanning HyperIndex pools...")
    reply = await bedrock_reply(uid, "What are the best yield opportunities on HashKey Chain right now?")
    await update.message.reply_text(reply)


async def cmd_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = get_user(uid)
    state["alerts"] = not state.get("alerts", False)
    status = "ON ✅" if state["alerts"] else "OFF ❌"
    await update.message.reply_text(f"Price alerts: {status}\nI'll message you when your holdings move >5%.")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*MIRA — HashKey Chain DeFi Agent*\n\n"
        "/wallet `0x...` — set your wallet\n"
        "/portfolio — your holdings + PnL\n"
        "/yield — best yield on HashKey Chain\n"
        "/alerts — toggle price alerts\n\n"
        "Or just talk to me:\n"
        "• _\"swap 10 USDC for HSK\"_\n"
        "• _\"what's HSK price?\"_\n"
        "• _\"any risks in my portfolio?\"_\n"
        "• Send a voice message 🎤",
        parse_mode="Markdown"
    )


# ── Message handlers ──────────────────────────────────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    # Detect wallet address pasted directly
    if text.startswith("0x") and len(text) == 42:
        ctx.args = [text]
        await cmd_wallet(update, ctx)
        return

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply = await bedrock_reply(uid, text)

    # Check if MIRA wants to confirm a swap
    if "confirm" in reply.lower() and ("swap" in reply.lower() or "buy" in reply.lower()):
        keyboard = [[
            InlineKeyboardButton("✅ Confirm", callback_data="swap_confirm"),
            InlineKeyboardButton("❌ Cancel",  callback_data="swap_cancel"),
        ]]
        await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(reply)


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Download voice file
    voice = update.message.voice
    file = await ctx.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        text = await voice_to_text(tmp.name)

    if not text:
        await update.message.reply_text("Couldn't catch that. Try typing it instead.")
        return

    await update.message.reply_text(f"_{text}_", parse_mode="Markdown")
    reply = await bedrock_reply(uid, text)
    await update.message.reply_text(reply)


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "swap_confirm":
        reply = await bedrock_reply(uid, "User confirmed the swap. Execute it now and report the result.")
        await query.edit_message_text(reply)
    elif query.data == "swap_cancel":
        await query.edit_message_text("Swap cancelled.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Set TELEGRAM_BOT_TOKEN in .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("wallet",    cmd_wallet))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("yield",     cmd_yield))
    app.add_handler(CommandHandler("alerts",    cmd_alerts))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("MIRA is online.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
