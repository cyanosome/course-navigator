import { useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { testPageStyles, getAlertStyle } from '../styles/testPageStyles'
import { getErrorMessage } from '../utils/errorMessage'

interface CoursePrereqItem {
  code: string
  title: string
  credits?: number | null
  term?: string | null
  depth: number
}

interface CourseSearchResultItem {
  code: string
  title: string
  credits?: number | null
  term?: string | null
  category?: string | null
  requirement_category?: string | null
  score: number
  prerequisites: CoursePrereqItem[]
}

interface CourseSearchResponse {
  mode: 'hybrid' | 'similarity' | 'pure_graph'
  query: string
  total_hits: number
  execution_time_ms: number
  results: CourseSearchResultItem[]
}

interface GraphNode {
  id: string
  code: string
  title: string
  credits?: number | null
  term?: string | null
  node_type: string
}

interface GraphEdge {
  source: string
  target: string
  type: string
  score?: number | null
}

interface CourseGraphResponse {
  course_code: string
  title: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}

const SAMPLE_QUERIES: Array<{ label: string; text: string; mode: 'hybrid' | 'similarity' | 'pure_graph' }> = [
  { label: '自然言語 (推薦)', text: 'データサイエンスと統計分析', mode: 'hybrid' },
  { label: '機械学習', text: '機械学習', mode: 'hybrid' },
  { label: '類似度 (実習)', text: '健康・スポーツ科学実習', mode: 'similarity' },
  { label: '前提チェーン', text: '特別研究', mode: 'pure_graph' },
  { label: '化学工学', text: '化学工学', mode: 'pure_graph' },
]

export default function CypherSearchTest() {
  const [query, setQuery] = useState('データサイエンスと統計分析')
  const [mode, setMode] = useState<'hybrid' | 'similarity' | 'pure_graph'>('hybrid')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<CourseSearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Graph inspection state
  const [activeGraph, setActiveGraph] = useState<CourseGraphResponse | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)

  const handleSearch = async (e?: FormEvent) => {
    if (e) e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setError(null)
    setActiveGraph(null)

    try {
      const response = await fetch('/api/search/courses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          mode,
          top_k: 6,
          max_depth: 3,
        }),
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => null)
        throw new Error(errData?.detail || `HTTP Error ${response.status}`)
      }

      const data: CourseSearchResponse = await response.json()
      setResult(data)
    } catch (err: unknown) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const handleInspectGraph = async (courseCode: string) => {
    setGraphLoading(true)
    try {
      const resp = await fetch(`/api/courses/${courseCode}/graph`)
      if (!resp.ok) {
        throw new Error(`Failed to load graph (${resp.status})`)
      }
      const gData: CourseGraphResponse = await resp.json()
      setActiveGraph(gData)
    } catch (err: unknown) {
      alert(`グラフ取得エラー: ${getErrorMessage(err)}`)
    } finally {
      setGraphLoading(false)
    }
  }

  return (
    <div style={testPageStyles.container}>
      <h1 style={testPageStyles.title}>test4-1: Cypher Search & Graph Navigator</h1>
      <p style={testPageStyles.subtitle}>
        Neo4j 5.x ネイティブ Vector Index (768次元) とトポロジー走査を組み合わせた 3 つの探索モードの検証画面です。
      </p>

      {/* モード切替タブ */}
      <div style={styles.modeTabBar}>
        <button
          type="button"
          onClick={() => setMode('hybrid')}
          style={{
            ...styles.modeTab,
            ...(mode === 'hybrid' ? styles.modeTabActive : {}),
          }}
        >
          <span style={styles.tabBadge}>提案手法</span>
          Mode A: Proposed Hybrid
        </button>
        <button
          type="button"
          onClick={() => setMode('similarity')}
          style={{
            ...styles.modeTab,
            ...(mode === 'similarity' ? styles.modeTabActive : {}),
          }}
        >
          Mode B: Precomputed Similarity
        </button>
        <button
          type="button"
          onClick={() => setMode('pure_graph')}
          style={{
            ...styles.modeTab,
            ...(mode === 'pure_graph' ? styles.modeTabActive : {}),
          }}
        >
          Mode C: Pure Graph
        </button>
      </div>

      {/* 検索入力フォーム */}
      <div style={styles.searchCard}>
        <form onSubmit={handleSearch} style={styles.formRow}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              mode === 'hybrid'
                ? '学習関心・自然言語（例: データサイエンスとアルゴリズム）'
                : '科目名または科目コード（例: 特別研究, 062620）'
            }
            style={styles.searchInput}
          />
          <button type="submit" disabled={loading} style={styles.submitBtn}>
            {loading ? '探索中...' : 'Cypher 検索実行'}
          </button>
        </form>

        {/* サンプルクエリ */}
        <div style={styles.samplesContainer}>
          <span style={styles.sampleLabel}>サンプル:</span>
          {SAMPLE_QUERIES.map((sq) => (
            <button
              key={sq.text}
              type="button"
              onClick={() => {
                setQuery(sq.text)
                setMode(sq.mode)
              }}
              style={styles.sampleChip}
            >
              {sq.label}
            </button>
          ))}
        </div>
      </div>

      {/* エラー表示 */}
      {error && (
        <div style={getAlertStyle(testPageStyles.alert, 'error')}>
          <strong>検索エラー:</strong> {error}
        </div>
      )}

      {/* レイテンシ & 統計バー */}
      {result && (
        <div style={styles.metricsBar}>
          <div>
            <strong>探索モード:</strong>{' '}
            <span style={styles.metricHighlight}>{result.mode.toUpperCase()}</span>
          </div>
          <div>
            <strong>ヒット件数:</strong>{' '}
            <span style={styles.metricHighlight}>{result.total_hits} 件</span>
          </div>
          <div>
            <strong>クエリレイテンシ:</strong>{' '}
            <span style={styles.metricLatency}>{result.execution_time_ms} ms</span>
          </div>
        </div>
      )}

      {/* 0件時の空表示 */}
      {result && result.results.length === 0 && (
        <div style={styles.emptyCard}>
          <p>該当する科目が一致しませんでした。別のキーワードや探索モードをお試しください。</p>
        </div>
      )}

      {/* 検索結果カード一覧 */}
      {result && result.results.length > 0 && (
        <div style={styles.resultsGrid}>
          {result.results.map((item, idx) => (
            <div key={`${item.code}-${idx}`} style={styles.courseCard}>
              <div style={styles.cardHeader}>
                <span style={styles.courseCode}>{item.code || 'コードなし'}</span>
                <span style={styles.scoreBadge}>
                  類似度: {(item.score * 100).toFixed(1)}%
                </span>
              </div>
              <h3 style={styles.courseTitle}>{item.title}</h3>

              <div style={styles.metaRow}>
                {item.credits !== null && item.credits !== undefined && (
                  <span style={styles.metaChip}>{item.credits} 単位</span>
                )}
                {item.term && <span style={styles.metaChip}>{item.term}</span>}
                {item.requirement_category && (
                  <span style={styles.reqChip}>{item.requirement_category}</span>
                )}
              </div>

              {/* 前提科目チェーン (DAG) */}
              <div style={styles.prereqSection}>
                <div style={styles.prereqHeader}>
                  <span>前提履修チェーン:</span>
                  <span style={styles.prereqCount}>
                    {item.prerequisites.length > 0
                      ? `${item.prerequisites.length} 科目`
                      : '前提なし (直接履修可)'}
                  </span>
                </div>
                {item.prerequisites.length > 0 && (
                  <div style={styles.prereqChain}>
                    {item.prerequisites.map((p, pIdx) => (
                      <div key={`${p.code}-${pIdx}`} style={styles.prereqStep}>
                        <span style={styles.stepBadge}>Step {p.depth}</span>
                        <span style={styles.prereqTitle}>{p.title}</span>
                        <span style={styles.prereqCode}>({p.code})</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* グラフ可視化ボタン */}
              <div style={styles.cardActions}>
                <button
                  type="button"
                  onClick={() => handleInspectGraph(item.code)}
                  style={styles.graphInspectBtn}
                  disabled={graphLoading}
                >
                  🕸️ 前提DAG & 類似エッジを可視化
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* グラフ詳細モーダル / パネル */}
      {activeGraph && (
        <div style={styles.graphModal}>
          <div style={styles.graphModalContent}>
            <div style={styles.modalHeader}>
              <h2>
                ナレッジグラフ探索: {activeGraph.title} ({activeGraph.course_code})
              </h2>
              <button
                type="button"
                onClick={() => setActiveGraph(null)}
                style={styles.closeBtn}
              >
                ✕ 閉じる
              </button>
            </div>
            <div style={styles.graphDetails}>
              <div>
                <strong>接続ノード ({activeGraph.nodes.length} 件):</strong>
                <ul style={styles.nodeList}>
                  {activeGraph.nodes.map((n) => (
                    <li key={n.id} style={styles.nodeItem}>
                      <span
                        style={{
                          ...styles.nodeTypeBadge,
                          background:
                            n.node_type === 'seed'
                              ? '#3b82f6'
                              : n.node_type === 'prerequisite'
                              ? '#f59e0b'
                              : '#10b981',
                        }}
                      >
                        {n.node_type}
                      </span>
                      <strong>{n.title}</strong> ({n.code})
                      {n.credits && ` - ${n.credits}単位`}
                    </li>
                  ))}
                </ul>
              </div>
              <div style={{ marginTop: '1.5rem' }}>
                <strong>接続エッジ ({activeGraph.edges.length} 本):</strong>
                <ul style={styles.edgeList}>
                  {activeGraph.edges.map((e, eIdx) => (
                    <li key={eIdx} style={styles.edgeItem}>
                      <code>{e.source}</code> ➔{' '}
                      <span style={styles.relBadge}>{e.type}</span> ➔{' '}
                      <code>{e.target}</code>
                      {e.score !== null && e.score !== undefined && (
                        <span style={styles.edgeScore}>
                          {' '}
                          (score: {e.score.toFixed(3)})
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const styles: Record<string, CSSProperties> = {
  modeTabBar: {
    display: 'flex',
    gap: '0.5rem',
    marginBottom: '1.5rem',
    flexWrap: 'wrap',
  },
  modeTab: {
    padding: '0.75rem 1.25rem',
    borderRadius: '8px',
    border: '1px solid var(--border)',
    background: 'var(--social-bg)',
    color: 'var(--text)',
    fontSize: '0.95rem',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    transition: 'all 0.2s',
  },
  modeTabActive: {
    background: 'var(--accent)',
    color: '#fff',
    borderColor: 'var(--accent)',
    fontWeight: 'bold',
  },
  tabBadge: {
    fontSize: '0.75rem',
    background: 'rgba(255, 255, 255, 0.25)',
    padding: '2px 6px',
    borderRadius: '4px',
  },
  searchCard: {
    background: 'var(--social-bg)',
    border: '1px solid var(--border)',
    borderRadius: '12px',
    padding: '1.5rem',
    marginBottom: '1.5rem',
  },
  formRow: {
    display: 'flex',
    gap: '0.75rem',
  },
  searchInput: {
    flex: 1,
    padding: '0.85rem 1rem',
    borderRadius: '8px',
    border: '1px solid var(--border)',
    background: 'var(--bg)',
    color: 'var(--text-h)',
    fontSize: '1rem',
    outline: 'none',
  },
  submitBtn: {
    padding: '0.85rem 1.75rem',
    borderRadius: '8px',
    border: 'none',
    background: 'var(--accent)',
    color: '#fff',
    fontSize: '1rem',
    fontWeight: 'bold',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  samplesContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginTop: '0.75rem',
    flexWrap: 'wrap',
  },
  sampleLabel: {
    fontSize: '0.85rem',
    color: 'var(--text)',
  },
  sampleChip: {
    fontSize: '0.8rem',
    padding: '4px 10px',
    borderRadius: '16px',
    border: '1px solid var(--border)',
    background: 'var(--code-bg)',
    color: 'var(--text)',
    cursor: 'pointer',
  },
  metricsBar: {
    display: 'flex',
    gap: '2rem',
    padding: '1rem 1.5rem',
    borderRadius: '8px',
    background: 'var(--social-bg)',
    border: '1px solid var(--border)',
    marginBottom: '1.5rem',
    fontSize: '0.95rem',
    flexWrap: 'wrap',
  },
  metricHighlight: {
    color: 'var(--accent)',
    fontWeight: 'bold',
  },
  metricLatency: {
    color: '#10b981',
    fontWeight: 'bold',
  },
  resultsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))',
    gap: '1.5rem',
  },
  courseCard: {
    background: 'var(--social-bg)',
    border: '1px solid var(--border)',
    borderRadius: '12px',
    padding: '1.25rem',
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'space-between',
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '0.5rem',
  },
  courseCode: {
    fontFamily: 'var(--mono)',
    fontSize: '0.85rem',
    color: 'var(--text)',
  },
  scoreBadge: {
    fontSize: '0.75rem',
    fontWeight: 'bold',
    background: 'rgba(59, 130, 246, 0.15)',
    color: '#3b82f6',
    padding: '2px 8px',
    borderRadius: '12px',
  },
  courseTitle: {
    fontSize: '1.2rem',
    color: 'var(--text-h)',
    margin: '0 0 0.75rem 0',
  },
  metaRow: {
    display: 'flex',
    gap: '0.5rem',
    marginBottom: '1rem',
    flexWrap: 'wrap',
  },
  metaChip: {
    fontSize: '0.8rem',
    padding: '2px 8px',
    borderRadius: '4px',
    background: 'var(--code-bg)',
    color: 'var(--text)',
  },
  reqChip: {
    fontSize: '0.8rem',
    padding: '2px 8px',
    borderRadius: '4px',
    background: 'rgba(16, 185, 129, 0.15)',
    color: '#10b981',
    fontWeight: 500,
  },
  prereqSection: {
    background: 'var(--bg)',
    borderRadius: '8px',
    padding: '0.75rem',
    marginBottom: '1rem',
  },
  prereqHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.85rem',
    fontWeight: 'bold',
    color: 'var(--text-h)',
    marginBottom: '0.5rem',
  },
  prereqCount: {
    fontWeight: 'normal',
    color: 'var(--text)',
  },
  prereqChain: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.4rem',
  },
  prereqStep: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    fontSize: '0.85rem',
  },
  stepBadge: {
    fontSize: '0.7rem',
    background: '#f59e0b',
    color: '#fff',
    padding: '1px 6px',
    borderRadius: '4px',
    fontWeight: 'bold',
  },
  prereqTitle: {
    color: 'var(--text-h)',
  },
  prereqCode: {
    color: 'var(--text)',
    fontFamily: 'var(--mono)',
    fontSize: '0.75rem',
  },
  cardActions: {
    display: 'flex',
    justifyContent: 'flex-end',
  },
  graphInspectBtn: {
    fontSize: '0.85rem',
    padding: '0.5rem 0.75rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--code-bg)',
    color: 'var(--text-h)',
    cursor: 'pointer',
  },
  graphModal: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    background: 'rgba(0, 0, 0, 0.6)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 1000,
  },
  graphModalContent: {
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: '12px',
    padding: '2rem',
    maxWidth: '700px',
    width: '90%',
    maxHeight: '80vh',
    overflowY: 'auto',
    boxShadow: 'var(--shadow)',
  },
  modalHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderBottom: '1px solid var(--border)',
    paddingBottom: '1rem',
    marginBottom: '1rem',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text)',
    fontSize: '1.2rem',
    cursor: 'pointer',
  },
  graphDetails: {
    fontSize: '0.9rem',
    color: 'var(--text)',
  },
  nodeList: {
    listStyle: 'none',
    padding: 0,
    margin: '0.5rem 0 0 0',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  nodeItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    background: 'var(--social-bg)',
    padding: '0.5rem',
    borderRadius: '6px',
  },
  nodeTypeBadge: {
    fontSize: '0.7rem',
    color: '#fff',
    padding: '2px 6px',
    borderRadius: '4px',
    fontWeight: 'bold',
  },
  edgeList: {
    listStyle: 'none',
    padding: 0,
    margin: '0.5rem 0 0 0',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  edgeItem: {
    background: 'var(--social-bg)',
    padding: '0.5rem',
    borderRadius: '6px',
    fontFamily: 'var(--mono)',
    fontSize: '0.85rem',
  },
  relBadge: {
    color: '#ec4899',
    fontWeight: 'bold',
  },
  edgeScore: {
    color: '#3b82f6',
  },
  emptyCard: {
    padding: '2.5rem',
    textAlign: 'center',
    background: 'var(--social-bg)',
    borderRadius: '12px',
    border: '1px dashed var(--border)',
    color: 'var(--text)',
    marginTop: '1.5rem',
    fontSize: '0.95rem',
  },
}
