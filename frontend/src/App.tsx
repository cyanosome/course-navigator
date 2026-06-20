import { useState, useEffect } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from './assets/vite.svg'
import heroImg from './assets/hero.png'
import './App.css'

function App() {
  const [count, setCount] = useState(0)
  const [items, setItems] = useState<string[]>([])
  const [inputText, setInputText] = useState('')
  const [processedText, setProcessedText] = useState('')
  const [error, setError] = useState<string | null>(null)

  // GET data from backend
  useEffect(() => {
    fetch('/api/data')
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`)
        }
        return res.json()
      })
      .then((data) => {
        if (data.items) {
          setItems(data.items)
        }
      })
      .catch((err) => {
        console.error('Error fetching data:', err)
        setError('バックエンドからのデータ取得に失敗しました')
      })
  }, [])

  // POST data to backend
  const handlePost = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inputText.trim()) return

    try {
      const res = await fetch('/api/process', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ text: inputText }),
      })
      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`)
      }
      const data = await res.json()
      setProcessedText(data.processed)
    } catch (err) {
      console.error('Error processing data:', err)
      setProcessedText('バックエンドでの処理中にエラーが発生しました')
    }
  }

  return (
    <>
      <section id="center">
        <div className="hero">
          <img src={heroImg} className="base" width="170" height="179" alt="" />
          <img src={reactLogo} className="framework" alt="React logo" />
          <img src={viteLogo} className="vite" alt="Vite logo" />
        </div>
        <div>
          <h1>Get started</h1>
          <p>
            Edit <code>src/App.tsx</code> and save to test <code>HMR</code>
          </p>
        </div>
        <button
          type="button"
          className="counter"
          onClick={() => setCount((count) => count + 1)}
        >
          Count is {count}
        </button>
      </section>

      <div className="ticks"></div>

      <section id="api-test" style={{ padding: '2rem', maxWidth: '600px', margin: '0 auto', textAlign: 'left' }}>
        <h2>🔌 バックエンド疎通実験</h2>
        
        {/* GET 検証エリア */}
        <div style={{ marginBottom: '2rem', padding: '1rem', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', backgroundColor: 'rgba(255,255,255,0.02)' }}>
          <h3>1. GET 疎通テスト (/api/data)</h3>
          {error ? (
            <p style={{ color: '#ff6b6b' }}>⚠️ {error}</p>
          ) : items.length === 0 ? (
            <p>データを読み込み中...</p>
          ) : (
            <ul>
              {items.map((item, idx) => (
                <li key={idx} style={{ margin: '0.5rem 0' }}>{item}</li>
              ))}
            </ul>
          )}
        </div>

        {/* POST 検証エリア */}
        <div style={{ padding: '1rem', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', backgroundColor: 'rgba(255,255,255,0.02)' }}>
          <h3>2. POST 疎通テスト (/api/process)</h3>
          <form onSubmit={handlePost} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="大文字に変換する英字を入力..."
              style={{
                flex: 1,
                padding: '0.6rem 1rem',
                borderRadius: '6px',
                border: '1px solid rgba(255,255,255,0.2)',
                backgroundColor: 'rgba(0,0,0,0.2)',
                color: '#fff',
                fontSize: '1rem'
              }}
            />
            <button
              type="submit"
              style={{
                padding: '0.6rem 1.2rem',
                borderRadius: '6px',
                border: 'none',
                backgroundColor: '#646cff',
                color: '#fff',
                cursor: 'pointer',
                fontSize: '1rem',
                fontWeight: 'bold'
              }}
            >
              送信
            </button>
          </form>
          {processedText && (
            <div style={{ padding: '0.8rem', borderRadius: '6px', backgroundColor: 'rgba(100,108,255,0.1)', borderLeft: '4px solid #646cff' }}>
              <strong>レスポンス結果:</strong>
              <p style={{ margin: '0.4rem 0 0 0', fontFamily: 'monospace' }}>{processedText}</p>
            </div>
          )}
        </div>
      </section>

      <div className="ticks"></div>

      <section id="next-steps">
        <div id="docs">
          <svg className="icon" role="presentation" aria-hidden="true">
            <use href="/icons.svg#documentation-icon"></use>
          </svg>
          <h2>Documentation</h2>
          <p>Your questions, answered</p>
          <ul>
            <li>
              <a href="https://vite.dev/" target="_blank">
                <img className="logo" src={viteLogo} alt="" />
                Explore Vite
              </a>
            </li>
            <li>
              <a href="https://react.dev/" target="_blank">
                <img className="button-icon" src={reactLogo} alt="" />
                Learn more
              </a>
            </li>
          </ul>
        </div>
        <div id="social">
          <svg className="icon" role="presentation" aria-hidden="true">
            <use href="/icons.svg#social-icon"></use>
          </svg>
          <h2>Connect with us</h2>
          <p>Join the Vite community</p>
          <ul>
            <li>
              <a href="https://github.com/vitejs/vite" target="_blank">
                <svg
                  className="button-icon"
                  role="presentation"
                  aria-hidden="true"
                >
                  <use href="/icons.svg#github-icon"></use>
                </svg>
                GitHub
              </a>
            </li>
            <li>
              <a href="https://chat.vite.dev/" target="_blank">
                <svg
                  className="button-icon"
                  role="presentation"
                  aria-hidden="true"
                >
                  <use href="/icons.svg#discord-icon"></use>
                </svg>
                Discord
              </a>
            </li>
            <li>
              <a href="https://x.com/vite_js" target="_blank">
                <svg
                  className="button-icon"
                  role="presentation"
                  aria-hidden="true"
                >
                  <use href="/icons.svg#x-icon"></use>
                </svg>
                X.com
              </a>
            </li>
            <li>
              <a href="https://bsky.app/profile/vite.dev" target="_blank">
                <svg
                  className="button-icon"
                  role="presentation"
                  aria-hidden="true"
                >
                  <use href="/icons.svg#bluesky-icon"></use>
                </svg>
                Bluesky
              </a>
            </li>
          </ul>
        </div>
      </section>

      <div className="ticks"></div>
      <section id="spacer"></section>
    </>
  )
}

export default App
