/**
 * 端末の中の保存（UX 仕様 5.5）。
 * - 候補・学科・調査の記録は localStorage（この端末のこのブラウザ。タブを閉じても残る）。
 * - 自由記述の質問と回答は sessionStorage（タブを閉じると消える。UX 仕様 C06、requirements.md R1-3・R2-6）。
 * 保存できない環境（プライベートブラウズなど）でも画面は動くようにし、失敗は console.error で知らせる。
 */

type Area = 'local' | 'session'

function area(kind: Area): Storage {
  return kind === 'local' ? window.localStorage : window.sessionStorage
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
} as const
