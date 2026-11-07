/**
 * 開発ビルドだけで読み込む（research.ts の import.meta.env.DEV の分岐の中の import()）。本番の束には入らない。
 * - 変種の表: ab-variants.md 付録 A の写し。正本は backend の course_core/research/variants.py で、これは画面の確認用
 *   （/navi?variant=V02 で R9 に届かないとき）。
 * - 偽の研究 API（R1〜R7）: /navi/s/dev-a1 のように dev- で始まるトークンで開くと、backend なしで調査の流れを通せる。
 *   a は分岐 A（N=V01 記号 K、A=V00 記号 M）、b は分岐 B（N=V02 J、A=V01 L）、c は H3（N=V02 J、A=V03 H）、
 *   d は診断の A/B（N=V30 診断のみ 記号 W、A=V31 診断＋対話 記号 Y。事前登録 study1 の 2.1 の記号）。
 *   数字は系列（1: N+P1→A+P2、2: A+P1→N+P2、3: N+P2→A+P1、4: A+P2→N+P1）。練習（ブロック0）は1つ目のブロックの旗。
 *   受け取ったイベントは sessionStorage の navi.devResearch.events に積み、console.debug にも出す。
 */
import { FORM_SERIAL_PATTERN } from './apiTypes'
import type { BlockPlan, BlockStartOut, ClientEvent, ConsentIn, EventBatchOut, SessionOut, VariantOut } from './apiTypes'
import { StudyError } from './research'
import type { ResearchTransport } from './research'
import { isNumber, isRecord, isString, isStringArray, readJson, writeJson } from './storage'
import { CONSENT } from './studyConfig'
import { FLAGS_VERSION, V00_FLAGS } from './variant'
import type { VariantFlags } from './variant'

/* ---------- 変種の表（付録 A） ---------- */

const AI_OFF: Partial<VariantFlags> = {
  assistant: 'off',
  ai_route: null,
  verify: null,
  citations: null,
  style: null,
  question_frame: null,
  toolset: null,
  model: null,
  ai_edges: null,
  retrieval: null,
}
const NO_GRAPH: Partial<VariantFlags> = { graph: 'off', recommend: 'off', first_suggestion: 'none' }

const VARIANTS: Record<string, { aiOff: boolean; diff: Partial<VariantFlags> }> = {
  V00: { aiOff: false, diff: {} },
  V01: { aiOff: true, diff: {} },
  V02: { aiOff: true, diff: NO_GRAPH },
  V03: { aiOff: false, diff: NO_GRAPH },
  V04: { aiOff: true, diff: { recommend: 'off', first_suggestion: 'none' } },
  V05: { aiOff: true, diff: { recommend: 'catalog' } },
  V06: { aiOff: true, diff: { recommend: 'reach_seeded' } },
  V07: { aiOff: false, diff: { ai_route: 'mcp_free' } },
  V08: { aiOff: false, diff: { ai_route: 'static_llm' } },
  V09: { aiOff: false, diff: { ai_route: 'static' } },
  V10: { aiOff: false, diff: { citations: 'text' } },
  V11: { aiOff: false, diff: { style: 'brief' } },
  V12: { aiOff: false, diff: { style: 'detailed' } },
  V13: { aiOff: false, diff: { first_suggestion: 'llm' } },
  V14: { aiOff: false, diff: { question_frame: 'raw' } },
  V15: { aiOff: false, diff: { question_frame: 'composed_guardrail' } },
  V16: { aiOff: false, diff: { toolset: 'per_request' } },
  V17: { aiOff: true, diff: { timetable: 'off' } },
  V18: { aiOff: true, diff: { detail: 'core' } },
  V19: { aiOff: true, diff: { rule_edges: 'official_prereq' } },
  V20: { aiOff: true, diff: { rule_edges: 'with_inferred' } },
  V21: { aiOff: false, diff: { model: 'alt' } },
  V22: { aiOff: true, diff: { ...NO_GRAPH, search: 'kw_filter' } },
  V23: { aiOff: false, diff: { verify: 'off' } },
  V24: { aiOff: true, diff: { search: 'off' } },
  V25: { aiOff: false, diff: { ai_edges: 'with_similar' } },
  V26: { aiOff: false, diff: { retrieval: 'vector_seed' } },
  V27: { aiOff: true, diff: { similar_panel: 'on' } },
  V28: { aiOff: false, diff: { ai_edges: 'with_inferred' } },
  V29: { aiOff: true, diff: { requirements: 'hidden' } },
  /* 11/7 に足した診断の変種（backend の表に足す案と同じ。表の版 2） */
  V30: { aiOff: true, diff: { diagnose: 'quiz' } },
  V31: { aiOff: false, diff: { diagnose: 'quiz' } },
}

