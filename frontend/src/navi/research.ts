/**
 * 研究のログ（ab-variants.md 7 章、api-contract.md 3 章）と、調査のセッションの状態。
 * - 画面は useResearchLog().log(種類, payload) を呼ぶだけにする。調査のセッションが無いときは何も記録しない
 *   （トークンの無いアクセスは記録しない。計画 4.2）。
 * - イベントは seq を1から振って列に積み、2 秒か 10 件で R6 にまとめて送る。送れなければ列に残して送り直す
 *   （同じ event_id の2回目はサーバーが捨てる）。ページを隠す・閉じるときは sendBeacon で送る（届いたか分からないので、
 *   列からは消さず、次に送れたときに重ねて送る）。列と seq はセッションごとに sessionStorage に持つ。
 * - 調査のセッションの状態（同意・ブロック・課題の段階）もここに持つ。段階の進め方は studyFlow.ts。
 * - 調査でないときの旗は R8（開発ビルドで ?variant=V02 のように指定したときは R9）から取る。
 */
import { createContext, useContext, useEffect, useState, useSyncExternalStore } from 'react'
import { CLIENT_EVENT_TYPES, CONTRACT_VERSION } from './apiTypes'
import type {
  BlockPlan,
  BlockStartOut,
  ClientEvent,
  ClientEventType,
  ConsentIn,
  EventBatchOut,
  EventPayload,
  SessionOut,
  VariantOut,
} from './apiTypes'
import { PC_QUERY } from './hooks'
import { isNumber, isRecord, isString, isStringArray, readJson, RESEARCH_KEYS, setStudyStorage, writeJson } from './storage'
import { DEFAULT_VARIANT, flagsDigest, isVariantFlags, toVariantState } from './variant'
import type { VariantFlags, VariantState } from './variant'

/** result_click の「どの一覧か」（plan は診断のプラン、refine はプランの微修正の AI の回答） */
export type ListSource = 'search' | 'recommend' | 'interest' | 'ask' | 'group' | 'similar' | 'plan' | 'refine'

/** shortlist_add・shortlist_remove の「どこから」 */
export type ShortlistFrom = ListSource | 'detail' | 'timetable' | 'undo' | 'unknown'

export interface ResearchLog {
  /** 調査のセッション中か */
  active: boolean
  /** イベントを1つ記録する。記録したら event_id を返し、セッションが無ければ何もせず null */
  log: (type: ClientEventType, payload?: EventPayload) => string | null
}

/** 調査でないときの口（何も記録しない） */
export const NOOP_RESEARCH_LOG: ResearchLog = {
  active: false,
  log: () => null,
}

export const ResearchLogContext = createContext<ResearchLog>(NOOP_RESEARCH_LOG)

export function useResearchLog(): ResearchLog {
  return useContext(ResearchLogContext)
}

/**
 * 詳細を開いてから閉じるまでを研究のログに残す（syllabus_open・syllabus_close。表示 ms は閉じたときに）。
 * from はどこから開いたか（plan・status・search・refine など。事前登録 study1 の 6.2）
 */
export function useSyllabusViewLog(syllabusId: string, from: string) {
  const { log } = useResearchLog()
  useEffect(() => {
    const opened = performance.now()
    log('syllabus_open', { syllabus_id: syllabusId, from })
    return () => {
      log('syllabus_close', { syllabus_id: syllabusId, shown_ms: Math.round(performance.now() - opened) })
    }
  }, [from, log, syllabusId])
}

/* ---------- 調査のセッションの状態 ---------- */

/** 調査の段階。task のあいだだけ画面（/navi）を開き、ほかは調査の入口（/navi/s/<トークン>）に出す */
export type StudyPhase =
  | { kind: 'consent' }
  | { kind: 'declined' }
  | { kind: 'blockIntro'; block: number }
  | { kind: 'taskIntro'; block: number; taskIndex: number }
  | { kind: 'task'; block: number; taskIndex: number }
  | { kind: 'taskQuestions'; block: number; taskIndex: number }
  | { kind: 'blockQuestions'; block: number }
  /** R5 を待つ（失敗したら入口で送り直す） */
  | { kind: 'blockEnd'; block: number }
  | { kind: 'finalQuestions' }
  /** 残りのイベントと R7 を待つ */
  | { kind: 'finishing' }
  | { kind: 'done' }

