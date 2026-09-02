import { useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { testPageStyles, getAlertStyle } from '../styles/testPageStyles'
import { getErrorMessage } from '../utils/errorMessage'

interface Evidence {
  kind: string
  text: string
  edge_refs: string[]
}

interface Candidate {
  code: string
  title: string
  hops: number
  path_codes: string[]
  reason: string
  shared_topics?: string[]
  evidence: Evidence[]
}

interface SearchIntent {
  mode: string
  anchor_code: string | null
  anchor_title: string | null
  anchor_status: string
  alternatives: string[]
  unclear_kind: string | null
  raw_question: string
  matched_rule: string
}

interface AgentQueryResponse {
  answer: string
  cited_codes: string[]
  intent: SearchIntent
  candidates: Candidate[]
  traversed_edges: string[]
  node_sequence: string[]
}

const SAMPLE_QUESTIONS = [
  { label: '後続探索 (次取れる科目)', text: 'データサイエンス入門の次に取れる科目は?' },
  { label: '前提探索 (必要な科目)', text: '機械学習を取るのに必要な前提科目は?' },
  { label: 'トピック探索 (関連分野)', text: 'データベースに近い分野の科目は?' },
  { label: '曖昧な質問 (案内)', text: '何かおすすめの授業ある?' },
]

export default function AgentTest() {
  const [question, setQuestion] = useState('データサイエンス入門の次に取れる科目は?')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AgentQueryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleQuery = async (e?: FormEvent) => {
    if (e) e.preventDefault()
    if (!question.trim()) return

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch('/api/test/agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.trim() }),
      })

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`)
      }

      const data: AgentQueryResponse = await res.json()
      setResult(data)
    } catch (err: unknown) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const handleSampleClick = (text: string) => {
    setQuestion(text)
  }

  return (
    <div style={testPageStyles.container}>
      <h1 style={testPageStyles.title}>test3-1: static_agent (Rule & Graph Search)</h1>
      <p style={testPageStyles.subtitle}>
        本画面（test3-1: static_agent）は LLM を使わず、ルールベースの意図解析と Neo4j グラフ探索（Evidence 連結）のみで決定論的に回答を出力するベースライン検証ページです。次のステップ（test3-2）でここに LLM ノードを組み込み、自然言語での柔軟なアドバイス回答を生成します。
      </p>

      {/* エラーアラート */}
      {error && (
        <div style={getAlertStyle(testPageStyles.alert, 'error')}>
          {error}
        </div>
      )}

      {/* 質問入力カード */}
      <div style={{ ...testPageStyles.card, marginBottom: '2rem' }}>
        <h2 style={testPageStyles.cardTitle}>質問入力</h2>
        <form onSubmit={handleQuery} style={testPageStyles.form}>
          <div style={testPageStyles.formGroup}>
            <label style={testPageStyles.label}>質問文 (日本語自然言語):</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="例: データサイエンス入門の次に取れる科目は?"
                style={{ ...testPageStyles.input, flex: 1 }}
              />
              <button
                type="submit"
                disabled={loading || !question.trim()}
                style={{
                  ...testPageStyles.button,
                  opacity: loading || !question.trim() ? 0.6 : 1,
                  cursor: loading || !question.trim() ? 'not-allowed' : 'pointer',
                  minWidth: '120px',
                }}
              >
                {loading ? '探索中...' : '探索実行'}
              </button>
            </div>
          </div>
        </form>

        {/* サンプル質問ボタン */}
        <div style={{ marginTop: '1rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
          <span style={{ fontSize: '0.85rem', color: 'var(--text)', fontWeight: 'bold' }}>サンプル質問:</span>
          {SAMPLE_QUESTIONS.map((sq, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => handleSampleClick(sq.text)}
              style={styles.sampleButton}
            >
              {sq.label}
            </button>
          ))}
        </div>
      </div>

      {/* ローディング表示 */}
      {loading && (
        <div style={testPageStyles.loading}>
          <p>Neo4j グラフDBを探索しています...</p>
        </div>
      )}

      {/* 結果表示エリア */}
      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          {/* 1. 回答サマリー & 意図解析カード */}
          <div style={testPageStyles.card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h2 style={{ ...testPageStyles.cardTitle, margin: 0, border: 'none', padding: 0 }}>探索結果サマリー</h2>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <span style={styles.badgeMode}>
                  Mode: {result.intent.mode}
                </span>
                {result.intent.anchor_code && (
                  <span style={styles.badgeAnchor}>
                    Anchor: {result.intent.anchor_code} ({result.intent.anchor_title})
                  </span>
                )}
              </div>
            </div>

            <div style={styles.answerBox}>
              <div style={{ fontSize: '0.85rem', color: 'var(--text)', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                生成された回答（Evidence 連結）:
              </div>
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6', fontSize: '1.05rem', color: 'var(--text-h)' }}>
                {result.answer || '（回答はありません）'}
              </div>
            </div>

            {result.intent.matched_rule && (
              <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--text)' }}>
                <span style={{ fontWeight: 'bold' }}>適用ルール: </span>
                <code>{result.intent.matched_rule}</code>
              </div>
            )}
          </div>

          {/* 2. 探索された候補講義一覧カード */}
          <div style={testPageStyles.card}>
            <h2 style={testPageStyles.cardTitle}>
              検出された講義候補 ({result.candidates.length} 件)
            </h2>

            {result.candidates.length === 0 ? (
              <p style={testPageStyles.noData}>該当する講義候補は見つかりませんでした。</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {result.candidates.map((c, idx) => (
                  <div key={idx} style={styles.candidateCard}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '0.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <span style={styles.candidateCode}>{c.code}</span>
                        <span style={styles.candidateTitle}>{c.title}</span>
                      </div>
                      <span style={styles.candidateHops}>距離: {c.hops} hop</span>
                    </div>

                    {c.path_codes && c.path_codes.length > 0 && (
                      <div style={{ fontSize: '0.85rem', color: 'var(--text)' }}>
                        <span style={{ fontWeight: 'bold' }}>探索パス: </span>
                        {c.path_codes.join(' → ')}
                      </div>
                    )}

                    {c.shared_topics && c.shared_topics.length > 0 && (
                      <div style={{ fontSize: '0.85rem', color: 'var(--text)' }}>
                        <span style={{ fontWeight: 'bold' }}>共通トピック: </span>
                        {c.shared_topics.join(', ')}
                      </div>
                    )}

                    {/* Evidence（根拠） */}
                    {c.evidence && c.evidence.length > 0 && (
                      <div style={styles.evidenceBox}>
                        <div style={{ fontSize: '0.8rem', fontWeight: 'bold', color: 'var(--accent)', marginBottom: '0.25rem' }}>
                          Evidence（根拠事実）:
                        </div>
                        {c.evidence.map((ev, eIdx) => (
                          <div key={eIdx} style={{ fontSize: '0.9rem', color: 'var(--text-h)' }}>
                            • {ev.text}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 3. グラフ探索トレース (デバッグ・検証用) */}
          <div style={testPageStyles.card}>
            <h2 style={testPageStyles.cardTitle}>グラフ探索トレース (ADK 実行詳細)</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>
              <div>
                <h3 style={styles.subHeading}>通過したノード順序 (Node Sequence):</h3>
                <div style={styles.codeBlock}>
                  {result.node_sequence.map((node, nIdx) => (
                    <div key={nIdx} style={{ padding: '0.2rem 0' }}>
                      {nIdx + 1}. <code>{node}</code>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <h3 style={styles.subHeading}>辿ったグラフエッジ (Traversed Edges):</h3>
                <div style={styles.codeBlock}>
                  {result.traversed_edges.length === 0 ? (
                    <span style={{ color: 'var(--text)' }}>（エッジ通過なし）</span>
                  ) : (
                    result.traversed_edges.map((edge, eIdx) => (
                      <div key={eIdx} style={{ padding: '0.2rem 0', wordBreak: 'break-all' }}>
                        <code>{edge}</code>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const styles: Record<string, CSSProperties> = {
  sampleButton: {
    padding: '0.35rem 0.75rem',
    borderRadius: '16px',
    border: '1px solid var(--border)',
    background: 'var(--code-bg)',
    color: 'var(--text-h)',
    fontSize: '0.8rem',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
  badgeMode: {
    padding: '0.25rem 0.6rem',
    borderRadius: '6px',
    background: 'var(--accent)',
    color: '#fff',
    fontSize: '0.8rem',
    fontWeight: 'bold',
  },
  badgeAnchor: {
    padding: '0.25rem 0.6rem',
    borderRadius: '6px',
    background: 'var(--code-bg)',
    border: '1px solid var(--border)',
    color: 'var(--text-h)',
    fontSize: '0.8rem',
  },
  answerBox: {
    padding: '1.2rem',
    borderRadius: '8px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
  },
  candidateCard: {
    padding: '1rem',
    borderRadius: '8px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  candidateCode: {
    fontSize: '0.9rem',
    fontFamily: 'var(--mono)',
    fontWeight: 'bold',
    color: 'var(--accent)',
  },
  candidateTitle: {
    fontSize: '1.1rem',
    fontWeight: 500,
    color: 'var(--text-h)',
  },
  candidateHops: {
    fontSize: '0.85rem',
    color: 'var(--text)',
    background: 'var(--code-bg)',
    padding: '0.2rem 0.5rem',
    borderRadius: '4px',
  },
  evidenceBox: {
    marginTop: '0.5rem',
    padding: '0.75rem',
    borderRadius: '6px',
    background: 'var(--social-bg)',
    borderLeft: '3px solid var(--accent)',
  },
  subHeading: {
    fontSize: '0.95rem',
    fontWeight: 'bold',
    color: 'var(--text-h)',
    marginBottom: '0.5rem',
  },
  codeBlock: {
    padding: '0.75rem',
    borderRadius: '6px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    fontSize: '0.85rem',
    fontFamily: 'var(--mono)',
    maxHeight: '200px',
    overflowY: 'auto',
  },
}