export function devVariantOut(variantId: string, conditionId: string | null = null): VariantOut | null {
  const v = VARIANTS[variantId]
  if (v === undefined) return null
  const flags: VariantFlags = { ...V00_FLAGS, ...(v.aiOff ? AI_OFF : {}), ...v.diff }
  return { variant_id: variantId, condition_id: conditionId, flags, flags_version: FLAGS_VERSION }
}

/* ---------- 偽の研究 API ---------- */

type Role = 'N' | 'A'

/** 腕ごとの役割（変種と伏せた記号） */
const ARMS: Record<string, Record<Role, [string, string]>> = {
  a: { N: ['V01', 'K'], A: ['V00', 'M'] },
  b: { N: ['V02', 'J'], A: ['V01', 'L'] },
  c: { N: ['V02', 'J'], A: ['V03', 'H'] },
  d: { N: ['V30', 'W'], A: ['V31', 'Y'] },
}

/** 系列（計画 4.1 の Q1〜Q4）: ブロック1・2の役割と課題セット */
const SEQUENCES: Record<string, [Role, string][]> = {
  '1': [
    ['N', 'P1'],
    ['A', 'P2'],
  ],
  '2': [
    ['A', 'P1'],
    ['N', 'P2'],
  ],
  '3': [
    ['N', 'P2'],
    ['A', 'P1'],
  ],
  '4': [
    ['A', 'P2'],
    ['N', 'P1'],
  ],
}

const TASK_SETS: Record<string, string[]> = {
  practice: ['practice'],
  P1: ['P1-a', 'P1-b'],
  P2: ['P2-a', 'P2-b'],
}

const DEV_TOKEN = /^dev-([abcd])([1-4])$/
/** 見本の学科（fixtureDepartment.ts の id） */
const DEV_DEPARTMENT = 'enechem'
/** 偽の study の同意文の版（画面の文の版と同じにする） */
const DEV_CONSENT_VERSION = CONSENT.version

const STATE_KEY = 'navi.devResearch'
const EVENTS_KEY = 'navi.devResearch.events'

interface DevSession {
  token: string
  sessionId: string
  arm: string
  sequence: string
  consent: boolean
  current: number | null
  ended: number[]
  lastSeq: number
  eventIds: string[]
  finished: boolean
}

function isDevSession(v: unknown): v is DevSession {
  return (
    isRecord(v) &&
    isString(v.token) &&
    isString(v.sessionId) &&
    isString(v.arm) &&
    isString(v.sequence) &&
    typeof v.consent === 'boolean' &&
    (v.current === null || isNumber(v.current)) &&
    Array.isArray(v.ended) &&
    v.ended.every(isNumber) &&
    isNumber(v.lastSeq) &&
    isStringArray(v.eventIds) &&
    typeof v.finished === 'boolean'
  )
}

function isDevSessions(v: unknown): v is DevSession[] {
  return Array.isArray(v) && v.every(isDevSession)
}

function sessions(): DevSession[] {
  return readJson('session', STATE_KEY, isDevSessions) ?? []
}

function save(next: DevSession): void {
  writeJson('session', STATE_KEY, [...sessions().filter((s) => s.sessionId !== next.sessionId), next])
}

function bySession(sessionId: string): DevSession {
  const found = sessions().find((s) => s.sessionId === sessionId)
  if (found === undefined) throw new StudyError(401, '（開発用）セッションがありません')
  return found
}

function blocksOf(dev: DevSession): { plan: BlockPlan; variant: VariantOut }[] {
  const arm = ARMS[dev.arm]
  const sequence = SEQUENCES[dev.sequence]
  if (arm === undefined || sequence === undefined) throw new StudyError(404, '（開発用）トークンが表にありません')
  const main = sequence.map(([role, set], i) => {
    const [variantId, conditionId] = arm[role]
    const variant = devVariantOut(variantId, conditionId)
    if (variant === null) throw new StudyError(500, `（開発用）変種 ${variantId} がありません`)
    return { plan: { block: i + 1, condition_id: conditionId, task_set_id: set, task_ids: TASK_SETS[set] ?? [] }, variant }
  })
  const first = main[0]
  if (first === undefined) throw new StudyError(500, '（開発用）ブロックがありません')
  const practice = {
    plan: { block: 0, condition_id: 'P', task_set_id: 'practice', task_ids: TASK_SETS.practice ?? [] },
    variant: { ...first.variant, condition_id: 'P' },
  }
  return [practice, ...main]
}

