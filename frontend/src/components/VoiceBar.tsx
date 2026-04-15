import { useState, useRef } from 'react'

interface Props {
  onInput: (text: string) => void
  voice: 'cool' | 'warm' | 'sharp'
  onVoiceChange: (v: 'cool' | 'warm' | 'sharp') => void
}

export function VoiceBar({ onInput, voice, onVoiceChange }: Props) {
  const [listening, setListening] = useState(false)
  const [text, setText] = useState('')
  const recognitionRef = useRef<any>(null)

  const startListening = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) return
    const r = new SR()
    r.continuous = false
    r.interimResults = false
    r.onresult = (e: any) => {
      const t = e.results[0][0].transcript
      setText(t)
      onInput(t)
    }
    r.onend = () => setListening(false)
    recognitionRef.current = r
    r.start()
    setListening(true)
  }

  const submit = () => {
    if (text.trim()) { onInput(text); setText('') }
  }

  return (
    <div className="voice-bar">
      {/* Voice selector */}
      <div className="voice-selector">
        {(['cool', 'warm', 'sharp'] as const).map(v => (
          <button
            key={v}
            className={`voice-btn ${voice === v ? 'active' : ''}`}
            onClick={() => onVoiceChange(v)}
          >{v}</button>
        ))}
      </div>

      {/* Input row */}
      <div className="input-row">
        <button
          className={`mic-btn ${listening ? 'listening' : ''}`}
          onClick={startListening}
        >
          {listening ? '●' : '🎤'}
        </button>
        <input
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
          placeholder="Ask MIRA anything..."
          className="text-input"
        />
        <button className="send-btn" onClick={submit}>→</button>
      </div>
    </div>
  )
}
// voice bar
