/**
 * /navi のモックで画面どうしが共有する状態の型と、その読み出し口（React の context）。
 * 状態そのものは components/navi/NaviApp.tsx が持つ。
 */
import { createContext, useContext } from 'react'
import type { ShortlistFrom } from './research'
import type { TermKey } from './timetable'
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
  /** 選んだ興味関心の順（id） */
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

/* ---------- どこから来た科目か（「なぜ」と戻り先の書き分け） ---------- */

export type Origin =
  | { kind: 'default' }
  | { kind: 'dir'; dirId: string }
  | { kind: 'course'; code: string }
  | { kind: 'group'; frameId: string }
  | { kind: 'ask'; localId: string }
  | { kind: 'tt' }
  | { kind: 'none' }

export function parseOrigin(value: string | null): Origin {
  if (value === null) return { kind: 'none' }
  if (value === 'default') return { kind: 'default' }
  // 'shortlist' は改訂前の候補の画面のリンク（時間割に置き換えた）
  if (value === 'tt' || value === 'shortlist') return { kind: 'tt' }
  const [kind, id] = value.split(':')
  if (id === undefined || id === '') return { kind: 'none' }
  if (kind === 'dir') return { kind: 'dir', dirId: id }
  if (kind === 'course') return { kind: 'course', code: id }
  if (kind === 'group') return { kind: 'group', frameId: id }
  if (kind === 'ask') return { kind: 'ask', localId: id }
  return { kind: 'none' }
}

function originParam(origin: Origin): string | null {
  switch (origin.kind) {
    case 'default':
      return 'default'
    case 'tt':
      return 'tt'
    case 'dir':
      return `dir:${origin.dirId}`
    case 'course':
      return `course:${origin.code}`
    case 'group':
      return `group:${origin.frameId}`
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

export function listHref(dirId: string): string {
  return dirId === 'default' ? '/navi' : `/navi?dir=${encodeURIComponent(dirId)}`
}

export const TIMETABLE_HREF = '/navi/timetable'

/* ---------- たどった道筋（PC のパンくず、スマホの戻る。UX 仕様 C03、E1 6章） ---------- */

export type PcTab = 'search' | 'tt'

export interface TrailEntry {
  label: string
  href: string
}

/** 履歴の state に積む。trail[0] は来た一覧、最後が今の画面 */
export interface PaneState {
  trail: TrailEntry[]
  tab: PcTab
}

export function readPaneState(state: unknown): PaneState | null {
  if (!isRecord(state)) return null
  const { trail, tab } = state
  if (tab !== 'search' && tab !== 'tt') return null
  if (!Array.isArray(trail)) return null
  const entries = trail.filter((e): e is TrailEntry => isRecord(e) && isString(e.label) && isString(e.href))
  return { trail: entries, tab }
}

/* ---------- 知らせ ---------- */

export type ToastState =
  /** 候補に入れた（2.4 秒。ボタンは置かない。E1 5章） */
  | { id: number; kind: 'added'; code: string }
  /** 時間割の［外す］で外した（5 秒、［元に戻す］つき。E1 10章） */
  | { id: number; kind: 'removed'; code: string; index: number }

/* ---------- 共有する状態 ---------- */

export interface NaviContextValue {
  dept: Department
  /** 想定の学年（リンクの t=。既定は1年。UX 仕様 1.4） */
  assumedYear: number
  /** 想定の時点の学期（入学直後なので春） */
  assumedTerm: TermKey
  isPc: boolean
  reducedMotion: boolean

  shortlist: string[]
  isKept: (code: string) => boolean
  /** ＋と［候補に入れる］。入れると知らせを出し、もう一度押すと外す。from は研究のログの「どこから」 */
  toggleKeep: (code: string, from?: ShortlistFrom) => void
  /** 時間割の［外す］。［元に戻す］つきの知らせを出す */
  removeKeep: (code: string) => void
  undoRemove: (toast: ToastState) => void

  /** いま見ている時間割の学期（タブの単位、W4、PC の右の段。E1 の「この学期」） */
  focusTerm: TermKey
  setFocusTerm: (t: TermKey) => void

  toast: ToastState | null
  clearToast: (id: number) => void

  /** 読み上げ用の領域に1回だけ言う */
  announcement: string
  announce: (text: string) => void

  ask: AskSession | null
  askDraft: string
  setAskDraft: (text: string) => void
  /** 欄に送っていない文が入っているか（空でなく、最後に送った文とも違う）。入っているあいだは興味関心のチップを隠す */
  askDraftUnsent: boolean
  /** 送れたら端末内の番号、前の質問を待っているときは null */
  sendAsk: (interest: string, withGuardrail: boolean) => string | null
  cancelAsk: () => void
  closeAsk: () => void
  markAskSeen: () => void

  study: StudyRecord | null
  track: (event: StudyEvent) => void
  startStudy: (surveyId: string, mode: 'fresh' | 'continue') => void
  endStudy: () => void

  /** 最後に選んだ興味関心（PC の左の段と、詳細から戻ったときの一覧に使う） */
  lastDir: string
  setLastDir: (dirId: string) => void
}

export const NaviContext = createContext<NaviContextValue | null>(null)

export function useNavi(): NaviContextValue {
  const value = useContext(NaviContext)
  if (value === null) throw new Error('useNavi は NaviApp の中で使ってください')
  return value
}
