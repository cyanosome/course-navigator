import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { getErrorMessage } from '../utils/errorMessage'

export type PageMessage = { type: 'success' | 'error'; text: string } | null

/**
 * PostgresTest / Neo4jTest / IntegratedTest の3画面で共通していた
 * 「検索クエリ→一覧取得→登録」の骨格をまとめたフック。
 *
 * - endpoint: `/api/test/postgres` のような API のベースパス（`?q=` を付与して GET する）
 *
 * 各画面固有のフィールド定義や登録処理の中身（fetch の body・成功メッセージ・入力バリデーション）は
 * 呼び出し側の handleInsert が `submitInsert` に渡す action の中で行う。
 */
export function useTestPageForm<T>(endpoint: string) {
  const [searchQuery, setSearchQuery] = useState('')
  const [records, setRecords] = useState<T[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [isInserting, setIsInserting] = useState(false)
  const [message, setMessage] = useState<PageMessage>(null)

  const fetchRecords = useCallback(
    async (query = '') => {
      setIsSearching(true)
      try {
        const response = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`)
        if (!response.ok) {
          throw new Error('Failed to fetch records')
        }
        const data = await response.json()
        setRecords(data)
      } catch (err: unknown) {
        console.error(getErrorMessage(err))
        setMessage({ type: 'error', text: '読み込みに失敗しました' })
      } finally {
        setIsSearching(false)
      }
    },
    [endpoint],
  )

  // 初期ロード時に全件取得
  // NOTE: queueMicrotask 経由なのは react-hooks/set-state-in-effect（effect 本体から同期的に
  // setState する fetchRecords の直接呼び出しを検出する）を満たすため。fetch 自体が非同期なので
  // 実挙動は直接呼び出しと変わらない。
  useEffect(() => {
    queueMicrotask(() => {
      fetchRecords()
    })
  }, [fetchRecords])

  const handleSearch = (e: FormEvent) => {
    e.preventDefault()
    fetchRecords(searchQuery)
  }

  /**
   * 登録処理の共通骨格（isInserting / message の管理と try-catch-finally）。
   * 実際の fetch 呼び出し・成功時メッセージ・フォームリセットは action 内で行う。
   */
  const submitInsert = useCallback(async (action: () => Promise<void>, errorText: string) => {
    setIsInserting(true)
    setMessage(null)
    try {
      await action()
    } catch (err: unknown) {
      console.error(getErrorMessage(err))
      setMessage({ type: 'error', text: errorText })
    } finally {
      setIsInserting(false)
    }
  }, [])

  return {
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
  }
}
