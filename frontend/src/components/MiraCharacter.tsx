import { useState, useEffect } from 'react'

interface Props {
  expression: string
  speaking: boolean
}

// Expression → CSS class + glow color
const EXPR_CONFIG: Record<string, { glow: string; label: string }> = {
  calm:      { glow: 'rgba(0,200,255,0.15)',   label: '' },
  focused:   { glow: 'rgba(100,150,255,0.2)',  label: '◉ ANALYZING' },
  stern:     { glow: 'rgba(255,80,80,0.2)',    label: '⚠ WARNING' },
  smirk:     { glow: 'rgba(0,255,150,0.2)',    label: '↑ PROFIT' },
  surprised: { glow: 'rgba(255,200,0,0.2)',    label: '! ALERT' },
}

export function MiraCharacter({ expression, speaking }: Props) {
  const cfg = EXPR_CONFIG[expression] || EXPR_CONFIG.calm
  const [dots, setDots] = useState('')

  // Animate speaking dots
  useEffect(() => {
    if (!speaking) { setDots(''); return }
    const id = setInterval(() => setDots(d => d.length >= 3 ? '' : d + '.'), 400)
    return () => clearInterval(id)
  }, [speaking])

  return (
    <div className={`mira-character expression-${expression}`}>
      {/* Ambient glow */}
      <div className="char-glow" style={{ background: `radial-gradient(circle, ${cfg.glow} 0%, transparent 70%)` }} />

      {/* Character image — replace with actual art */}
      <div className="char-frame">
        <img src="/mira-avatar.png" alt="MIRA" className="char-img"
          onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
        {/* Fallback silhouette when no image */}
        <div className="char-silhouette">
          <div className="sil-head" />
          <div className="sil-body" />
          <div className="sil-scan" style={{ animationPlayState: speaking ? 'running' : 'paused' }} />
        </div>
      </div>

      {/* Expression badge */}
      {cfg.label && <div className="expr-badge">{cfg.label}</div>}

      {/* Speaking indicator */}
      {speaking && <div className="speaking-dots">MIRA{dots}</div>}

      {/* Waveform bars when speaking */}
      <div className={`waveform ${speaking ? 'active' : ''}`}>
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="wave-bar" style={{ animationDelay: `${i * 0.08}s` }} />
        ))}
      </div>
    </div>
  )
}
