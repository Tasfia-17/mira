import { useState } from 'react'
import { ethers } from 'ethers'

interface Props { onConnected: (address: string) => void }

export function WalletConnect({ onConnected }: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const connect = async () => {
    setLoading(true)
    setError('')
    try {
      if (!(window as any).ethereum) throw new Error('MetaMask not found')
      const provider = new ethers.BrowserProvider((window as any).ethereum)
      // Switch to HashKey Chain (chainId 177)
      try {
        await (window as any).ethereum.request({
          method: 'wallet_switchEthereumChain',
          params: [{ chainId: '0xb1' }],
        })
      } catch {
        await (window as any).ethereum.request({
          method: 'wallet_addEthereumChain',
          params: [{
            chainId: '0xb1',
            chainName: 'HashKey Chain',
            rpcUrls: ['https://mainnet.hsk.xyz'],
            nativeCurrency: { name: 'HSK', symbol: 'HSK', decimals: 18 },
            blockExplorerUrls: ['https://hashkey.blockscout.com'],
          }],
        })
      }
      const signer = await provider.getSigner()
      const address = await signer.getAddress()
      onConnected(address)
    } catch (e: any) {
      setError(e.message)
    }
    setLoading(false)
  }

  return (
    <div className="wallet-connect">
      <div className="connect-hero">
        <h1 className="mira-title">MIRA</h1>
        <p className="mira-tagline">She's been watching the chain.</p>
        <button className="connect-btn" onClick={connect} disabled={loading}>
          {loading ? 'Connecting...' : 'Connect Wallet'}
        </button>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
// wallet connect
