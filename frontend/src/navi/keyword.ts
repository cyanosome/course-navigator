/**
 * キーワード検索（旗 search=kw）の送った語と失敗の文。検索そのものはデータ源の searchCourses
 * （dataSource.ts。D4 GET /api/courses、開発ビルドで VITE_NAVI_DATA=fixture なら見本）で引く。
 * - 送った語は URL に入れず（UX 仕様 5.4）、タブの中（sessionStorage）だけで持つ。一覧と PC の中央の段が同じ値を読む。
 */
import { useSyncExternalStore } from 'react'
import { ApiError, apiErrorMessage } from './api'
import type { CourseSummary } from './apiTypes'
import { isRecord, isString, KEYS, readJson, writeJson } from './storage'

/** 1回に読む件数（D4 の既定と同じ） */
export const PAGE_SIZE = 20
/** D4 の上限（語は5つまで、全体 100 文字まで） */
const MAX_WORDS = 5
const MAX_QUERY_CHARS = 100

/* ---------- 送った語（タブの中だけ） ---------- */

const listeners = new Set<() => void>()

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange)
  return () => listeners.delete(onChange)
}

function readQuery(): string {
  return readJson('session', KEYS.keyword, isString) ?? ''
}

/** 語を送った回数（同じ語をもう一度送っても探し直すため）と、送った直後の結果がまだ記録されていないか */
let submissions = 0
let pendingSubmission = false

/** 空にすると検索をやめる（一覧はおすすめ・興味関心・全科目に戻る） */
export function setKeywordQuery(query: string): void {
  writeJson('session', KEYS.keyword, query === '' ? null : query)
  if (query !== '') {
    submissions += 1
    pendingSubmission = true
  }
  for (const l of listeners) l()
}

export function useKeywordQuery(): [string, (query: string) => void] {
  return [useSyncExternalStore(subscribe, readQuery), setKeywordQuery]
}

export function useKeywordSubmissions(): number {
  return useSyncExternalStore(subscribe, () => submissions)
}

/**
 * 送った直後の結果か（search_query の trigger を user にする）。一度だけ真を返す。
 * 詳細から戻って一覧を作り直したときの読み直しは、送った検索に数えない（trigger は redisplay）。
 */
export function takeKeywordSubmission(): boolean {
  const was = pendingSubmission
  pendingSubmission = false
  return was
}

/* ---------- 科目名の控え（候補の一覧で、学科の系統図に無い科目の名前を出すため） ---------- */

function isNameMap(v: unknown): v is Record<string, string> {
  return isRecord(v) && Object.values(v).every(isString)
}

export function rememberCourseNames(items: CourseSummary[]): void {
  const names = readJson('session', KEYS.courseNames, isNameMap) ?? {}
  for (const item of items) names[item.syllabus_id] = item.name
  writeJson('session', KEYS.courseNames, names)
}

export function rememberedCourseName(syllabusId: string): string | undefined {
  return readJson('session', KEYS.courseNames, isNameMap)?.[syllabusId]
}

/* ---------- 検索の失敗 ---------- */

/** 画面に出す失敗の文。語の上限（422）だけ検索の言葉で書き、ほかはデータ源の書き分け（api.ts）に任せる */
export function searchErrorText(err: unknown): string {
  if (err instanceof ApiError && err.status === 422) return `検索の言葉が長すぎます（${MAX_WORDS}語・${MAX_QUERY_CHARS}文字まで）。`
  return apiErrorMessage(err)
}
