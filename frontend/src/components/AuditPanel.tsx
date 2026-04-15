import { useState, useEffect } from 'react'

interface AuditEntry {
  id: number
  action: string
  summary: string
  timestamp: number
  confirmed: boolean
  tx_hash: string | null
}

interface Props {
  wallet: string
}

const ACTION_ICONS: Record<string, string> = {
  SWAP_EXECUTED:      '🔄',
  SWAP_QUOTED:        '💬',
  ALERT_FIRED:        '⚡',
  PORTFOLIO_ANALYZED: '📊',
  RISK_FLAGGED:       '⚠️',
  YIELD_RECOMMENDED:  '💰',
  PAYMENT_CREATED:    '💳',
  STRATEGY_TRIGGERED: '🤖',
}

export function AuditPanel({ wallet }: Props) {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/audit/${wallet}`)
      const data = await res.json()
      setEntries(data.entries || [])
    } catch {
      // backend not connected — show empty state
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [wallet])

  const fmt = (ts: number) => new Date(ts * 1000).toLocaleString()

  return (
    <div className="audit-panel">
      <div className="audit-header">
        <span className="audit-title">On-Chain Audit Trail</span>
        <span className="audit-badge">HashKey Chain</span>
        <button className="audit-refresh" onClick={load}>↻</button>
      </div>

      {loading && <div className="audit-loading">Loading from chain...</div>}

      {!loading && entries.length === 0 && (
        <div className="audit-empty">
          No actions anchored yet. Every MIRA decision will appear here.
        </div>
      )}

      <div className="audit-list">
        {entries.map(e => (
          <div key={e.id} className={`audit-entry ${e.confirmed ? 'confirmed' : ''}`}>
            <div className="audit-icon">{ACTION_ICONS[e.action] || '•'}</div>
            <div className="audit-body">
              <div className="audit-summary">{e.summary}</div>
              <div className="audit-meta">
                <span className="audit-time">{fmt(e.timestamp)}</span>
                {e.confirmed && e.tx_hash && (
                  <a
                    className="audit-tx"
                    href={`https://hashkey.blockscout.com/tx/${e.tx_hash}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {e.tx_hash.slice(0, 10)}... ↗
                  </a>
                )}
              </div>
            </div>
            <div className={`audit-status ${e.confirmed ? 'on-chain' : 'pending'}`}>
              {e.confirmed ? '✓ on-chain' : '○ anchored'}
            </div>
          </div>
        ))}
      </div>

      <div className="audit-footer">
        Every MIRA decision is cryptographically anchored to HashKey Chain.
        <a href={`https://hashkey.blockscout.com/address/${wallet}`} target="_blank" rel="noreferrer">
          View on BlockScout ↗
        </a>
      </div>
    </div>
  )
}
// audit panel
