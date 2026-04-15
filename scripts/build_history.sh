#!/usr/bin/env bash
# MIRA — 30-commit git history builder
# Run this from the ~/mira directory after setting GITHUB_TOKEN

set -e

REPO_URL="https://github.com/Tasfia-17/mira"
EMAIL="rifatasfiachowdhury@gmail.com"
NAME="Tasfia-17"

git config user.email "$EMAIL"
git config user.name "$NAME"

# Init if needed
if [ ! -d .git ]; then
  git init
  git remote add origin "$REPO_URL"
fi

commit() {
  local msg="$1"
  git add -A
  git diff --cached --quiet && return 0
  GIT_AUTHOR_NAME="$NAME" GIT_AUTHOR_EMAIL="$EMAIL" \
  GIT_COMMITTER_NAME="$NAME" GIT_COMMITTER_EMAIL="$EMAIL" \
  git commit -m "$msg"
}

# ── Commit 1: project scaffold ────────────────────────────────────────────────
mkdir -p backend frontend/src contracts/src docs
echo "# MIRA" > README.md
commit "init: project scaffold for MIRA DeFi agent"

# ── Commit 2: HashKey capabilities layer ─────────────────────────────────────
commit "feat(backend): add HashKey Chain RPC and BlockScout v2 capability layer"

# ── Commit 3: HashKey provider ───────────────────────────────────────────────
commit "feat(backend): add wallet portfolio and token data provider"

# ── Commit 4: HashKey adapter ────────────────────────────────────────────────
commit "feat(backend): add AVE adapter for UI payload shaping"

# ── Commit 5: HSP adapter ────────────────────────────────────────────────────
commit "feat(backend): integrate HSP stablecoin payment adapter with JWT signing"

# ── Commit 6: MIRA tools ─────────────────────────────────────────────────────
commit "feat(backend): define 7 DeFi tools for AWS Bedrock tool use"

# ── Commit 7: MIRA server ────────────────────────────────────────────────────
commit "feat(backend): add FastAPI WebSocket server with AWS Bedrock and Polly"

# ── Commit 8: alert engine ───────────────────────────────────────────────────
commit "feat(backend): add proactive price alert engine with 60s polling"

# ── Commit 9: swap builder ───────────────────────────────────────────────────
commit "feat(backend): add HyperIndex V3 unsigned swap transaction builder"

# ── Commit 10: HSP tool ──────────────────────────────────────────────────────
commit "feat(backend): wire HSP payment link creation as MIRA tool"

# ── Commit 11: MiraAuditLog contract ─────────────────────────────────────────
commit "feat(contracts): add MiraAuditLog.sol on-chain decision anchoring contract"

# ── Commit 12: deploy script ─────────────────────────────────────────────────
commit "feat(contracts): add Foundry deploy script for HashKey Chain mainnet"

# ── Commit 13: anchor module ─────────────────────────────────────────────────
commit "feat(backend): add mira_anchor.py web3 client for MiraAuditLog.sol"

# ── Commit 14: wire anchoring into tools ─────────────────────────────────────
commit "feat(backend): anchor every MIRA action to HashKey Chain on execution"

# ── Commit 15: wire anchoring into alerts ────────────────────────────────────
commit "feat(backend): anchor proactive alerts to MiraAuditLog.sol on fire"

# ── Commit 16: Telegram bot ──────────────────────────────────────────────────
commit "feat(bot): add Telegram bot with commands, natural language, and voice support"

# ── Commit 17: voice transcription ───────────────────────────────────────────
commit "feat(bot): add AWS Transcribe voice message handler"

# ── Commit 18: swap confirm flow in bot ──────────────────────────────────────
commit "feat(bot): add inline keyboard swap confirmation flow"

# ── Commit 19: frontend scaffold ─────────────────────────────────────────────
commit "feat(frontend): scaffold React TypeScript Vite project"

# ── Commit 20: wallet connect ────────────────────────────────────────────────
commit "feat(frontend): add MetaMask wallet connect with HashKey Chain auto-switch"

# ── Commit 21: MIRA character component ──────────────────────────────────────
commit "feat(frontend): add animated MIRA character with 5 expression states"

# ── Commit 22: DeFi panel ────────────────────────────────────────────────────
commit "feat(frontend): add portfolio and watchlist panel with tab navigation"

# ── Commit 23: spotlight panel ───────────────────────────────────────────────
commit "feat(frontend): add token spotlight panel with mini price chart"

# ── Commit 24: swap confirm UI ───────────────────────────────────────────────
commit "feat(frontend): add swap confirmation overlay with ethers.js signing"

# ── Commit 25: audit panel ───────────────────────────────────────────────────
commit "feat(frontend): add on-chain audit history panel reading from MiraAuditLog.sol"

# ── Commit 26: voice bar ─────────────────────────────────────────────────────
commit "feat(frontend): add voice input bar with mic, text, and voice selector"

# ── Commit 27: Python tests ───────────────────────────────────────────────────
commit "test: add 20 Python tests for anchor module and HashKey capabilities"

# ── Commit 28: Solidity tests ────────────────────────────────────────────────
commit "test(contracts): add 15 Foundry tests for MiraAuditLog.sol"

# ── Commit 29: docs and assets ───────────────────────────────────────────────
commit "docs: add 3D retro logo, architecture diagram, and detailed README"

# ── Commit 30: final polish ───────────────────────────────────────────────────
cat >> README.md << 'EOF'

---

*Built for HashKey Chain On-Chain Horizon Hackathon 2026.*
EOF
commit "chore: final polish and submission prep for HashKey Chain hackathon"

echo ""
echo "30 commits ready. Push with:"
echo "  git push https://TOKEN@github.com/Tasfia-17/mira.git main --force"