export type TransportKind = 'http' | 'dev'

export interface StudyState {
  session: SessionOut
  /** 調査の入口の URL（/navi/s/<トークン>） */
  gatePath: string
  transport: TransportKind
  phase: StudyPhase
  /** いまのブロックの計画と旗（R4 の応答）。ブロックの外は null */
  plan: BlockPlan | null
  variant: VariantOut | null
  /** variant_applied を送ったブロック */
  appliedBlock: number | null
}

const PHASE_KINDS: readonly string[] = [
  'consent',
  'declined',
  'blockIntro',
  'taskIntro',
  'task',
  'taskQuestions',
  'blockQuestions',
  'blockEnd',
  'finalQuestions',
  'finishing',
  'done',
]

function isStudyPhase(v: unknown): v is StudyPhase {
  if (!isRecord(v) || !isString(v.kind) || !PHASE_KINDS.includes(v.kind)) return false
  if ('block' in v && !isNumber(v.block)) return false
  if ('taskIndex' in v && !isNumber(v.taskIndex)) return false
  return true
}

export function isBlockPlan(v: unknown): v is BlockPlan {
  return isRecord(v) && isNumber(v.block) && isString(v.condition_id) && isString(v.task_set_id) && isStringArray(v.task_ids)
}

export function isVariantOut(v: unknown): v is VariantOut {
  return (
    isRecord(v) &&
    isString(v.variant_id) &&
    (v.condition_id === null || isString(v.condition_id)) &&
    isVariantFlags(v.flags) &&
    isString(v.flags_version)
  )
}

export function isSessionOut(v: unknown): v is SessionOut {
  return (
    isRecord(v) &&
    isString(v.session_id) &&
    isString(v.pid) &&
    isString(v.study_id) &&
    isString(v.sequence_id) &&
    (v.mode === 'onsite' || v.mode === 'remote') &&
    isString(v.department_id) &&
    isString(v.consent_version) &&
    typeof v.consent_recorded === 'boolean' &&
    Array.isArray(v.blocks) &&
    v.blocks.every(isBlockPlan) &&
    (v.current_block === null || isNumber(v.current_block)) &&
    (v.variant === null || isVariantOut(v.variant)) &&
    isString(v.backend_version) &&
    Array.isArray(v.completed_blocks) &&
    v.completed_blocks.every(isNumber) &&
    isNumber(v.last_seq)
  )
}

function isStudyState(v: unknown): v is StudyState {
  return (
    isRecord(v) &&
    isSessionOut(v.session) &&
    isString(v.gatePath) &&
    (v.transport === 'http' || v.transport === 'dev') &&
    isStudyPhase(v.phase) &&
    (v.plan === null || isBlockPlan(v.plan)) &&
    (v.variant === null || isVariantOut(v.variant)) &&
    (v.appliedBlock === null || isNumber(v.appliedBlock))
  )
}

const studyListeners = new Set<() => void>()
/** 読んだ値の写し（useSyncExternalStore は同じ値なら同じ参照を返す必要がある） */
let studyCache: StudyState | null | undefined

export function getStudy(): StudyState | null {
  if (studyCache === undefined) studyCache = readJson('session', RESEARCH_KEYS.study, isStudyState)
  return studyCache
}

export function setStudy(next: StudyState | null): void {
  studyCache = next
  writeJson('session', RESEARCH_KEYS.study, next)
  setStudyStorage(next !== null)
  if (next !== null) installPageListeners()
  for (const l of studyListeners) l()
}

function subscribeStudy(onChange: () => void): () => void {
  studyListeners.add(onChange)
  return () => studyListeners.delete(onChange)
}

export function useStudy(): StudyState | null {
  return useSyncExternalStore(subscribeStudy, getStudy)
}

/** 段階が課題か、課題の直後の質問票なら、その課題の ID */
export function currentTaskId(study: StudyState): string | null {
  const { phase, plan } = study
  if (plan === null || (phase.kind !== 'task' && phase.kind !== 'taskQuestions')) return null
  return plan.task_ids[phase.taskIndex] ?? null
}

/** 画面（/navi）を開いてよい段階か */
export function isTaskRunning(study: StudyState): boolean {
  return study.phase.kind === 'task'
}

/* ---------- サーバーとのやりとり ---------- */

