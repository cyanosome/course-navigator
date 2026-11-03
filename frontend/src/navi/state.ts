/**
 * /navi のモックで画面どうしが共有する状態の型と、その読み出し口（React の context）。
 * 状態そのものは components/navi/NaviApp.tsx が持つ。
 */
import { createContext, useContext } from 'react'
import type { Department, McpAgentRunResult } from './types'
import { isNumber, isRecord, isString, isStringArray } from './storage'

/* ---------- 自由記述（W5） ---------- */

export type AskStatus = 'waiting' | 'done' | 'error' | 'timeout' | 'empty'

export interface AskSession {
  /** 端末の中で付けた番号（URL /navi/ask/<番号>。質問の文は URL に入れない。UX 仕様 C06） */
  localId: string
  /** 学生が書いた文（画面に出す。送る文は composeQuestion で別に作る） */
  interest: string
  /** 範囲外の言葉のまま送ったとき、送る文にガードレールを足した（UX 仕様 C10） */
  guardrail: boolean
  status: AskStatus
  startedAt: number
  finishedAt: number | null
  result: McpAgentRunResult | null
  /** 届いた回答を一覧で見たか（見るまで「回答が届きました [見る]」を出す。UX 仕様 C08） */
  seen: boolean
}

const ASK_STATUSES: readonly string[] = ['waiting', 'done', 'error', 'timeout', 'empty']

export function isAskSession(v: unknown): v is AskSession {
  return (
    isRecord(v) &&
    isString(v.localId) &&
    isString(v.interest) &&
    typeof v.guardrail === 'boolean' &&
    isString(v.status) &&
    ASK_STATUSES.includes(v.status) &&
    isNumber(v.startedAt) &&
    (v.finishedAt === null || isNumber(v.finishedAt)) &&
    (v.result === null || isRecord(v.result)) &&
    typeof v.seen === 'boolean'
  )
}

/** 回答を待つ上限（requirements.md R1-2 の提案 180 秒。UX 仕様 W6-3） */
export const ASK_TIMEOUT_MS = 180_000

/* ---------- 調査モード（W9・W10。UX 仕様 8.1・8.7） ---------- */

export interface StudyRecord {
  surveyId: string
  sessionId: string
  startedAt: number
  endedAt: number | null
  /** 詳細を開いた科目（コード） */
  detailOpened: string[]
  /** 理由（詳細）を見てから候補に入れた科目（コード） */
  keptAfterReason: string[]
  originalOpened: number
  traversed: number
  asked: number
  /** 選んだ方向の順（id） */
  dirs: string[]
}

export function isStudyRecord(v: unknown): v is StudyRecord {
  return (
    isRecord(v) &&
    isString(v.surveyId) &&
    isString(v.sessionId) &&
    isNumber(v.startedAt) &&
    (v.endedAt === null || isNumber(v.endedAt)) &&
    isStringArray(v.detailOpened) &&
    isStringArray(v.keptAfterReason) &&
    isNumber(v.originalOpened) &&
    isNumber(v.traversed) &&
    isNumber(v.asked) &&
    isStringArray(v.dirs)
  )
}

export type StudyEvent =
  | { type: 'detail'; code: string }
  | { type: 'original' }
  | { type: 'traverse' }
  | { type: 'ask' }
  | { type: 'dir'; dirId: string }

/* ---------- どこから来た提案か（「なぜ」の書き分け。UX 仕様 7.2） ---------- */

export type Origin =
  | { kind: 'default' }
  | { kind: 'dir'; dirId: string }
  | { kind: 'course'; code: string }
  | { kind: 'ask'; localId: string }
  | { kind: 'shortlist' }
  | { kind: 'none' }

export function parseOrigin(value: string | null): Origin {
  if (value === null) return { kind: 'none' }
  if (value === 'default') return { kind: 'default' }
  if (value === 'shortlist') return { kind: 'shortlist' }
  const [kind, id] = value.split(':')
  if (id === undefined || id === '') return { kind: 'none' }
  if (kind === 'dir') return { kind: 'dir', dirId: id }
  if (kind === 'course') return { kind: 'course', code: id }
  if (kind === 'ask') return { kind: 'ask', localId: id }
  return { kind: 'none' }
}

function originParam(origin: Origin): string | null {
  switch (origin.kind) {
    case 'default':
      return 'default'
    case 'shortlist':
      return 'shortlist'
    case 'dir':
      return `dir:${origin.dirId}`
    case 'course':
      return `course:${origin.code}`
    case 'ask':
      return `ask:${origin.localId}`
    case 'none':
      return null
  }
}

function withFrom(path: string, origin: Origin): string {
  const from = originParam(origin)
  return from === null ? path : `${path}?from=${encodeURIComponent(from)}`
}

export function courseHref(code: string, origin: Origin): string {
  return withFrom(`/navi/course/${encodeURIComponent(code)}`, origin)
}

export function groupHref(frameId: string, origin: Origin): string {
  return withFrom(`/navi/group/${encodeURIComponent(frameId)}`, origin)
}

/* ---------- PC の右ペインの道筋（UX 仕様 C03） ---------- */

export type PcTab = 'search' | 'shortlist'

export interface TrailEntry {
  label: string
  href: string
}

/** 履歴の state に積む。ブラウザの戻るで右ペインが1段戻る */
export interface PaneState {
  trail: TrailEntry[]
  tab: PcTab
}

export function readPaneState(state: unknown): PaneState | null {
  if (!isRecord(state)) return null
  const { trail, tab } = state
  if (tab !== 'search' && tab !== 'shortlist') return null
  if (!Array.isArray(trail)) return null
  const entries = trail.filter(
    (e): e is TrailEntry => isRecord(e) && isString(e.label) && isString(e.href),
  )
  return { trail: entries, tab }
}

/* ---------- 共有する状態 ---------- */

export interface ToastState {
  id: number
  text: string
  undo: () => void
}

export interface NaviContextValue {
  dept: Department
  /** 想定の学年（リンクの t=。既定は1年。UX 仕様 1.4） */
  assumedYear: number
  isPc: boolean

  shortlist: string[]
  isKept: (code: string) => boolean
  toggleKeep: (code: string) => void
  removeKeep: (code: string) => void

  toast: ToastState | null
  dismissToast: () => void

  ask: AskSession | null
  askDraft: string
  setAskDraft: (text: string) => void
  /** 送れたら端末内の番号、前の質問を待っているときは null */
  sendAsk: (interest: string, withGuardrail: boolean) => string | null
  cancelAsk: () => void
  closeAsk: () => void
  markAskSeen: () => void

  study: StudyRecord | null
  track: (event: StudyEvent) => void
  startStudy: (surveyId: string, mode: 'fresh' | 'continue') => void
  endStudy: () => void

  /** 最後に選んだ方向（PC の左ペインと、詳細から戻ったときの一覧に使う） */
  lastDir: string
  setLastDir: (dirId: string) => void
}

export const NaviContext = createContext<NaviContextValue | null>(null)

export function useNavi(): NaviContextValue {
  const value = useContext(NaviContext)
  if (value === null) throw new Error('useNavi は NaviApp の中で使ってください')
  return value
}
