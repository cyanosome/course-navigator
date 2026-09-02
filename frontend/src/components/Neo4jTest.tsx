import { useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { testPageStyles } from '../styles/testPageStyles'
import { useTestPageForm } from '../hooks/useTestPageForm'
import TestPageLayout from './TestPageLayout'

interface GraphRecord {
  id: string
  title: string
  description: string | null
  prerequisites: string[]
}

export default function Neo4jTest() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [prerequisiteTitle, setPrerequisiteTitle] = useState('')

  const {
    searchQuery,
    setSearchQuery,
    records,
    isSearching,
    isInserting,
    message,
    setMessage,
    fetchRecords,
    handleSearch,
    submitInsert,
  } = useTestPageForm<GraphRecord>('/api/test/neo4j')

  const handleInsert = async (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim()) {
      setMessage({ type: 'error', text: '講義名を入力してください。' })
      return
    }

    await submitInsert(async () => {
      const response = await fetch('/api/test/neo4j', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          title,
          description,
          prerequisite_title: prerequisiteTitle.trim() || null,
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to insert record')
      }

      setMessage({ type: 'success', text: 'Neo4j にノードおよびリレーションを正常に保存しました！' })
      setTitle('')
      setDescription('')
      setPrerequisiteTitle('')
      fetchRecords(searchQuery) // リストを更新
    }, 'データの保存に失敗しました。')
  }

  return (
    <TestPageLayout
      styles={styles}
      title="test2-2: Neo4j Communication Test"
      subtitle="Frontend (React) ⇔ Backend (FastAPI) ⇔ Neo4j (GraphDB) の疎通テスト用ページです。"
      message={message}
      formCardTitle="グラフデータ登録"
      onInsert={handleInsert}
      isInserting={isInserting}
      insertButtonLabel={isInserting ? '保存中...' : 'Neo4j に保存'}
      formChildren={
        <>
          <div style={styles.formGroup}>
            <label style={styles.label}>講義名 (Title)</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例: データ構造とアルゴリズム"
              style={styles.input}
              disabled={isInserting}
            />
          </div>
          <div style={styles.formGroup}>
            <label style={styles.label}>概要 (Description)</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="講義の内容や詳細を入力してください"
              style={styles.textarea}
              disabled={isInserting}
            />
          </div>
          <div style={styles.formGroup}>
            <label style={styles.label}>前提講義名 (Prerequisite Course Title) - 任意</label>
            <input
              type="text"
              value={prerequisiteTitle}
              onChange={(e) => setPrerequisiteTitle(e.target.value)}
              placeholder="例: プログラミング基礎 (関係性を接続)"
              style={styles.input}
              disabled={isInserting}
            />
            <span style={styles.inputHint}>指定された場合、自動的に :REQUIRES_PREREQUISITE 関係が作成されます。</span>
          </div>
        </>
      }
      searchCardTitle="グラフ探索・一覧"
      searchQuery={searchQuery}
      onSearchQueryChange={setSearchQuery}
      onSearch={handleSearch}
      searchPlaceholder="検索する講義名やキーワード..."
      searchButtonLabel="検索"
      isSearching={isSearching}
      loadingText="探索中..."
      noDataText="ノードが見つかりません。"
      hasRecords={records.length > 0}
    >
      {records.map((record) => (
        <div key={record.id} style={styles.listItem}>
          <div style={styles.itemHeader}>
            <span style={styles.itemTitle}>{record.title}</span>
            <span style={styles.itemId}>{record.id.substring(0, 8)}...</span>
          </div>
          {record.description && <p style={styles.itemDescription}>{record.description}</p>}
          {record.prerequisites.length > 0 && (
            <div style={styles.relations}>
              <span style={styles.relationLabel}>前提条件:</span>
              <div style={styles.tagsContainer}>
                {record.prerequisites.filter(Boolean).map((pTitle, idx) => (
                  <span key={idx} style={styles.tag}>
                    {pTitle}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </TestPageLayout>
  )
}

const styles: Record<string, CSSProperties> = {
  ...testPageStyles,
  inputHint: {
    fontSize: '0.75rem',
    color: 'var(--text)',
  },
  relations: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginTop: '0.25rem',
  },
  relationLabel: {
    fontSize: '0.8rem',
    fontWeight: 'bold',
    color: 'var(--text-h)',
  },
  tagsContainer: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '0.4rem',
  },
  tag: {
    fontSize: '0.75rem',
    padding: '0.2rem 0.6rem',
    borderRadius: '12px',
    background: 'var(--accent-bg)',
    border: '1px solid var(--accent-border)',
    color: 'var(--accent)',
    fontWeight: 500,
  },
}
