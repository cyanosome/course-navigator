import { useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { testPageStyles, getAlertStyle } from '../styles/testPageStyles'
import { getErrorMessage } from '../utils/errorMessage'

/** DB（PostgreSQL）の行から組み立てた出典。LLM の生成テキストではない。 */
interface Source {
  code: string
  title: string
  instructor: string | null
  schedule: string | null
  credits: number | null
  excerpt: string
  origin: string
  url: string | null
}

/** LlmAgent のツール呼び出し1件（adk web の Events 表示に相当）。 */
interface ToolCall {
  name: string
  /** ツール引数は任意の JSON なので境界の型として unknown で受ける */
  args: Record<string, unknown>
  result_summary: string | null
}

interface McpAgentResponse {
  route: 'mcp' | 'static'
  answer: string
  cited_codes: string[]
  sources: Source[]
  unverified_codes: string[]
  notes: string[]
  tool_calls: ToolCall[]
  node_sequence: string[]
  model: string | null
  latency_ms: number
}

const SAMPLE_QUESTIONS = [
  { label: '後続科目', text: 'データサイエンスの次に取るべき科目は?' },
  { label: '前提科目', text: '機械学習を履修する前に必要な科目は?' },
  { label: '関連分野', text: 'データベースと共通のトピックを扱う科目は?' },
  { label: '詳細 (教員・時限)', text: 'セキュリティ分野の科目の担当教員と開講時期を教えて' },
]

export default function McpAgentTest() {
  const [question, setQuestion] = useState('データサイエンスの次に取るべき科目は?')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<McpAgentResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleQuery = async (e?: FormEvent) => {
    if (e) e.preventDefault()
    if (!question.trim()) return

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch('/api/test/agent/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.trim() }),
      })

      if (!res.ok) {
        // FastAPI の detail（JSON）や 500 の本文をそのまま見せる
        const body = await res.text()
        throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
      }

      const data: McpAgentResponse = await res.json()
      setResult(data)
    } catch (err: unknown) {
      console.error('test3-2 の問い合わせに失敗しました:', err)
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={testPageStyles.container}>
      <h1 style={testPageStyles.title}>test3-2: mcp_agent (LLM + Neo4j MCP + RDB)</h1>
      <p style={testPageStyles.subtitle}>
        本画面（test3-2: mcp_agent）は、LLM Agent が Neo4j を MCP ツールで探索し、候補科目のシラバス詳細を PostgreSQL ツールで確認して回答します。回答の後段で決定論ノード（attach_sources）が引用コードを DB で引き直し、出典カードを DB の行から組み立てます。DB に無いコードは「未検証」として警告します。MCP が無効、または GEMINI_API_KEY が未設定の場合は test3-1 と同じ静的 DAG で回答します（route: static）。
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
                placeholder="例: データサイエンスの次に取るべき科目は?"
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
                {loading ? '実行中...' : 'Agent 実行'}
              </button>
            </div>
          </div>
        </form>

        {/* サンプル質問ボタン */}
        <div style={{ marginTop: '1rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
          <span style={{ fontSize: '0.85rem', color: 'var(--text)', fontWeight: 'bold' }}>サンプル質問:</span>
          {SAMPLE_QUESTIONS.map((sq) => (
            <button
              key={sq.text}
              type="button"
              onClick={() => setQuestion(sq.text)}
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
          <p>Agent が Neo4j / PostgreSQL を探索しています...（LLM 呼び出しのため数十秒かかることがあります）</p>
        </div>
      )}

      {/* 結果表示エリア */}
      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          {/* 1. 回答カード */}
          <div style={testPageStyles.card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
              <h2 style={{ ...testPageStyles.cardTitle, margin: 0, border: 'none', padding: 0 }}>回答</h2>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={result.route === 'mcp' ? styles.badgeRouteMcp : styles.badgeRouteStatic}>
                  Route: {result.route}
                </span>
                <span style={styles.badgeMeta}>Model: {result.model ?? '（LLM 不使用）'}</span>
                <span style={styles.badgeMeta}>Latency: {result.latency_ms} ms</span>
              </div>
            </div>

            {result.route === 'static' && (
              <p style={{ fontSize: '0.85rem', color: 'var(--text)', marginTop: 0 }}>
                MCP が無効、または GEMINI_API_KEY が未設定のため、静的 DAG（test3-1 と同じ経路）で回答しました。
              </p>
            )}

            <div style={styles.answerBox}>
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6', fontSize: '1.05rem', color: 'var(--text-h)' }}>
                {result.answer || '（回答はありません）'}
              </div>
            </div>

            <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--text)' }}>
              <span style={{ fontWeight: 'bold' }}>引用コード (cited_codes): </span>
              {result.cited_codes.length === 0 ? '（なし）' : result.cited_codes.join(', ')}
            </div>
          </div>

          {/* 2. 未検証コード・注記の警告 */}
          {result.unverified_codes.length > 0 && (
            <div style={styles.warningBox}>
              <div style={{ fontWeight: 'bold', marginBottom: '0.25rem' }}>
                未検証の引用コード ({result.unverified_codes.length} 件)
              </div>
              <div>
                回答が引用した次のコードは DB で確認できなかったため、出典に含めていません（LLM の誤引用の可能性があります）:
              </div>
              <div style={{ fontFamily: 'var(--mono)', marginTop: '0.25rem' }}>{result.unverified_codes.join(', ')}</div>
            </div>
          )}
          {result.notes.length > 0 && (
            <div style={styles.warningBox}>
              {result.notes.map((note, idx) => (
                <div key={idx}>{note}</div>
              ))}
            </div>
          )}

          {/* 3. 出典カード */}
          <div style={testPageStyles.card}>
            <h2 style={testPageStyles.cardTitle}>出典 ({result.sources.length} 件)</h2>
            {result.sources.length === 0 ? (
              <p style={testPageStyles.noData}>
                {result.route === 'mcp' ? 'DB で確認できた出典はありません。' : 'static ルートでは出典を付与しません。'}
              </p>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
                {result.sources.map((source) => (
                  <div key={source.code} style={styles.sourceCard}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.75rem', flexWrap: 'wrap' }}>
                      <span style={styles.sourceCode}>{source.code}</span>
                      <span style={styles.sourceTitle}>{source.title}</span>
                    </div>
                    <div style={styles.sourceMeta}>
                      <div>担当: {source.instructor ?? '（未登録）'}</div>
                      <div>開講: {source.schedule ?? '（未登録）'}</div>
                      <div>単位: {source.credits ?? '（未登録）'}</div>
                    </div>
                    {source.excerpt && <div style={styles.sourceExcerpt}>{source.excerpt}</div>}
                    <div style={styles.sourceOrigin}>
                      出典元: <code>{source.origin}</code>
                      {source.url && (
                        <>
                          {' / '}
                          <a href={source.url} target="_blank" rel="noopener noreferrer">
                            シラバスを開く
                          </a>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 4. ツール呼び出しタイムライン */}
          <div style={testPageStyles.card}>
            <h2 style={testPageStyles.cardTitle}>ツール呼び出し ({result.tool_calls.length} 件)</h2>
            {result.tool_calls.length === 0 ? (
              <p style={testPageStyles.noData}>ツール呼び出しはありません。</p>
            ) : (
              <ol style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {result.tool_calls.map((call, idx) => (
                  <li key={idx} style={styles.toolCallItem}>
                    <code style={styles.toolName}>
                      #{idx + 1} {call.name}
                    </code>
                    <pre style={styles.codeBlock}>{JSON.stringify(call.args, null, 2)}</pre>
                    {call.result_summary === null ? (
                      <div style={{ fontSize: '0.8rem', color: 'var(--text)' }}>（応答イベントなし）</div>
                    ) : (
                      <details>
                        <summary style={{ cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text)' }}>結果 (要約)</summary>
                        <pre style={styles.codeBlock}>{call.result_summary}</pre>
                      </details>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>

          {/* 5. ノード順序 */}
          <div style={testPageStyles.card}>
            <h2 style={testPageStyles.cardTitle}>通過したノード (Node Sequence)</h2>
            <div style={{ fontFamily: 'var(--mono)', fontSize: '0.9rem', color: 'var(--text-h)', wordBreak: 'break-all' }}>
              {result.node_sequence.length === 0 ? '（なし）' : result.node_sequence.join(' → ')}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const badgeBase: CSSProperties = {
  padding: '0.25rem 0.6rem',
  borderRadius: '6px',
  fontSize: '0.8rem',
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
  badgeRouteMcp: {
    ...badgeBase,
    background: 'var(--accent)',
    color: '#fff',
    fontWeight: 'bold',
  },
  badgeRouteStatic: {
    ...badgeBase,
    background: 'var(--text)',
    color: 'var(--bg)',
    fontWeight: 'bold',
  },
  badgeMeta: {
    ...badgeBase,
    background: 'var(--code-bg)',
    border: '1px solid var(--border)',
    color: 'var(--text-h)',
  },
  answerBox: {
    padding: '1.2rem',
    borderRadius: '8px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
  },
  warningBox: {
    padding: '1rem',
    borderRadius: '8px',
    border: '1px solid rgba(234, 179, 8, 0.5)',
    background: 'rgba(234, 179, 8, 0.1)',
    color: 'var(--text-h)',
    fontSize: '0.9rem',
  },
  sourceCard: {
    padding: '1rem',
    borderRadius: '8px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  sourceCode: {
    fontSize: '0.9rem',
    fontFamily: 'var(--mono)',
    fontWeight: 'bold',
    color: 'var(--accent)',
  },
  sourceTitle: {
    fontSize: '1.1rem',
    fontWeight: 500,
    color: 'var(--text-h)',
  },
  sourceMeta: {
    fontSize: '0.85rem',
    color: 'var(--text)',
  },
  sourceExcerpt: {
    fontSize: '0.9rem',
    color: 'var(--text-h)',
    padding: '0.5rem 0.75rem',
    borderLeft: '3px solid var(--accent)',
    background: 'var(--social-bg)',
    borderRadius: '4px',
  },
  sourceOrigin: {
    fontSize: '0.75rem',
    color: 'var(--text)',
  },
  toolCallItem: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.35rem',
  },
  toolName: {
    fontWeight: 'bold',
    color: 'var(--accent)',
  },
  codeBlock: {
    margin: 0,
    padding: '0.75rem',
    borderRadius: '6px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    fontSize: '0.8rem',
    fontFamily: 'var(--mono)',
    maxHeight: '240px',
    overflow: 'auto',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
  },
}
