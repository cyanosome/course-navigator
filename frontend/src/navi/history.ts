/**
 * 学期ごとの利用と履修の記録（学期の表と取った科目。学期のコンペの T-a）の純関数と、端末に保存する形。
 * - 今の学期: 初めに1回選んだ学期と、その日の暦の半期を持ち、以後は日付で進める（8月1日から秋、2月1日から春。
 *   大学の暦のデータが無いので固定の日）。「今の学期」は授業を受けている学期か、これから登録する学期。
 * - 記録: 今の学期より前の学期ごとの取った科目。記録の無い学期は「未記入」、科目の無い記録は「取っていない」で、
 *   未記入を取っていないとはみなさない。
 * - 登録済み: 今の学期から先の学期に履修登録した科目（syllabus_id）。
 * - まとまり（系統図）は科目名で系統図の科目に照らす（同じ名前の別クラスは系統図に載らないので、id では外れる）。
 * 履歴は端末の中（localStorage）にだけ置き、プランを作るときに backend へ送る（サーバーには残らない）。
 */
import type { DiagnoseTerm, PlanHistoryIn, RegisteredTermIn } from './apiTypes'
import { HISTORY_LIMITS } from './apiTypes'
import type { WorkingPlan } from './diagnose'
import { isNumber, isRecord, isString, isStringArray } from './storage'
import type { StatusCourse } from './status'
import type { TermKey } from './timetable'
import { ALL_TERMS, sameTerm, termIndex } from './timetable'
import type { Department } from './types'

/* ---------- 形 ---------- */

/** 取った科目（同じ名前の別クラスは区別しない。曜限はプランから来た科目とクラスが1つの科目だけ。分からなければ null） */
export interface TakenCourse {
  syllabus_id: string
  name: string
  credits: number | null
  slots: string[] | null
}

/** 記入済みの学期（courses が空なら「取っていない」） */
export interface TermRecord {
  year: number
  term: DiagnoseTerm
  courses: TakenCourse[]
}

/** その学期に履修登録した科目 */
export interface RegisteredRecord {
  year: number
  term: DiagnoseTerm
  ids: string[]
}

export interface StoredHistory {
  deptId: string
  /** 今の学期を決めたとき: 学期の番号（0 = 1年春 … 7 = 4年秋）と、その日の暦の半期（calendarHalf） */
  base: { index: number; cal: number } | null
  /** 切り替わりを済ませた今の学期の番号。今の学期がこれより後なら、学期の切り替わりの画面を出す */
  seen: number | null
  records: TermRecord[]
  registered: RegisteredRecord[]
}

export function emptyHistory(deptId: string): StoredHistory {
  return { deptId, base: null, seen: null, records: [], registered: [] }
}

function isTerm(v: unknown): v is DiagnoseTerm {
  return v === '春' || v === '秋'
}

function isTakenCourse(v: unknown): v is TakenCourse {
  return (
    isRecord(v) &&
    isString(v.syllabus_id) &&
    isString(v.name) &&
    (v.credits === null || isNumber(v.credits)) &&
    (v.slots === null || isStringArray(v.slots))
  )
}

export function isStoredHistory(v: unknown): v is StoredHistory {
  return (
    isRecord(v) &&
    isString(v.deptId) &&
    (v.base === null || (isRecord(v.base) && isNumber(v.base.index) && isNumber(v.base.cal))) &&
    (v.seen === null || isNumber(v.seen)) &&
    Array.isArray(v.records) &&
    v.records.every((r) => isRecord(r) && isNumber(r.year) && isTerm(r.term) && Array.isArray(r.courses) && r.courses.every(isTakenCourse)) &&
    Array.isArray(v.registered) &&
    v.registered.every((r) => isRecord(r) && isNumber(r.year) && isTerm(r.term) && isStringArray(r.ids))
  )
}

/* ---------- 今の学期 ---------- */

/** 秋の学期に切り替わる月（8月1日から）と、春に切り替わる月（2月1日から） */
const AUTUMN_FROM_MONTH = 8
const SPRING_FROM_MONTH = 2
export const LAST_TERM_INDEX = ALL_TERMS.length - 1

/** 暦の半期の通し番号（年×2、秋は +1。1月は前の年の秋） */
export function calendarHalf(date: Date): number {
  const month = date.getMonth() + 1
  const year = date.getFullYear()
  if (month >= AUTUMN_FROM_MONTH) return year * 2 + 1
  if (month < SPRING_FROM_MONTH) return (year - 1) * 2 + 1
  return year * 2
}

