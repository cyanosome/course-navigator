import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import heroImg from './assets/hero.png'
import PostgresTest from './components/PostgresTest'
import Neo4jTest from './components/Neo4jTest'
import IntegratedTest from './components/IntegratedTest'
import AgentTest from './components/AgentTest'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <div style={styles.appContainer}>
        {/* ナビゲーションバー */}
        <nav style={styles.navBar}>
          <div style={styles.navLogo}>
            <span style={styles.navLogoText}>Course Navigator</span>
          </div>
          <div style={styles.navLinks}>
            <Link to="/" style={styles.navLink}>Home</Link>
            <Link to="/test2-1" style={styles.navLink}>test2-1: postgres</Link>
            <Link to="/test2-2" style={styles.navLink}>test2-2: neo4j</Link>
            <Link to="/test2-3" style={styles.navLink}>test2-3: integratedDB</Link>
            <Link to="/test3-1" style={styles.navLink}>test3-1: static_agent</Link>
          </div>
        </nav>

        {/* ルーティング定義 */}
        <Routes>
          <Route path="/" element={<WelcomeScreen />} />
          <Route path="/test2-1" element={<PostgresTest />} />
          <Route path="/test2-2" element={<Neo4jTest />} />
          <Route path="/test2-3" element={<IntegratedTest />} />
          <Route path="/test3-1" element={<AgentTest />} />
          {/* 旧パス互換 */}
          <Route path="/test1" element={<PostgresTest />} />
          <Route path="/test2" element={<Neo4jTest />} />
          <Route path="/test3" element={<IntegratedTest />} />
          <Route path="/test4" element={<AgentTest />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}

function WelcomeScreen() {
  return (
    <section id="center">
      <div className="hero">
        <img src={heroImg} className="base" width="170" height="179" alt="" />
      </div>
      <div>
        <h1>Course Navigator</h1>
        <p>現在開発中です。上部のナビゲーションから各疎通テストページを確認できます。</p>
      </div>
    </section>
  )
}

const styles: { [key: string]: React.CSSProperties } = {
  appContainer: {
    display: 'flex',
    flexDirection: 'column',
    width: '100%',
  },
  navBar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '1rem 2rem',
    borderBottom: '1px solid var(--border)',
    background: 'var(--social-bg)',
    backdropFilter: 'blur(8px)',
  },
  navLogo: {
    display: 'flex',
    alignItems: 'center',
  },
  navLogoText: {
    fontSize: '1.2rem',
    fontWeight: 'bold',
    color: 'var(--text-h)',
  },
  navLinks: {
    display: 'flex',
    gap: '1.5rem',
  },
  navLink: {
    color: 'var(--text)',
    textDecoration: 'none',
    fontSize: '0.95rem',
    fontWeight: 500,
    transition: 'color 0.2s',
  },
}

export default App