/** 研究の API の失敗（status は HTTP の状態。通信の失敗と応答の形の誤りは null） */
export class StudyError extends Error {
  readonly status: number | null

  constructor(status: number | null, message: string) {
    super(message)
    this.name = 'StudyError'
    this.status = status
  }
}

export interface ResearchTransport {
  startSession(token: string): Promise<SessionOut>
  currentSession(sessionId: string): Promise<SessionOut>
  recordConsent(sessionId: string, input: ConsentIn): Promise<void>
  startBlock(sessionId: string, block: number): Promise<BlockStartOut>
  endBlock(sessionId: string, block: number): Promise<void>
  sendEvents(sessionId: string, events: ClientEvent[]): Promise<EventBatchOut>
  /** 閉じる直前の送信。送る手続きに乗ったかだけを返す */
  beaconEvents(events: ClientEvent[]): boolean
  endSession(sessionId: string): Promise<void>
}

/** ビルド時に埋めたコミット（VITE_APP_COMMIT）。無ければ dev */
export const FRONTEND_VERSION: string = (() => {
  const v: unknown = import.meta.env.VITE_APP_COMMIT
  return isString(v) && v !== '' ? v : 'dev'
})()

const EVENTS_PATH = '/api/research/events'

async function callApi(path: string, method: 'GET' | 'POST', sessionId: string | null, body?: unknown): Promise<unknown> {
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Navi-Frontend': FRONTEND_VERSION }
  if (sessionId !== null) headers['X-Navi-Session'] = sessionId
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (err) {
    throw new StudyError(null, `${path} に届きませんでした: ${String(err)}`)
  }
  if (!res.ok) {
    let detail = ''
    try {
      const data: unknown = await res.json()
      if (isRecord(data) && isString(data.detail)) detail = data.detail
    } catch {
      // 本文が JSON でなければ状態だけで書き分ける
    }
    throw new StudyError(res.status, `${path} が ${res.status} を返しました ${detail}`.trim())
  }
  const contract = res.headers.get('X-Navi-Contract')
  if (contract !== null && contract !== CONTRACT_VERSION) console.warn(`${path} の約束の版が ${contract} です（画面は ${CONTRACT_VERSION}）`)
  if (res.status === 204) return null
  try {
    return (await res.json()) as unknown
  } catch {
    throw new StudyError(null, `${path} の応答が JSON ではありません`)
  }
}

function expect<T>(value: unknown, guard: (v: unknown) => v is T, what: string): T {
  if (guard(value)) return value
  throw new StudyError(null, `${what} の形が約束（navi-v1）と違います`)
}

function isBlockStartOut(v: unknown): v is BlockStartOut {
  return isRecord(v) && isBlockPlan(v.plan) && isVariantOut(v.variant)
}

function isEventBatchOut(v: unknown): v is EventBatchOut {
  return isRecord(v) && isNumber(v.accepted) && isNumber(v.duplicates) && isNumber(v.last_seq) && isStringArray(v.warnings)
}

const HTTP_TRANSPORT: ResearchTransport = {
  async startSession(token) {
    return expect(await callApi('/api/research/sessions', 'POST', null, { token }), isSessionOut, 'R1 の応答')
  },
  async currentSession(sessionId) {
    return expect(await callApi('/api/research/sessions/current', 'GET', sessionId), isSessionOut, 'R2 の応答')
  },
  async recordConsent(sessionId, input) {
    await callApi('/api/research/consent', 'POST', sessionId, input)
  },
  async startBlock(sessionId, block) {
    return expect(await callApi(`/api/research/blocks/${block}/start`, 'POST', sessionId, {}), isBlockStartOut, 'R4 の応答')
  },
  async endBlock(sessionId, block) {
    await callApi(`/api/research/blocks/${block}/end`, 'POST', sessionId, {})
  },
  async sendEvents(sessionId, events) {
    return expect(await callApi(EVENTS_PATH, 'POST', sessionId, { events }), isEventBatchOut, 'R6 の応答')
  },
  beaconEvents(events) {
    // sendBeacon はヘッダを付けられないので、セッションはクッキー（navi_sid）で伝わる。
    // 型は CORS の単純な型の text/plain にする（R6 は本文を UTF-8 の JSON として読む）
    const blob = new Blob([JSON.stringify({ events })], { type: 'text/plain;charset=UTF-8' })
    return navigator.sendBeacon(EVENTS_PATH, blob)
  },
  async endSession(sessionId) {
    await callApi('/api/research/sessions/current/end', 'POST', sessionId, {})
  },
}

