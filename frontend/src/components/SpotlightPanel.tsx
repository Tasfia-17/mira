interface Props {
  token: any
  onClose: () => void
  onBuy: (symbol: string, address: string) => void
  onWatch: (symbol: string, address: string) => void
}

export function SpotlightPanel({ token, onClose, onBuy, onWatch }: Props) {
  if (!token) return null
  const t = token

  return (
    <div className="spotlight-overlay" onClick={onClose}>
      <div className="spotlight-card" onClick={e => e.stopPropagation()}>
        <div className="spot-header">
          <div>
            <div className="spot-symbol">{t.symbol}</div>
            <div className="spot-name">{t.name || t.token_id?.slice(0,12)}</div>
          </div>
          <button className="spot-close" onClick={onClose}>✕</button>
        </div>

        <div className="spot-price-row">
          <span className="spot-price">{t.price || t.price_raw}</span>
          <span className={`spot-change ${t.change_positive ? 'green' : 'red'}`}>{t.change_24h}</span>
        </div>

        <div className="spot-stats">
          {[
            ['Volume 24h', t.volume_24h],
            ['Market Cap', t.market_cap],
            ['Liquidity',  t.liquidity],
            ['Holders',    t.holders],
            ['Risk',       t.risk_level],
          ].filter(([,v]) => v).map(([label, val]) => (
            <div key={label as string} className="spot-stat">
              <span className="stat-label">{label}</span>
              <span className={`stat-val ${label==='Risk' && val!=='SAFE' ? 'red' : ''}`}>{val}</span>
            </div>
          ))}
        </div>

        {t.chart_points && <MiniChart points={t.chart_points} positive={t.change_positive} />}

        <div className="spot-actions">
          <button className="spot-watch-btn" onClick={() => onWatch(t.symbol, t.address || t.token_id)}>
            + Watchlist
          </button>
          <button className="spot-buy-btn" onClick={() => onBuy(t.symbol, t.address || t.token_id)}>
            Buy {t.symbol}
          </button>
        </div>
      </div>
    </div>
  )
}

function MiniChart({ points, positive }: { points: number[], positive: boolean }) {
  const min = Math.min(...points), max = Math.max(...points)
  const range = max - min || 1
  const w = 300, h = 60
  const pts = points.map((p, i) =>
    `${(i/(points.length-1))*w},${h-((p-min)/range)*h}`
  ).join(' ')
  return (
    <svg width={w} height={h} className="spot-chart">
      <polyline points={pts} fill="none" stroke={positive?'#00e676':'#ff5252'} strokeWidth="2"/>
    </svg>
  )
}
// spotlight panel
