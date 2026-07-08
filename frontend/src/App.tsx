import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import heroImg from './assets/hero.png'
import PostgresTest from './components/PostgresTest'
import Neo4jTest from './components/Neo4jTest'
import IntegratedTest from './components/IntegratedTest'
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
            <Link to="/test1" style={styles.navLink}>Postgres Test (test1)</Link>
            <Link to="/test2" style={styles.navLink}>Neo4j Test (test2)</Link>
            <Link to="/test3" style={styles.navLink}>Integrated Test (test3)</Link>
          </div>
        </nav>

        {/* ルーティング定義 */}
        <Routes>
          <Route path="/" element={<WelcomeScreen />} />
          <Route path="/test1" element={<PostgresTest />} />
          <Route path="/test2" element={<Neo4jTest />} />
          <Route path="/test3" element={<IntegratedTest />} />
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
