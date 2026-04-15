import { useEffect, useRef, useState, useCallback } from 'react'

export function useMiraSocket(url: string) {
  const ws = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<any>(null)

  useEffect(() => {
    const connect = () => {
      ws.current = new WebSocket(url)
      ws.current.onopen = () => setConnected(true)
      ws.current.onclose = () => { setConnected(false); setTimeout(connect, 2000) }
      ws.current.onmessage = (e) => setLastMessage(JSON.parse(e.data))
    }
    connect()
    return () => ws.current?.close()
  }, [url])

  const send = useCallback((data: object) => {
    if (ws.current?.readyState === WebSocket.OPEN)
      ws.current.send(JSON.stringify(data))
  }, [])

  return { send, lastMessage, connected }
}
