import { useState } from 'react'

interface Props {
  portfolio: any
  wallet: string
  onQuery: (q: string) => void
  onSpotlight: (token: any) => void
  watchlist: string[]
  paperMode: boolean
  onTogglePaper: () => void
  paperBalance: number
}

export function DeFiPanel({ portfolio, wallet, onQuery, onSpotlight, watchlist, paperMode, onTogglePaper, paperBalance }: Props) {
  const [tab, setTab] = useState<'portfolio' | 'watchlist'>('portfolio')
  const tokens = portfolio?.tokens || []
  const totalUsd = portfolio?.total_usd_value || 0

  const quickActions = [
    { label: 'Analyze portfolio', q: 'Analyze my portfolio and tell me what I should do right now.' },
    { label: 'Any risks?',        q: 'Are there any risks in my current positions?' },
    { label: 'Best yield?',       q: 'Where can I earn the best yield on HashKey Chain right now?' },
    { label: 'Recent activity',   q: 'Summarize my recent wallet activity.' },
  ]

  return (
    <div className="defi-panel">
      <div className="wallet-header">
        <div>
          <div className="wallet-addr">{wallet.slice(0,6)}...{wallet.slice(-4)}</div>
          {paperMode && <div className="paper-badge">PAPER MODE</div>}
        </div>
        <div className="header-right">
          <span className="total-value">
            ${paperMode ? paperBalance.toLocaleString(undefined,{maximumFractionDigits:2}) : Number(totalUsd).toLocaleString(undefined,{maximumFractionDigits:2})}
          </span>
          <button className={`paper-toggle ${paperMode ? 'active' : ''}`} onClick={onTogglePaper}>
            {paperMode ? '📄 Paper' : '💰 Live'}
          </button>
        </div>
      </div>

      <div className="panel-tabs">
        {(['portfolio','watchlist'] as const).map(t => (
          <button key={t} className={`tab ${tab===t?'active':''}`} onClick={() => setTab(t)}>
            {t.charAt(0).toUpperCase()+t.slice(1)}
            {t==='watchlist' && watchlist.length > 0 && <span className="tab-badge">{watchlist.length}</span>}
          </button>
        ))}
      </div>

      <div className="token-list">
        {tab === 'portfolio' && (
          tokens.length === 0
            ? <div className="loading-row">Loading portfolio...</div>
            : tokens.map((t: any, i: number) => (
              <div key={i} className="token-row" onClick={() => onSpotlight(t)}>
                <span className="token-symbol">{t.symbol}</span>
                <span className="token-balance">{t.balance_fmt}</span>
                <span className="token-usd">{t.usd_value_fmt}</span>
                <span className={`token-change ${t.change_positive?'green':'red'}`}>{t.change_24h||'—'}</span>
              </div>
            ))
        )}
        {tab === 'watchlist' && (
          watchlist.length === 0
            ? <div className="loading-row">No tokens watched. Ask MIRA to watch a token.</div>
            : watchlist.map((sym, i) => (
              <div key={i} className="token-row" onClick={() => onQuery(`Show me details for ${sym}`)}>
                <span className="token-symbol">{sym}</span>
                <span className="token-balance">—</span>
                <span className="token-usd">—</span>
                <span className="token-change">tap to load</span>
              </div>
            ))
        )}
      </div>

      <div className="quick-actions">
        {quickActions.map((a,i) => (
          <button key={i} className="quick-btn" onClick={() => onQuery(a.q)}>{a.label}</button>
        ))}
      </div>
    </div>
  )
}
// defi panel