/** 開発ビルドで、このトークンで始めると、ブラウザの中の偽の研究 API（devResearch.ts）で調査の流れを通せる */
export const DEV_TOKEN_PREFIX = 'dev-'

export function transportFor(token: string): TransportKind {
  return import.meta.env.DEV && token.startsWith(DEV_TOKEN_PREFIX) ? 'dev' : 'http'
}

let devTransport: ResearchTransport | null = null

export async function researchTransport(kind: TransportKind): Promise<ResearchTransport> {
  if (kind === 'http') return HTTP_TRANSPORT
  if (!import.meta.env.DEV) throw new StudyError(null, '開発用の調査は開発ビルドだけで動きます')
  if (devTransport === null) devTransport = (await import('./devResearch')).DEV_TRANSPORT
  return devTransport
}

/** 同期で使える（閉じる直前の sendBeacon 用）。開発用をまだ読み込んでいなければ null */
function loadedTransport(kind: TransportKind): ResearchTransport | null {
  return kind === 'http' ? HTTP_TRANSPORT : devTransport
}

/* ---------- イベントの列 ---------- */

const FLUSH_DELAY_MS = 2_000
const FLUSH_COUNT = 10
/** R6 の1回の上限 */
const BATCH_MAX = 100
const RETRY_FIRST_MS = 5_000
const RETRY_MAX_MS = 30_000
const MESSAGE_MAX_CHARS = 200

const queueKey = (sessionId: string) => `${RESEARCH_KEYS.queue}.${sessionId}`
const seqKey = (sessionId: string) => `${RESEARCH_KEYS.seq}.${sessionId}`

const EVENT_TYPES: readonly string[] = CLIENT_EVENT_TYPES

function isClientEvent(v: unknown): v is ClientEvent {
  return (
    isRecord(v) &&
    isString(v.event_id) &&
    isString(v.event_type) &&
    EVENT_TYPES.includes(v.event_type) &&
    isNumber(v.seq) &&
    isString(v.ts_client) &&
    (v.task_id === null || isString(v.task_id)) &&
    isRecord(v.payload)
  )
}

function isEventArray(v: unknown): v is ClientEvent[] {
  return Array.isArray(v) && v.every(isClientEvent)
}

function readQueue(sessionId: string): ClientEvent[] {
  return readJson('session', queueKey(sessionId), isEventArray) ?? []
}

function writeQueue(sessionId: string, events: ClientEvent[]): void {
  writeJson('session', queueKey(sessionId), events.length === 0 ? null : events)
}

/** 開き直したとき、サーバーが受け付けた seq の最大より手元の seq が小さければ、そこから続ける */
export function syncSeq(sessionId: string, lastSeq: number): void {
  const local = readJson('session', seqKey(sessionId), isNumber) ?? 0
  if (local < lastSeq) writeJson('session', seqKey(sessionId), lastSeq)
}

function nextSeq(sessionId: string): number {
  const seq = (readJson('session', seqKey(sessionId), isNumber) ?? 0) + 1
  writeJson('session', seqKey(sessionId), seq)
  return seq
}