function sessionOut(dev: DevSession): SessionOut {
  const blocks = blocksOf(dev)
  const current = dev.current === null ? undefined : blocks.find((b) => b.plan.block === dev.current)
  return {
    session_id: dev.sessionId,
    pid: 'P90',
    study_id: 'DEV',
    sequence_id: `Q${dev.sequence}`,
    mode: 'onsite',
    department_id: DEV_DEPARTMENT,
    consent_version: DEV_CONSENT_VERSION,
    consent_recorded: dev.consent,
    blocks: blocks.map((b) => b.plan),
    current_block: dev.current,
    variant: current?.variant ?? null,
    backend_version: 'dev',
    completed_blocks: dev.ended,
    last_seq: dev.lastSeq,
  }
}

interface StoredEvent extends ClientEvent {
  received_block: number | null
  warnings: string[]
}

function isStoredEvents(v: unknown): v is StoredEvent[] {
  return Array.isArray(v) && v.every((e) => isRecord(e) && isString(e.event_id) && isString(e.event_type))
}

function receive(sessionId: string, events: ClientEvent[]): EventBatchOut {
  const dev = bySession(sessionId)
  if (dev.finished) throw new StudyError(401, '（開発用）セッションは終わっています')
  const seen = new Set(dev.eventIds)
  const stored = readJson('session', EVENTS_KEY, isStoredEvents) ?? []
  const warnings: string[] = []
  let accepted = 0
  let duplicates = 0
  let lastSeq = dev.lastSeq
  for (const e of events) {
    if (seen.has(e.event_id)) {
      duplicates += 1
      continue
    }
    const marks: string[] = []
    if (e.seq !== lastSeq + 1) marks.push('seq_gap')
    lastSeq = Math.max(lastSeq, e.seq)
    seen.add(e.event_id)
    accepted += 1
    warnings.push(...marks)
    stored.push({ ...e, received_block: dev.current, warnings: marks })
    console.debug('（開発用）研究のイベント', e.seq, e.event_type, e.task_id, e.payload)
  }
  writeJson('session', EVENTS_KEY, stored)
  save({ ...dev, lastSeq, eventIds: [...seen] })
  return { accepted, duplicates, last_seq: lastSeq, warnings }
}

export const DEV_TRANSPORT: ResearchTransport = {
  async startSession(token) {
    const m = DEV_TOKEN.exec(token)
    if (m === null) throw new StudyError(404, '（開発用）トークンが表にありません')
    const existing = sessions().find((s) => s.token === token && !s.finished)
    if (existing !== undefined) return sessionOut(existing)
    const dev: DevSession = {
      token,
      sessionId: `dev-${Date.now().toString(36)}`,
      arm: m[1] ?? 'a',
      sequence: m[2] ?? '1',
      consent: false,
      current: null,
      ended: [],
      lastSeq: 0,
      eventIds: [],
      finished: false,
    }
    save(dev)
    return sessionOut(dev)
  },
  async currentSession(sessionId) {
    return sessionOut(bySession(sessionId))
  },
  async recordConsent(sessionId, input: ConsentIn) {
    const dev = bySession(sessionId)
    if (input.consent_version !== DEV_CONSENT_VERSION) throw new StudyError(409, '（開発用）同意文の版が study と違います')
    if (!FORM_SERIAL_PATTERN.test(input.form_serial)) throw new StudyError(422, '（開発用）同意書の番号の形が違います')
    save({ ...dev, consent: input.agreed })
  },
  async startBlock(sessionId, block): Promise<BlockStartOut> {
    const dev = bySession(sessionId)
    if (!dev.consent) throw new StudyError(409, '（開発用）同意の前です')
    if (dev.current !== null && !dev.ended.includes(dev.current)) throw new StudyError(409, '（開発用）前のブロックが終わっていません')
    const next = blocksOf(dev).find((b) => !dev.ended.includes(b.plan.block))
    if (next === undefined || next.plan.block !== block) throw new StudyError(409, `（開発用）次のブロックは ${String(next?.plan.block)} です`)
    save({ ...dev, current: block })
    return { plan: next.plan, variant: next.variant }
  },
  async endBlock(sessionId, block) {
    const dev = bySession(sessionId)
    if (dev.current !== block) throw new StudyError(409, '（開発用）始めていないブロックです')
    save({ ...dev, ended: [...dev.ended, block] })
  },
  async sendEvents(sessionId, events) {
    return receive(sessionId, events)
  },
  beaconEvents(events) {
    const dev = sessions().find((s) => !s.finished)
    if (dev === undefined) return false
    try {
      receive(dev.sessionId, events)
      return true
    } catch (err) {
      console.error('（開発用）閉じる前の送信を受けられませんでした', err)
      return false
    }
  },
  async endSession(sessionId) {
    save({ ...bySession(sessionId), finished: true })
  },
}
