import { useState } from 'react'
import { ethers } from 'ethers'

interface Props {
  tx: any
  onResult: (success: boolean, txHash: string) => void
  onReject: () => void
}

export function SwapConfirm({ tx, onResult, onReject }: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const quote = tx.quote || {}
  const params = tx.params || {}

  const execute = async () => {
    setLoading(true)
    setError('')
    try {
      const provider = new ethers.BrowserProvider((window as any).ethereum)
      const signer = await provider.getSigner()
      const iface = new ethers.Interface(tx.router_abi)
      const data = iface.encodeFunctionData(tx.method, [params])

      const txResp = await signer.sendTransaction({
        to: tx.to,
        value: tx.value,
        data,
        gasLimit: 300000n,
      })
      const receipt = await txResp.wait()
      onResult(receipt?.status === 1, txResp.hash)
    } catch (e: any) {
      setError(e.message?.slice(0, 80))
    }
    setLoading(false)
  }

  return (
    <div className="swap-confirm-overlay">
      <div className="swap-confirm-card">
        <div className="swap-confirm-title">Confirm Swap</div>

        <div className="swap-row">
          <span className="swap-label">You pay</span>
          <span className="swap-value">{quote.amount_in_fmt || '—'}</span>
        </div>
        <div className="swap-row">
          <span className="swap-label">You receive</span>
          <span className="swap-value green">{quote.amount_out_fmt || '—'}</span>
        </div>
        <div className="swap-row">
          <span className="swap-label">Price impact</span>
          <span className={`swap-value ${parseFloat(quote.price_impact_pct || 0) > 2 ? 'red' : ''}`}>
            {quote.price_impact_pct ? `${quote.price_impact_pct}%` : '—'}
          </span>
        </div>
        <div className="swap-row">
          <span className="swap-label">Slippage</span>
          <span className="swap-value">1%</span>
        </div>

        {error && <div className="swap-error">{error}</div>}

        <div className="swap-actions">
          <button className="swap-reject-btn" onClick={onReject} disabled={loading}>Cancel</button>
          <button className="swap-confirm-btn" onClick={execute} disabled={loading}>
            {loading ? 'Signing...' : 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  )
}
// swap confirm
