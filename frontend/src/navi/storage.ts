/**
 * 端末の中の保存（UX 仕様 5.5）。
 * - 候補・学科・調査の記録は localStorage（この端末のこのブラウザ。タブを閉じても残る）。
 * - 自由記述の質問と回答は sessionStorage（タブを閉じると消える。UX 仕様 C06、requirements.md R1-3・R2-6）。
 * 保存できない環境（プライベートブラウズなど）でも画面は動くようにし、失敗は console.error で知らせる。
 * - 調査のセッション中は localStorage を使わず、'local' も sessionStorage に置く（計画 4.2。同じ端末を次の人が使うときに
 *   前の人の候補が残らないように）。調査の開始時とブロックの開始時に、画面の状態を消す（clearAppState）。
 */

type Area = 'local' | 'session'

/** 調査のセッション中か（research.ts が切り替える） */
let studyStorage = false

export function setStudyStorage(on: boolean): void {
  studyStorage = on
}

function area(kind: Area): Storage {
  return kind === 'local' && !studyStorage ? window.localStorage : window.sessionStorage
}

/** 読めなければ null。中身の形は呼び出し側の guard で確かめる */
export function readJson<T>(kind: Area, key: string, guard: (v: unknown) => v is T): T | null {
  let raw: string | null
  try {
    raw = area(kind).getItem(key)
  } catch (err) {
    console.error(`保存領域を読めませんでした（${key}）`, err)
    return null
  }
  if (raw === null) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (guard(parsed)) return parsed
    console.error(`保存された値の形が想定と違うため使いません（${key}）`)
    return null
  } catch (err) {
    console.error(`保存された値を読めませんでした（${key}）`, err)
    return null
  }
}

export function writeJson(kind: Area, key: string, value: unknown): void {
  try {
    if (value === null) area(kind).removeItem(key)
    else area(kind).setItem(key, JSON.stringify(value))
  } catch (err) {
    console.error(`保存できませんでした（${key}）`, err)
  }
}

export function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'string')
}

export function isString(v: unknown): v is string {
  return typeof v === 'string'
}

export function isNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

export const KEYS = {
  dept: 'navi.dept',
  assumedYear: 'navi.assumedYear',
  shortlist: 'navi.shortlist',
  study: 'navi.study',
  ask: 'navi.ask',
  askSeq: 'navi.askSeq',
  askDraft: 'navi.askDraft',
  askSent: 'navi.askSent',
  wait: 'navi.wait',
  keyword: 'navi.keyword',
  /** 診断の答えとプラン（学科ごと） */
  diagnose: 'navi.diagnose',
  /** プランの微修正の質問と回答（sessionStorage） */
  refine: 'navi.refine',
  refineSeq: 'navi.refineSeq',
  /** 履修状況のチェックの一覧 */
  checkpoints: 'navi.checkpoints',
  /** 今の学期と取った科目（学科ごと。調査のモードでは使わない） */
  history: 'navi.history',
} as const

/** 研究のログの欄（画面の状態とは別に持ち、clearAppState では消さない） */
export const RESEARCH_KEYS = {
  study: 'navi.research.study',
  queue: 'navi.research.queue',
  seq: 'navi.research.seq',
  devVariant: 'navi.research.devVariant',
} as const

/** 調査の開始時・ブロックの開始時に、画面の状態（学科・候補・質問・検索の語など）を sessionStorage から消す */
export function clearAppState(): void {
  for (const key of Object.values(KEYS)) writeJson('session', key, null)
}
