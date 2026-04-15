import { useState, useEffect, useRef } from 'react'
import { MiraCharacter } from './components/MiraCharacter'
import { DeFiPanel } from './components/DeFiPanel'
import { VoiceBar } from './components/VoiceBar'
import { WalletConnect } from './components/WalletConnect'
import { SwapConfirm } from './components/SwapConfirm'
import { SpotlightPanel } from './components/SpotlightPanel'
import { AuditPanel } from './components/AuditPanel'
import { useMiraSocket } from './hooks/useMiraSocket'
import './App.css'

export default function App() {
  const [wallet, setWallet]           = useState<string | null>(null)
  const [voice, setVoice]             = useState<'cool'|'warm'|'sharp'>('cool')
  const [expression, setExpr]         = useState('calm')
  const [speaking, setSpeaking]       = useState(false)
  const [portfolio, setPortfolio]     = useState<any>(null)
  const [miraText, setMiraText]     = useState("Connect your wallet. I've been watching the chain.")
  const [pendingSwapTx, setPendingSwapTx] = useState<any>(null)
  const [spotlight, setSpotlight]     = useState<any>(null)
  const [watchlist, setWatchlist]     = useState<string[]>([])
  const [paperMode, setPaperMode]     = useState(false)
  const [paperBalance, setPaperBalance] = useState(10000)
  const [alerts, setAlerts]           = useState<string[]>([])
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const { send, lastMessage, connected } = useMiraSocket('ws://localhost:8000/ws')

  useEffect(() => {
    if (!lastMessage) return
    const m = lastMessage
    if (m.expression) setExpr(m.expression)
    if (m.text)       setMiraText(m.text)
    if (m.portfolio)  setPortfolio(m.portfolio)
    if (m.audio)      playAudio(m.audio)
    if (m.spotlight)  setSpotlight(m.spotlight)
    if (m.type === 'alert')    setAlerts(a => [m.text, ...a].slice(0, 4))
    if (m.type === 'swap_tx')  setPendingSwapTx(m.tx)
    if (m.type === 'watchlist_add') setWatchlist(w => [...new Set([...w, m.symbol])])
    if (m.paper_balance !== undefined) setPaperBalance(m.paper_balance)
  }, [lastMessage])

  const playAudio = (b64: string) => {
    audioRef.current?.pause()
    const audio = new Audio(`data:audio/mp3;base64,${b64}`)
    audioRef.current = audio
    setSpeaking(true)
    audio.onended = () => setSpeaking(false)
    audio.play().catch(() => setSpeaking(false))
  }

  const onWalletConnected = (addr: string) => {
    setWallet(addr)
    send({ type: 'wallet_connect', address: addr, voice })
  }

  const onInput = (text: string) => send({ type: 'message', text })

  const onVoiceChange = (v: 'cool'|'warm'|'sharp') => {
    setVoice(v)
    send({ type: 'set_voice', voice: v })
  }

  const onSpotlight = (token: any) => {
    setSpotlight(token)
    send({ type: 'message', text: `Tell me about ${token.symbol} — price, risk, and should I buy it?` })
  }

  const onBuy = (symbol: string, _address: string) => {
    setSpotlight(null)
    send({ type: 'message', text: `I want to buy ${symbol}. Show me a swap preview.` })
  }

  const onWatch = (symbol: string) => {
    setWatchlist(w => [...new Set([...w, symbol])])
    setSpotlight(null)
    send({ type: 'message', text: `Add ${symbol} to my watchlist.` })
  }

  const onTogglePaper = () => {
    const next = !paperMode
    setPaperMode(next)
    send({ type: 'set_paper_mode', enabled: next })
  }

  return (
    <div className="mira-app">
      <div className={`conn-dot ${connected ? 'online' : 'offline'}`} />

      <div className="character-panel">
        <MiraCharacter expression={expression} speaking={speaking} />
        <div className="mira-speech">{miraText}</div>
        {alerts.length > 0 && (
          <div className="alert-feed">
            {alerts.map((a, i) => <div key={i} className="alert-item">⚡ {a}</div>)}
          </div>
        )}
        <VoiceBar onInput={onInput} voice={voice} onVoiceChange={onVoiceChange} />
      </div>

      <div className="data-panel">
        {!wallet
          ? <WalletConnect onConnected={onWalletConnected} />
          : <>
              <DeFiPanel
                portfolio={portfolio} wallet={wallet} onQuery={onInput}
                onSpotlight={onSpotlight} watchlist={watchlist}
                paperMode={paperMode} onTogglePaper={onTogglePaper}
                paperBalance={paperBalance}
              />
              <AuditPanel wallet={wallet} />
            </>
        }
      </div>

      {spotlight && (
        <SpotlightPanel
          token={spotlight}
          onClose={() => setSpotlight(null)}
          onBuy={onBuy}
          onWatch={onWatch}
        />
      )}

      {pendingSwapTx && wallet && (
        <SwapConfirm
          tx={pendingSwapTx}
          onResult={(ok, hash) => { setPendingSwapTx(null); send({ type: 'swap_result', success: ok, tx_hash: hash }) }}
          onReject={() => { setPendingSwapTx(null); send({ type: 'swap_reject' }) }}
        />
      )}
    </div>
  )
}