/** UUID v4。crypto.randomUUID は HTTPS か localhost でしか使えないので、getRandomValues から作る */
function uuidV4(): string {
  const b = new Uint8Array(16)
  crypto.getRandomValues(b)
  b[6] = ((b[6] ?? 0) & 0x0f) | 0x40
  b[8] = ((b[8] ?? 0) & 0x3f) | 0x80
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/** ISO 8601（端末の時差つき。日本なら +09:00） */
function isoLocal(d: Date): string {
  const pad = (n: number, width = 2) => String(Math.abs(n)).padStart(width, '0')
  const offset = -d.getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}` +
    `${sign}${pad(Math.trunc(offset / 60))}:${pad(offset % 60)}`
  )
}

/** 端末の種類と画面幅の区分（PC・スマホ程度。ab-variants.md 7.2） */
export function deviceInfo(): EventPayload {
  return {
    pointer: window.matchMedia('(pointer: coarse)').matches ? 'coarse' : 'fine',
    width_class: window.matchMedia(PC_QUERY).matches ? 'pc' : 'phone',
    viewport_width: window.innerWidth,
  }
}

/**
 * イベントを1つ列に積む。task_id を省くと、いまの課題の ID（課題の外は null）。
 * セッションが無いか、断った・終えたあとは何もしない。
 */
export function logEvent(type: ClientEventType, payload: EventPayload = {}, taskId?: string | null): string | null {
  const study = getStudy()
  if (study === null || study.phase.kind === 'declined' || study.phase.kind === 'done') return null
  const sessionId = study.session.session_id
  const event: ClientEvent = {
    event_id: uuidV4(),
    event_type: type,
    seq: nextSeq(sessionId),
    ts_client: isoLocal(new Date()),
    task_id: taskId === undefined ? currentTaskId(study) : taskId,
    payload,
  }
  writeQueue(sessionId, [...readQueue(sessionId), event])
  scheduleFlush()
  return event.event_id
}

/** 調査中の画面が使う口 */
export const RESEARCH_LOG: ResearchLog = {
  active: true,
  log: (type, payload) => logEvent(type, payload),
}

let flushTimer: ReturnType<typeof setTimeout> | null = null
let retryDelay = RETRY_FIRST_MS
let inflight: Promise<boolean> | null = null

function scheduleFlush(delay = FLUSH_DELAY_MS): void {
  const study = getStudy()
  if (study === null) return
  if (readQueue(study.session.session_id).length >= FLUSH_COUNT) {
    void flushEvents()
    return
  }
  if (flushTimer !== null) return
  flushTimer = setTimeout(() => {
    flushTimer = null
    void flushEvents()
  }, delay)
}

/** 列を全部送る。送り終えたら true。失敗したら列に残し、時間をおいて送り直す */
export function flushEvents(): Promise<boolean> {
  if (inflight !== null) return inflight.then(() => flushEvents())
  inflight = sendQueue().finally(() => {
    inflight = null
  })
  return inflight
}

async function sendQueue(): Promise<boolean> {
  const study = getStudy()
  if (study === null) return true
  const sessionId = study.session.session_id
  const transport = await researchTransport(study.transport)
  for (;;) {
    const batch = readQueue(sessionId).slice(0, BATCH_MAX)
    if (batch.length === 0) {
      retryDelay = RETRY_FIRST_MS
      return true
    }
    let out: EventBatchOut
    try {
      out = await transport.sendEvents(sessionId, batch)
    } catch (err) {
      console.error(`研究のイベントを送れませんでした（${batch.length}件。${Math.round(retryDelay / 1000)}秒後に送り直します）`, err)
      if (flushTimer === null) {
        flushTimer = setTimeout(() => {
          flushTimer = null
          void flushEvents()
        }, retryDelay)
      }
      retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS)
      return false
    }
    if (out.warnings.length > 0) console.warn('研究のイベントにサーバーが印を付けました', out.warnings)
    const sent = new Set(batch.map((e) => e.event_id))
    writeQueue(
      sessionId,
      readQueue(sessionId).filter((e) => !sent.has(e.event_id)),
    )
  }
}

/** ページを隠す・閉じるときに、列を sendBeacon で送る（列からは消さない） */
function beaconQueue(): void {
  const study = getStudy()
  if (study === null) return
  const transport = loadedTransport(study.transport)
  if (transport === null) return
  const queue = readQueue(study.session.session_id)
  for (let i = 0; i < queue.length; i += BATCH_MAX) {
    if (!transport.beaconEvents(queue.slice(i, i + BATCH_MAX))) {
      console.error('閉じる前の送信（sendBeacon）を受け付けてもらえませんでした')
      return
    }
  }
}

function truncate(text: string): string {
  return text.length > MESSAGE_MAX_CHARS ? `${text.slice(0, MESSAGE_MAX_CHARS)}…` : text
}

let pageListenersInstalled = false

/** 中断（page_hidden・page_visible）、閉じる直前の送信、拾えなかった例外（client_error）を、調査のセッションのあいだ記録する */
function installPageListeners(): void {
  if (pageListenersInstalled) return
  pageListenersInstalled = true
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      logEvent('page_hidden')
      beaconQueue()
    } else {
      logEvent('page_visible')
    }
  })
  window.addEventListener('pagehide', beaconQueue)
  window.addEventListener('error', (e) => {
    logEvent('client_error', { kind: 'error', message: truncate(String(e.message)) })
  })
  window.addEventListener('unhandledrejection', (e) => {
    logEvent('client_error', { kind: 'unhandledrejection', message: truncate(String(e.reason)) })
  })
}

/** 画面が使った旗を、ブロックごとに1回だけ記録する（サーバーの旗と同じかを確かめるため） */
export function markVariantApplied(flags: VariantFlags): void {
  const study = getStudy()
  if (study === null || study.variant === null || study.phase.kind !== 'task') return
  const { block } = study.phase
  if (study.appliedBlock === block) return
  setStudy({ ...study, appliedBlock: block })
  logEvent('variant_applied', {
    block,
    variant_id: study.variant.variant_id,
    flags_digest: flagsDigest(flags),
    flags_version: study.variant.flags_version,
    ...deviceInfo(),
  })
}

/** 研究の API の失敗を、画面の外の記録にも残す */
export function logApiError(step: string, err: unknown): void {
  const status = err instanceof StudyError ? err.status : null
  logEvent('client_error', { kind: 'api', step, status, message: truncate(String(err)) })
}

// 開き直したタブで、前の調査のセッションが残っていれば、保存先と記録の口をすぐ切り替える
if (getStudy() !== null) {
  setStudyStorage(true)
  installPageListeners()
}

/* ---------- 調査でないときの旗（R8・R9） ---------- */

const VARIANT_ID_PATTERN = /^V\d{2}$/

/** 開発ビルドの ?variant=V02（空か default で解除）。タブの中で覚える */
function devVariantId(search: string): string | null {
  const param = new URLSearchParams(search).get('variant')
  if (param !== null) {
    writeJson('session', RESEARCH_KEYS.devVariant, VARIANT_ID_PATTERN.test(param) ? param : null)
    if (param !== '' && param !== 'default' && !VARIANT_ID_PATTERN.test(param)) console.error(`?variant=${param} は変種の ID ではありません`)
  }
  return readJson('session', RESEARCH_KEYS.devVariant, isString)
}

const variantPromises = new Map<string, Promise<VariantState>>()
const variantResolved = new Map<string, VariantState>()

async function fetchVariant(path: string): Promise<VariantState> {
  return toVariantState(expect(await callApi(path, 'GET', null), isVariantOut, `${path} の応答`))
}

async function resolveVariant(devId: string | null): Promise<VariantState> {
  if (import.meta.env.DEV && devId !== null) {
    try {
      return await fetchVariant(`/api/research/variants/${encodeURIComponent(devId)}`)
    } catch (err) {
      const { devVariantOut } = await import('./devResearch')
      const local = devVariantOut(devId)
      if (local === null) {
        console.error(`変種 ${devId} は変種の表にありません。V00 相当で出します`, err)
        return DEFAULT_VARIANT
      }
      console.warn(`R9 に届かないので、手元の変種の表（開発用）で ${devId} を出します`, err)
      return toVariantState(local)
    }
  }
  try {
    return await fetchVariant('/api/research/variants/default')
  } catch (err) {
    const report = import.meta.env.DEV ? console.warn : console.error
    report('既定の旗（R8）を受け取れないので、V00 相当（何も隠さない）で出します', err)
    return DEFAULT_VARIANT
  }
}

function loadVariant(devId: string | null): Promise<VariantState> {
  const key = devId ?? 'default'
  const cached = variantPromises.get(key)
  if (cached !== undefined) return cached
  const promise = resolveVariant(devId).then((v) => {
    variantResolved.set(key, v)
    return v
  })
  variantPromises.set(key, promise)
  return promise
}

/** 調査でないときの画面の旗。受け取るまでは既定（V00 相当） */
export function useFallbackVariant(enabled: boolean, search: string): VariantState {
  const devId = import.meta.env.DEV ? devVariantId(search) : null
  const key = devId ?? 'default'
  const [loaded, setLoaded] = useState<{ key: string; value: VariantState } | null>(null)
  useEffect(() => {
    if (!enabled) return
    let live = true
    void loadVariant(devId).then((value) => {
      if (live) setLoaded({ key: devId ?? 'default', value })
    })
    return () => {
      live = false
    }
  }, [enabled, devId])
  if (loaded !== null && loaded.key === key) return loaded.value
  return variantResolved.get(key) ?? DEFAULT_VARIANT
}