/** 学期の鍵（取った科目の画面の URL の ?term=。例 1-秋） */
export function termParam(t: TermKey): string {
  return `${t.year}-${t.half}`
}

/** 取った科目の画面の、その学期の節へのリンク */
export function historyHref(t: TermKey): string {
  return `/navi/history?term=${encodeURIComponent(termParam(t))}`
}

export function termAt(index: number): TermKey {
  return ALL_TERMS[Math.min(LAST_TERM_INDEX, Math.max(0, index))] ?? { year: 1, half: '春' }
}

/** 今の学期の番号（まだ決めていなければ null）。4年秋より後は4年秋のまま */
export function currentIndex(h: StoredHistory, now: Date): number | null {
  if (h.base === null) return null
  return Math.min(LAST_TERM_INDEX, Math.max(0, h.base.index + calendarHalf(now) - h.base.cal))
}

/** 今の学期を決め直す（初めに選んだとき・メニューで直したとき・前の学期のままにしたとき） */
export function withCurrent(h: StoredHistory, term: TermKey, now: Date, seen: number): StoredHistory {
  return { ...h, base: { index: termIndex(term), cal: calendarHalf(now) }, seen }
}

/* ---------- 記録 ---------- */

const sameRecordTerm = (r: { year: number; term: DiagnoseTerm }, t: TermKey) => r.year === t.year && r.term === t.half

export function recordOf(h: StoredHistory, t: TermKey): TermRecord | undefined {
  return h.records.find((r) => sameRecordTerm(r, t))
}

/** その学期の記録を置き換える（courses が空なら「取っていない」）。学期の順に並べる */
export function setRecord(h: StoredHistory, t: TermKey, courses: TakenCourse[]): StoredHistory {
  const rest = h.records.filter((r) => !sameRecordTerm(r, t))
  const records = [...rest, { year: t.year, term: t.half, courses }].sort(
    (a, b) => termIndex({ year: a.year, half: a.term }) - termIndex({ year: b.year, half: b.term }),
  )
  return { ...h, records }
}

/** その学期の記録を消す（未記入に戻す） */
export function clearRecord(h: StoredHistory, t: TermKey): StoredHistory {
  return { ...h, records: h.records.filter((r) => !sameRecordTerm(r, t)) }
}

/** その学期に取った科目を足す（同じ名前がもう記録にあれば足さない。記録が無ければ作る） */
export function addTaken(h: StoredHistory, t: TermKey, courses: TakenCourse[]): StoredHistory {
  const cur = recordOf(h, t)?.courses ?? []
  const names = new Set(cur.map((c) => c.name))
  const added = courses.filter((c) => {
    if (names.has(c.name)) return false
    names.add(c.name)
    return true
  })
  return setRecord(h, t, [...cur, ...added])
}

/** その学期の記録から科目を外す（記録は残る。全部外すと「取っていない」） */
export function removeTaken(h: StoredHistory, t: TermKey, name: string): StoredHistory {
  const rec = recordOf(h, t)
  if (rec === undefined) return h
  return setRecord(h, t, rec.courses.filter((c) => c.name !== name))
}

/** 取った科目（記入済みの学期の順） */
export function takenList(h: StoredHistory): { term: TermKey; course: TakenCourse }[] {
  return h.records.flatMap((r) => r.courses.map((course) => ({ term: { year: r.year, half: r.term }, course })))
}

/** 取った科目の名前 → 最初に取った学期 */
export function takenNames(h: StoredHistory): Map<string, TermKey> {
  const out = new Map<string, TermKey>()
  for (const { term, course } of takenList(h)) if (!out.has(course.name)) out.set(course.name, term)
  return out
}

/** プランの科目を取った科目に（クラスが分かるので曜限も持つ） */
export function takenFromPlan(c: { syllabus_id: string; name: string; credits: number | null; slots: string[] }): TakenCourse {
  return { syllabus_id: c.syllabus_id, name: c.name, credits: c.credits, slots: c.slots }
}

/** 系統図の科目を取った科目に（同じ名前の別クラスを取ったかもしれないので、曜限は持たない） */
export function takenFromGraph(c: { code: string; name: string; credits: number | null }): TakenCourse {
  return { syllabus_id: c.code, name: c.name, credits: c.credits, slots: null }
}

export function creditsOf(courses: readonly TakenCourse[]): number {
  return courses.reduce((n, c) => n + (c.credits ?? 0), 0)
}

