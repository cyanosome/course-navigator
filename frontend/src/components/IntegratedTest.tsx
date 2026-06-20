import React, { useState, useEffect } from 'react'

interface Prerequisite {
  id: string
  code: string
  title: string
}

interface RelatedCourse {
  id: string
  code: string
  title: string
  topic: string
}

interface SyllabusRecord {
  id: string
  code: string
  title: string
  instructor: string
  schedule: string
  credits: number
  syllabus_text: string | null
  prerequisites: Prerequisite[]
  topics: string[]
  related_courses: RelatedCourse[]
}

export default function IntegratedTest() {
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')
  const [instructor, setInstructor] = useState('')
  const [schedule, setSchedule] = useState('')
  const [credits, setCredits] = useState(2)
  const [syllabusText, setSyllabusText] = useState('')
  const [prereqCodesInput, setPrereqCodesInput] = useState('')
  const [topicsInput, setTopicsInput] = useState('')

  const [searchQuery, setSearchQuery] = useState('')
  const [records, setRecords] = useState<SyllabusRecord[]>([])
  const [isInserting, setIsInserting] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // 初期ロード時に全件取得
  useEffect(() => {
    fetchRecords()
  }, [])

  const fetchRecords = async (query = '') => {
    setIsSearching(true)
    try {
      const response = await fetch(`/api/test/integrated?q=${encodeURIComponent(query)}`)
      if (!response.ok) {
        throw new Error('Failed to fetch records')
      }
      const data = await response.json()
      setRecords(data)
    } catch (err: any) {
      console.error(err)
    } finally {
      setIsSearching(false)
    }
  }

  const handleInsert = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!code.trim() || !title.trim()) {
      setMessage({ type: 'error', text: '講義コードと講義名は必須入力です。' })
      return
    }

    setIsInserting(true)
    setMessage(null)

    // カンマ区切り文字列を配列に変換
    const prerequisite_codes = prereqCodesInput
      .split(',')
      .map((c) => c.trim())
      .filter(Boolean)

    const topics = topicsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)

    try {
      const response = await fetch('/api/test/integrated', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          code: code.trim(),
          title: title.trim(),
          instructor: instructor.trim() || '未設定',
          schedule: schedule.trim() || '未設定',
          credits: Number(credits) || 0,
          syllabus_text: syllabusText.trim() || null,
          prerequisite_codes,
          topics,
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to insert integrated record')
      }

      setMessage({ type: 'success', text: 'シラバス情報を PostgreSQL と Neo4j に同期登録しました！' })
      setCode('')
      setTitle('')
      setInstructor('')
      setSchedule('')
      setCredits(2)
      setSyllabusText('')
      setPrereqCodesInput('')
      setTopicsInput('')
      
      fetchRecords(searchQuery) // リストを更新
    } catch (err: any) {
      setMessage({ type: 'error', text: 'シラバス情報の登録に失敗しました。' })
    } finally {
      setIsInserting(false)
    }
  }

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    fetchRecords(searchQuery)
  }

  return (
    <div style={styles.container}>
      <h1 style={styles.title}>Postgres + Neo4j Integrated Test</h1>
      <p style={styles.subtitle}>
        授業シラバス情報（Postgres）と履修関係トポロジー（Neo4j）をマージする、GraphRAG 基礎技術の複合デモ画面です。
      </p>

      {message && (
        <div style={{
          ...styles.alert,
          backgroundColor: message.type === 'success' ? 'var(--accent-bg)' : 'rgba(239, 68, 68, 0.1)',
          borderColor: message.type === 'success' ? 'var(--accent-border)' : 'rgba(239, 68, 68, 0.4)',
          color: message.type === 'success' ? 'var(--accent)' : '#ef4444',
        }}>
          {message.text}
        </div>
      )}

      <div style={styles.grid}>
        {/* シラバス登録フォーム */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>シラバス一括登録</h2>
          <form onSubmit={handleInsert} style={styles.form}>
            <div style={styles.row}>
              <div style={{ ...styles.formGroup, flex: 1 }}>
                <label style={styles.label}>講義コード (Code) *</label>
                <input
                  type="text"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="例: CS-302"
                  style={styles.input}
                  disabled={isInserting}
                />
              </div>
              <div style={{ ...styles.formGroup, flex: 2 }}>
                <label style={styles.label}>講義名 (Title) *</label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="例: 機械学習概論"
                  style={styles.input}
                  disabled={isInserting}
                />
              </div>
            </div>

            <div style={styles.row}>
              <div style={{ ...styles.formGroup, flex: 2 }}>
                <label style={styles.label}>担当教員 (Instructor)</label>
                <input
                  type="text"
                  value={instructor}
                  onChange={(e) => setInstructor(e.target.value)}
                  placeholder="例: 山田 太郎"
                  style={styles.input}
                  disabled={isInserting}
                />
              </div>
              <div style={{ ...styles.formGroup, flex: 2 }}>
                <label style={styles.label}>曜日時限 (Schedule)</label>
                <input
                  type="text"
                  value={schedule}
                  onChange={(e) => setSchedule(e.target.value)}
                  placeholder="例: 春学期 月曜2限"
                  style={styles.input}
                  disabled={isInserting}
                />
              </div>
              <div style={{ ...styles.formGroup, flex: 1 }}>
                <label style={styles.label}>単位数 (Credits)</label>
                <input
                  type="number"
                  value={credits}
                  onChange={(e) => setCredits(Number(e.target.value))}
                  style={styles.input}
                  disabled={isInserting}
                />
              </div>
            </div>

            <div style={styles.formGroup}>
              <label style={styles.label}>シラバス本文 (Syllabus Description)</label>
              <textarea
                value={syllabusText}
                onChange={(e) => setSyllabusText(e.target.value)}
                placeholder="講義計画、概要、キーワードなどを詳しく入力してください。"
                style={styles.textarea}
                disabled={isInserting}
              />
            </div>

            <div style={styles.formGroup}>
              <label style={styles.label}>前提講義コード (Prerequisites) - カンマ区切り</label>
              <input
                type="text"
                value={prereqCodesInput}
                onChange={(e) => setPrereqCodesInput(e.target.value)}
                placeholder="例: CS-101, MATH-201 (存在しないコードは自動でプレースホルダー生成されます)"
                style={styles.input}
                disabled={isInserting}
              />
            </div>

            <div style={styles.formGroup}>
              <label style={styles.label}>カバーするトピック (Topics) - カンマ区切り</label>
              <input
                type="text"
                value={topicsInput}
                onChange={(e) => setTopicsInput(e.target.value)}
                placeholder="例: Python, 数学, 機械学習"
                style={styles.input}
                disabled={isInserting}
              />
            </div>

            <button type="submit" style={styles.button} disabled={isInserting}>
              {isInserting ? '同期登録中...' : 'Postgres ＆ Neo4j に同期保存'}
            </button>
          </form>
        </div>

        {/* 検索・GraphRAGインサイト表示 */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>シラバス検索 ＆ グラフインサイト</h2>
          <form onSubmit={handleSearch} style={styles.searchForm}>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="講義名、コード、またはシラバス内のキーワード..."
              style={styles.searchInput}
            />
            <button type="submit" style={styles.searchButton}>
              探索
            </button>
          </form>

          {isSearching ? (
            <div style={styles.loading}>探索・結合処理中...</div>
          ) : records.length === 0 ? (
            <div style={styles.noData}>シラバス情報が見つかりません。</div>
          ) : (
            <div style={styles.list}>
              {records.map((record) => (
                <div key={record.id} style={styles.listItem}>
                  <div style={styles.itemHeader}>
                    <div style={styles.itemBadgeContainer}>
                      <span style={styles.itemCode}>{record.code}</span>
                      <span style={styles.itemCredits}>{record.credits} 単位</span>
                    </div>
                    <span style={styles.itemId}>{record.id.substring(0, 8)}...</span>
                  </div>

                  <h3 style={styles.itemTitle}>{record.title}</h3>
                  
                  <div style={styles.itemMeta}>
                    <span>教員: {record.instructor}</span>
                    <span> | </span>
                    <span>時間: {record.schedule}</span>
                  </div>

                  {record.syllabus_text && (
                    <p style={styles.itemDescription}>{record.syllabus_text}</p>
                  )}

                  {/* トピックタグ */}
                  {record.topics.length > 0 && (
                    <div style={styles.topicsWrapper}>
                      {record.topics.map((topic, idx) => (
                        <span key={idx} style={styles.topicTag}>
                          #{topic}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* 履修ロードマップ (Neo4j前提関係) */}
                  {record.prerequisites.length > 0 && (
                    <div style={styles.roadmap}>
                      <h4 style={styles.sectionHeader}>履修ロードマップ (Prerequisites)</h4>
                      <div style={styles.roadmapFlow}>
                        {record.prerequisites.map((prereq, idx) => (
                          <React.Fragment key={prereq.id}>
                            <div style={styles.roadmapNode}>
                              <span style={styles.nodeCode}>{prereq.code}</span>
                              <span style={styles.nodeTitle}>{prereq.title}</span>
                            </div>
                            {idx < record.prerequisites.length - 1 && (
                              <span style={styles.arrow}>➔</span>
                            )}
                          </React.Fragment>
                        ))}
                        <span style={styles.arrow}>➔</span>
                        <div style={{ ...styles.roadmapNode, background: 'var(--accent-bg)', borderColor: 'var(--accent-border)' }}>
                          <span style={{ ...styles.nodeCode, color: 'var(--accent)' }}>{record.code}</span>
                          <span style={{ ...styles.nodeTitle, color: 'var(--text-h)' }}>{record.title}</span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* トピック共通の関連講義 (Neo4j二ホップ検索結果) */}
                  {record.related_courses.length > 0 && (
                    <div style={styles.relatedSection}>
                      <h4 style={styles.sectionHeader}>概念が共通する他の関連講義 (Graph Insights)</h4>
                      <div style={styles.relatedGrid}>
                        {record.related_courses.map((rel, idx) => (
                          <div key={idx} style={styles.relatedCard}>
                            <span style={styles.relatedCardCode}>{rel.code}</span>
                            <span style={styles.relatedCardTitle}>{rel.title}</span>
                            <span style={styles.relatedCardTopic}>トピック: {rel.topic}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const styles: { [key: string]: React.CSSProperties } = {
  container: {
    padding: '2rem',
    maxWidth: '1200px',
    margin: '0 auto',
    textAlign: 'left',
    boxSizing: 'border-box',
    width: '100%',
  },
  title: {
    fontSize: '2.5rem',
    marginBottom: '0.5rem',
    color: 'var(--text-h)',
    fontWeight: 500,
  },
  subtitle: {
    fontSize: '1rem',
    color: 'var(--text)',
    marginBottom: '2rem',
  },
  alert: {
    padding: '1rem',
    borderRadius: '8px',
    border: '1px solid',
    marginBottom: '1.5rem',
    fontSize: '0.95rem',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
    gap: '2rem',
    alignItems: 'start',
  },
  card: {
    background: 'var(--social-bg)',
    border: '1px solid var(--border)',
    borderRadius: '12px',
    padding: '2rem',
    boxShadow: 'var(--shadow)',
  },
  cardTitle: {
    fontSize: '1.5rem',
    marginBottom: '1.5rem',
    color: 'var(--text-h)',
    borderBottom: '2px solid var(--border)',
    paddingBottom: '0.5rem',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '1rem',
  },
  row: {
    display: 'flex',
    gap: '1rem',
    flexWrap: 'wrap',
  },
  formGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.4rem',
  },
  label: {
    fontSize: '0.85rem',
    fontWeight: 'bold',
    color: 'var(--text-h)',
  },
  input: {
    padding: '0.7rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--bg)',
    color: 'var(--text-h)',
    fontSize: '0.95rem',
    outline: 'none',
  },
  textarea: {
    padding: '0.7rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--bg)',
    color: 'var(--text-h)',
    fontSize: '0.95rem',
    minHeight: '80px',
    outline: 'none',
    resize: 'vertical',
  },
  button: {
    padding: '0.75rem 1.5rem',
    borderRadius: '6px',
    border: 'none',
    background: 'var(--accent)',
    color: '#fff',
    fontSize: '1rem',
    fontWeight: 'bold',
    cursor: 'pointer',
    marginTop: '0.5rem',
  },
  searchForm: {
    display: 'flex',
    gap: '0.5rem',
    marginBottom: '1.5rem',
  },
  searchInput: {
    flex: 1,
    padding: '0.75rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--bg)',
    color: 'var(--text-h)',
    fontSize: '1rem',
    outline: 'none',
  },
  searchButton: {
    padding: '0.75rem 1.2rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--code-bg)',
    color: 'var(--text-h)',
    cursor: 'pointer',
  },
  loading: {
    textAlign: 'center',
    padding: '2rem 0',
    color: 'var(--text)',
  },
  noData: {
    textAlign: 'center',
    padding: '2rem 0',
    color: 'var(--text)',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: '1.5rem',
    maxHeight: '600px',
    overflowY: 'auto',
    paddingRight: '0.5rem',
  },
  listItem: {
    padding: '1.5rem',
    borderRadius: '8px',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.8rem',
  },
  itemHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  itemBadgeContainer: {
    display: 'flex',
    gap: '0.5rem',
    alignItems: 'center',
  },
  itemCode: {
    fontSize: '0.8rem',
    fontWeight: 'bold',
    padding: '0.2rem 0.5rem',
    borderRadius: '4px',
    background: 'var(--code-bg)',
    color: 'var(--text-h)',
    fontFamily: 'var(--mono)',
  },
  itemCredits: {
    fontSize: '0.8rem',
    color: 'var(--text)',
  },
  itemId: {
    fontSize: '0.75rem',
    color: 'var(--text)',
    fontFamily: 'var(--mono)',
  },
  itemTitle: {
    fontSize: '1.4rem',
    fontWeight: 500,
    color: 'var(--text-h)',
    margin: 0,
  },
  itemMeta: {
    fontSize: '0.85rem',
    color: 'var(--text)',
  },
  itemDescription: {
    fontSize: '0.9rem',
    color: 'var(--text)',
    margin: 0,
    lineHeight: '1.5',
  },
  topicsWrapper: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '0.5rem',
  },
  topicTag: {
    fontSize: '0.8rem',
    color: 'var(--accent)',
    fontWeight: 500,
  },
  sectionHeader: {
    fontSize: '0.9rem',
    fontWeight: 'bold',
    color: 'var(--text-h)',
    margin: '0 0 0.5rem 0',
  },
  roadmap: {
    background: 'var(--code-bg)',
    padding: '1rem',
    borderRadius: '6px',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  roadmapFlow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    flexWrap: 'wrap',
  },
  roadmapNode: {
    padding: '0.4rem 0.8rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--bg)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '0.1rem',
  },
  nodeCode: {
    fontSize: '0.7rem',
    fontFamily: 'var(--mono)',
    color: 'var(--text)',
  },
  nodeTitle: {
    fontSize: '0.8rem',
    fontWeight: 500,
  },
  arrow: {
    fontSize: '1rem',
    color: 'var(--text)',
  },
  relatedSection: {
    borderTop: '1px solid var(--border)',
    paddingTop: '0.8rem',
  },
  relatedGrid: {
    display: 'flex',
    gap: '0.6rem',
    flexWrap: 'wrap',
  },
  relatedCard: {
    padding: '0.5rem 0.8rem',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--code-bg)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.1rem',
    fontSize: '0.8rem',
  },
  relatedCardCode: {
    fontFamily: 'var(--mono)',
    fontSize: '0.7rem',
    color: 'var(--text)',
  },
  relatedCardTitle: {
    fontWeight: 500,
    color: 'var(--text-h)',
  },
  relatedCardTopic: {
    fontSize: '0.65rem',
    color: 'var(--accent)',
  },
}
