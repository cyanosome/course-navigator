import { useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { testPageStyles } from '../styles/testPageStyles'
import { useTestPageForm } from '../hooks/useTestPageForm'
import TestPageLayout from './TestPageLayout'

interface CourseRecord {
  id: string
  title: string
  description: string | null
  created_at: string
}

export default function PostgresTest() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')

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
  } = useTestPageForm<CourseRecord>('/api/test/postgres')

  const handleInsert = async (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim()) {
      setMessage({ type: 'error', text: 'タイトルを入力してください。' })
      return
    }

    await submitInsert(async () => {
      const response = await fetch('/api/test/postgres', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ title, description }),
      })

      if (!response.ok) {
        throw new Error('Failed to insert record')
      }

      setMessage({ type: 'success', text: 'データを正常に保存しました！' })
      setTitle('')
      setDescription('')
      fetchRecords(searchQuery) // リストを更新
    }, 'データの保存に失敗しました。')
  }

  return (
    <TestPageLayout
      styles={styles}
      title="PostgreSQL Communication Test"
      subtitle="Frontend (React) ⇔ Backend (FastAPI) ⇔ PostgreSQL の疎通テスト用ページです。"
      message={message}
      formCardTitle="データ登録"
      onInsert={handleInsert}
      isInserting={isInserting}
      insertButtonLabel={isInserting ? '保存中...' : 'PostgreSQL に保存'}
      formChildren={
        <>
          <div style={styles.formGroup}>
            <label style={styles.label}>講義名 (Title)</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例: アルゴリズムとデータ構造"
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
        </>
      }
      searchCardTitle="データ検索・一覧"
      searchQuery={searchQuery}
      onSearchQueryChange={setSearchQuery}
      onSearch={handleSearch}
      searchPlaceholder="検索する講義名を入力..."
      searchButtonLabel="検索"
      isSearching={isSearching}
      loadingText="検索中..."
      noDataText="データが見つかりません。"
      hasRecords={records.length > 0}
    >
      {records.map((record) => (
        <div key={record.id} style={styles.listItem}>
          <div style={styles.itemHeader}>
            <span style={styles.itemTitle}>{record.title}</span>
            <span style={styles.itemId}>{record.id.substring(0, 8)}...</span>
          </div>
          {record.description && <p style={styles.itemDescription}>{record.description}</p>}
          <span style={styles.itemDate}>{new Date(record.created_at).toLocaleString('ja-JP')}</span>
        </div>
      ))}
    </TestPageLayout>
  )
}

const styles: Record<string, CSSProperties> = {
  ...testPageStyles,
  itemDate: {
    fontSize: '0.75rem',
    color: 'var(--text)',
    alignSelf: 'flex-end',
  },
}
