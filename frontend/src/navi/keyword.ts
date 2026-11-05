/**
 * キーワード検索（旗 search=kw。api-contract.md 2.4 の D4 GET /api/courses）。
 * - 送った語は URL に入れず（UX 仕様 5.4）、タブの中（sessionStorage）だけで持つ。一覧と PC の中央の段が同じ値を読む。
 * - 開発ビルドで学科が見本のデータのときは、見本の科目を同じ規則で探す（本番の束には見本を入れない）。
 *   学科が API から来ていれば、開発ビルドでも D4 を呼ぶ。
 */
import { useSyncExternalStore } from 'react'
import type { CoursePage, CourseQuery, CourseSummary, KindCode } from './apiTypes'
import { isNumber, isRecord, isString, isStringArray, KEYS, readJson, writeJson } from './storage'
import type { Course, Department, Kind } from './types'

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

/* ---------- 検索 ---------- */

/** 検索の失敗（status は HTTP の状態。通信の失敗と形の誤りは null） */
export class SearchError extends Error {
  readonly status: number | null

  constructor(status: number | null, message: string) {
    super(message)
    this.name = 'SearchError'
    this.status = status
  }
}

/** 画面に出す失敗の文（api-contract.md 5.3 の書き分け） */
export function searchErrorText(err: unknown): string {
  if (err instanceof SearchError) {
    if (err.status === 422) return `検索の言葉が長すぎます（${MAX_WORDS}語・${MAX_QUERY_CHARS}文字まで）。`
    if (err.status === 503) return 'データベースにつながりません。'
    if (err.status === 504) return '時間内に返りませんでした。'
    if (err.status !== null) return 'サーバーのエラーで、探せませんでした。'
  }
  return 'サーバーにつながりません。'
}

export function splitWords(query: string): string[] {
  return query.trim().split(/\s+/).filter((w) => w !== '')
}

/** D4 のクエリ文字列（配列は同じ名前を繰り返す） */
export function courseQueryString(query: CourseQuery): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue
    if (Array.isArray(value)) for (const v of value) params.append(key, String(v))
    else params.set(key, String(value))
  }
  return params.toString()
}

const KIND_CODES: readonly string[] = ['required', 'elective_required', 'elective']
const TERMS: readonly string[] = ['春', '秋', '通年']

function isNullableString(v: unknown): boolean {
  return v === null || isString(v)
}

function isNullableNumber(v: unknown): boolean {
  return v === null || isNumber(v)
}

function isCourseSummary(v: unknown): v is CourseSummary {
  return (
    isRecord(v) &&
    isString(v.syllabus_id) &&
    isString(v.course_code) &&
    isString(v.name) &&
    isNullableString(v.subtitle) &&
    isNullableString(v.group_id) &&
    isNullableNumber(v.year_min) &&
    isNullableNumber(v.year_max) &&
    isNullableString(v.year_range) &&
    (v.term === null || (isString(v.term) && TERMS.includes(v.term))) &&
    isNullableString(v.term_raw) &&
    isStringArray(v.slots) &&
    isNullableString(v.slot_note) &&
    isNullableNumber(v.credits) &&
    isStringArray(v.faculties) &&
    isNullableString(v.teacher) &&
    isString(v.lead) &&
    (v.kind === null || (isString(v.kind) && KIND_CODES.includes(v.kind))) &&
    isNullableString(v.detail_url)
  )
}

function isCoursePage(v: unknown): v is CoursePage {
  return (
    isRecord(v) &&
    isNumber(v.total) &&
    isNumber(v.limit) &&
    isNumber(v.offset) &&
    Array.isArray(v.items) &&
    v.items.every(isCourseSummary) &&
    (v.kinds_status === 'available' || v.kinds_status === 'pending')
  )
}

async function fetchCoursePage(query: CourseQuery, signal: AbortSignal): Promise<CoursePage> {
  let res: Response
  try {
    res = await fetch(`/api/courses?${courseQueryString(query)}`, { signal, headers: { Accept: 'application/json' } })
  } catch (err) {
    if (signal.aborted) throw err
    throw new SearchError(null, `D4 に届きませんでした: ${String(err)}`)
  }
  if (!res.ok) throw new SearchError(res.status, `D4 が ${res.status} を返しました`)
  let body: unknown
  try {
    body = await res.json()
  } catch {
    throw new SearchError(null, 'D4 の応答が JSON ではありません')
  }
  if (!isCoursePage(body)) throw new SearchError(null, 'D4 の応答の形が約束（navi-v1）と違います')
  return body
}

/* ---------- 見本のデータ源（開発ビルドだけ） ---------- */

const KIND_TO_CODE: Record<Kind, KindCode | null> = { 必修: 'required', 選択: 'elective', 他学部: null }

function toSummary(c: Course): CourseSummary {
  return {
    syllabus_id: c.code,
    course_code: c.code,
    name: c.name,
    subtitle: null,
    group_id: c.frameId,
    year_min: c.year,
    year_max: c.year,
    year_range: c.yearRange,
    term: c.term,
    term_raw: c.term,
    slots: c.slots,
    slot_note: c.slotNote,
    credits: c.credits,
    faculties: [],
    teacher: c.teacher.status === 'known' ? c.teacher.name : null,
    lead: (c.summary !== '' ? c.summary : c.learn).slice(0, 120),
    kind: c.kind === null ? null : KIND_TO_CODE[c.kind],
    detail_url: c.syllabusUrl,
  }
}

/** D4 と同じ規則（語の AND、科目名・概要・授業でやることの部分一致、科目名が全部の語を含むものを先に、次に科目コードの順） */
function searchInDepartment(dept: Department, query: CourseQuery): CoursePage {
  const q = query.q ?? ''
  const words = splitWords(q).map((w) => w.toLowerCase())
  if (words.length > MAX_WORDS || q.length > MAX_QUERY_CHARS) throw new SearchError(422, '語が多すぎます')
  const hit = (c: Course) => {
    const text = `${c.name}\n${c.summary}\n${c.learn}`.toLowerCase()
    return words.every((w) => text.includes(w))
  }
  const nameHasAll = (c: Course) => words.length > 0 && words.every((w) => c.name.toLowerCase().includes(w))
  const items = dept.courses
    .filter(hit)
    .sort((a, b) => Number(nameHasAll(b)) - Number(nameHasAll(a)) || (a.code < b.code ? -1 : a.code > b.code ? 1 : 0))
  const limit = query.limit ?? PAGE_SIZE
  const offset = query.offset ?? 0
  return {
    total: items.length,
    limit,
    offset,
    items: items.slice(offset, offset + limit).map(toSummary),
    kinds_status: 'available',
  }
}

/** 学科の科目を探す。開発ビルドで学科が見本なら見本を、そうでなければ D4 を引く */
export async function searchCourses(dept: Department, query: CourseQuery, signal: AbortSignal): Promise<CoursePage> {
  if (import.meta.env.DEV) {
    const { FIXTURE_DEPARTMENTS } = await import('./fixtureDepartment')
    if (FIXTURE_DEPARTMENTS.some((d) => d.id === dept.id)) return searchInDepartment(dept, query)
  }
  return fetchCoursePage({ ...query, dept: dept.id }, signal)
}
