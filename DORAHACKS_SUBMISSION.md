# MIRA — DoraHacks Submission

## Track
DeFi — 10K Prize Pool

## Tagline
She sees everything on-chain.

## One-liner
MIRA is a Telegram-native DeFi agent for HashKey Chain — she lives in your phone, watches your wallet 24/7, and executes trades through natural conversation.

## Problem
Every DeFi product makes you go TO it. You open an app, connect a wallet, navigate a dashboard. Most people never bother. The result: 420 million crypto holders who can't actually use DeFi.

## Solution
MIRA flips the model. She comes to you — in Telegram, the app already on your phone.

You message her like a person. She responds with real on-chain data, executes swaps, and alerts you proactively when something matters. No app install. No wallet connect flow. No dashboard.

## How It Works
1. Message @mira_hsk_bot on Telegram
2. Send your wallet address — she loads your full HashKey Chain portfolio instantly
3. Talk to her naturally: "swap 50 USDC for HSK", "any risks?", "best yield right now?"
4. She quotes, confirms, and executes — all in the chat
5. She monitors your wallet in the background and messages you when prices move

## What MIRA Can Do
- Full portfolio intelligence (BlockScout v2 — balances, PnL, history)
- Token search and spotlight (price, liquidity, holders, risk)
- Swap execution via HyperIndex V3 (quote → confirm button → on-chain)
- Proactive price alerts (>5% moves trigger automatic messages)
- Voice message support (AWS Transcribe → full DeFi response)
- HSP stablecoin payment links (USDC/USDT via HashKey Settlement Protocol)
- Paper trading mode for safe demos

## Technical Architecture
- **Interface:** Telegram Bot (python-telegram-bot)
- **AI Brain:** AWS Bedrock — Claude 3.5 Sonnet with 7 DeFi tools via tool use
- **Voice:** AWS Transcribe for speech-to-text
- **Chain Data:** HashKey Chain RPC + BlockScout v2 + HyperIndex V3
- **Payments:** HSP (HashKey Settlement Protocol) — USDC/USDT stablecoin rails
- **Web UI:** React + TypeScript + ethers.js (optional companion interface)

## HashKey Chain Integration
- Native HSK token + WHSK pool routing on HyperIndex V3
- BlockScout v2 for wallet intelligence and token search
- HSP for USDC/USDT stablecoin payments (extra points track)
- Paper trading mode using same confirm flow as live mode
- Proactive monitoring of HashKey Chain every 60 seconds

## AWS Integration
- Bedrock (Claude 3.5 Sonnet): all AI reasoning and tool orchestration
- Transcribe: voice message speech-to-text
- Polly: optional TTS for voice responses
- S3: temporary voice file storage for transcription

## Why This Is Different
99 other submissions built dashboards and protocols. MIRA built a character who lives in your phone.

She's not a chatbot wrapper. She has a personality, a name, a face (shown on /start), and she speaks directly. You don't "use" MIRA — you talk to her. And she actually does things: real swaps, real data, real alerts.

The OpenClaw model (messaging-native AI agents) applied to DeFi on HashKey Chain — nobody else in this hackathon built this.

## GitHub
https://github.com/[your-handle]/mira-hashkey

## Demo Video
[link]
