# MIRA — 3-Minute Demo Script

## Setup (before judges arrive)
- Backend running: `python mira_server.py`
- Frontend open: `http://localhost:5173`
- MetaMask on HashKey Chain (chainId 177)
- Wallet with some HSK + USDC loaded

---

## The Pitch (30 seconds)

> "Every DeFi dashboard shows you numbers. MIRA talks to you about them.
> She knows your wallet, watches the chain 24/7, and executes trades through conversation.
> Built on HashKey Chain with AWS Bedrock and Polly. Let me show you."

---

## Demo (2 minutes)

**Step 1 — Connect** (15s)
- Click "Connect Wallet"
- MIRA speaks: *"Welcome back. You have $X across Y tokens..."*
- Point out: she loaded the full portfolio from BlockScout automatically

**Step 2 — Ask about risk** (20s)
- Type or say: *"Any risks in my portfolio?"*
- MIRA analyzes via Claude + HyperIndex data, responds with voice
- Expression shifts to "stern" if risk detected

**Step 3 — Token spotlight** (20s)
- Click any token in the portfolio
- Spotlight panel opens: price, chart, liquidity, holders
- Say: *"Should I hold or sell HSK?"*
- MIRA gives a data-grounded recommendation

**Step 4 — Swap** (30s)
- Say: *"Swap 10 USDC for HSK"*
- MIRA shows swap preview (quote from HyperIndex V3)
- Confirm overlay appears with price impact
- Click Confirm → MetaMask signs → on-chain settlement
- MIRA: *"Swap confirmed. Transaction: 0x..."* — expression: smirk

**Step 5 — Proactive alert** (15s, if live)
- Show the alert feed: *"HSK just moved up 6.2% in the last minute"*
- Explain: she monitors every 60 seconds, pushes alerts without being asked

**Step 6 — HSP payment** (20s)
- Say: *"Create a payment link for 50 USDC"*
- MIRA generates an HSP checkout URL
- Point out: stablecoin PayFi rails, bonus points track

---

## Close (30 seconds)

> "MIRA is the first DeFi product on HashKey Chain with a soul.
> She's not a dashboard with a chatbot bolted on — she IS the interface.
> Voice-first, wallet-aware, proactive. Built on AWS Bedrock + Polly + HashKey Chain.
> The code is live, the swaps are real, and she's been watching your wallet."

---

## Backup (if something breaks)
- Switch to Paper Mode (📄 button) — full demo without real funds
- All mock scenes work offline via the WebSocket fallback
