import type { CSSProperties, FormEvent, ReactNode } from 'react'
import { getAlertStyle } from '../styles/testPageStyles'
import type { PageMessage } from '../hooks/useTestPageForm'

interface TestPageLayoutProps {
  /** テストページ用スタイル一式（testPageStyles、またはそれをスプレッドして一部上書きしたもの） */
  styles: Record<string, CSSProperties>
  title: string
  subtitle: string
  message: PageMessage

  formCardTitle: string
  onInsert: (e: FormEvent) => void
  isInserting: boolean
  insertButtonLabel: string
  /** フォーム内のフィールド群（画面ごとに異なる差分部分） */
  formChildren: ReactNode

  searchCardTitle: string
  searchQuery: string
  onSearchQueryChange: (value: string) => void
  onSearch: (e: FormEvent) => void
  searchPlaceholder: string
  searchButtonLabel: string

  isSearching: boolean
  loadingText: string
  noDataText: string
  hasRecords: boolean
  /** 検索結果一覧の中身（画面ごとに異なる表示ロジック） */
  children: ReactNode
}

/**
 * PostgresTest / Neo4jTest / IntegratedTest で共通していたページ全体の骨格
 * （タイトル・メッセージ表示・登録フォームカード・検索/一覧カード）を担うレイアウト。
 * フィールド定義や一覧アイテムの表示ロジックは呼び出し側から children として渡す。
 */
export default function TestPageLayout({
  styles,
  title,
  subtitle,
  message,
  formCardTitle,
  onInsert,
  isInserting,
  insertButtonLabel,
  formChildren,
  searchCardTitle,
  searchQuery,
  onSearchQueryChange,
  onSearch,
  searchPlaceholder,
  searchButtonLabel,
  isSearching,
  loadingText,
  noDataText,
  hasRecords,
  children,
}: TestPageLayoutProps) {
  return (
    <div style={styles.container}>
      <h1 style={styles.title}>{title}</h1>
      <p style={styles.subtitle}>{subtitle}</p>

      {message && <div style={getAlertStyle(styles.alert, message.type)}>{message.text}</div>}

      <div style={styles.grid}>
        {/* データ入力フォーム */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>{formCardTitle}</h2>
          <form onSubmit={onInsert} style={styles.form}>
            {formChildren}
            <button type="submit" style={styles.button} disabled={isInserting}>
              {insertButtonLabel}
            </button>
          </form>
        </div>

        {/* 検索・結果表示エリア */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>{searchCardTitle}</h2>
          <form onSubmit={onSearch} style={styles.searchForm}>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchQueryChange(e.target.value)}
              placeholder={searchPlaceholder}
              style={styles.searchInput}
            />
            <button type="submit" style={styles.searchButton}>
              {searchButtonLabel}
            </button>
          </form>

          {isSearching ? (
            <div style={styles.loading}>{loadingText}</div>
          ) : !hasRecords ? (
            <div style={styles.noData}>{noDataText}</div>
          ) : (
            <div style={styles.list}>{children}</div>
          )}
        </div>
      </div>
    </div>
  )
}