/** 今の学期より前の学期のうち、記録の無い学期（未記入） */
export function unrecordedTerms(h: StoredHistory, current: number): TermKey[] {
  return ALL_TERMS.slice(0, current).filter((t) => recordOf(h, t) === undefined)
}

/* ---------- 登録済み ---------- */

export function registeredIds(h: StoredHistory, t: TermKey): string[] {
  return h.registered.find((r) => sameRecordTerm(r, t))?.ids ?? []
}

/** その学期の登録済みの科目を置き換える（空なら消す） */
export function setRegistered(h: StoredHistory, t: TermKey, ids: string[]): StoredHistory {
  const rest = h.registered.filter((r) => !sameRecordTerm(r, t))
  return { ...h, registered: ids.length === 0 ? rest : [...rest, { year: t.year, term: t.half, ids: [...new Set(ids)] }] }
}

/* ---------- 系統図との照らし合わせ ---------- */

/** その学期の系統図の科目（名前ごとに1つ。系統図の記載順） */
export function graphCoursesIn(dept: Department, t: TermKey): { code: string; name: string; credits: number | null }[] {
  const seen = new Set<string>()
  const out: { code: string; name: string; credits: number | null }[] = []
  for (const c of dept.courses) {
    const inTerm = c.year === t.year && (c.term === t.half || c.term === '通年')
    if (c.frameId === null || !inTerm || seen.has(c.name)) continue
    seen.add(c.name)
    out.push({ code: c.code, name: c.name, credits: c.credits })
  }
  return out
}

/**
 * 取った科目を履修状況の科目に（学期は記録の学期、まとまりと必修は系統図の科目に名前で照らす）。
 * 曜限の分からない科目は null（過去の学期の重なりは見ない）
 */
export function takenStatusCourses(h: StoredHistory, dept: Department): StatusCourse[] {
  const byName = new Map(dept.courses.filter((c) => c.frameId !== null).map((c) => [c.name, c]))
  return takenList(h).map(({ term, course }) => {
    const graph = byName.get(course.name)
    return {
      code: course.syllabus_id,
      name: course.name,
      terms: [term],
      credits: course.credits,
      slots: course.slots,
      frameId: graph?.frameId ?? null,
      required: graph?.kind === '必修',
    }
  })
}

/* ---------- 送るもの（POST /diagnose/plan と A1 の plan_context） ---------- */

/**
 * 履修の状況（backend の決まりに合わせる）。
 * - start: 今の学期。診断の範囲（scope）に無ければ送らない（422 になる）
 * - completed: 取った科目（重ねない。登録済みの科目は除く）
 * - registered: start から先の学期の登録済みの科目（plan があれば、plan のその学期にある科目だけ）
 * どれも無ければ null
 */
export function historyPayload(
  h: StoredHistory,
  current: TermKey | null,
  scope: readonly TermKey[],
  plan: WorkingPlan | null,
): PlanHistoryIn | null {
  const start = current !== null && scope.some((t) => sameTerm(t, current)) ? current : null
  const registered: RegisteredTermIn[] = h.registered
    .filter((r) => start !== null && termIndex({ year: r.year, half: r.term }) >= termIndex(start))
    .filter((r) => scope.some((t) => sameRecordTerm(r, t)))
    .map((r) => {
      const inPlan = plan?.terms.find((t) => t.year === r.year && t.term === r.term)?.courses.map((c) => c.syllabus_id)
      const ids = inPlan === undefined ? (plan === null ? r.ids : []) : r.ids.filter((id) => inPlan.includes(id))
      return { year: r.year, term: r.term, syllabus_ids: ids.slice(0, HISTORY_LIMITS.registeredIdsPerTerm) }
    })
    .filter((r) => r.syllabus_ids.length > 0)
    .slice(0, HISTORY_LIMITS.registeredTerms)
  const registeredSet = new Set(registered.flatMap((r) => r.syllabus_ids))
  const completed = [...new Set(takenList(h).map(({ course }) => course.syllabus_id))]
    .filter((id) => !registeredSet.has(id))
    .slice(0, HISTORY_LIMITS.completed)
  if (start === null && completed.length === 0 && registered.length === 0) return null
  return {
    ...(start === null ? {} : { start: { year: start.year, term: start.half } }),
    ...(completed.length === 0 ? {} : { completed }),
    ...(registered.length === 0 ? {} : { registered }),
  }
}
