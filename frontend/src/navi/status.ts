/**
 * 履修状況（選んだ科目・学期ごとの単位・曜限の表）と、利用者が決めたチェックの判定。どの関数も入力だけで結果が決まる。
 * - 入力は科目の一覧（StatusCourse）。候補（statusCoursesFromShortlist）からもプラン（statusCoursesFromPlan）からも作れる。
 * - チェックの結果は「満たす・満たさない・判定できない」と理由（どの科目が原因か）。データが準備中のもの
 *   （必修の区分など）と、科目のデータが読めていないもの（単位・曜限が分からない）は「判定できない」にし、推測で埋めない。
 * - 診断のみと診断＋対話の両方で同じものを出す（LLM は使わない）。
 */
import type { DiagnoseTerm, EventPayload, JsonValue } from './apiTypes'
import type { WorkingPlan } from './diagnose'
import { findCourse } from './graph'
import { isNumber, isRecord, isString, isStringArray } from './storage'
import type { TermKey } from './timetable'
import { ALL_TERMS, requiredCourses, sameTerm, termIndex, termLabel, termsOf } from './timetable'
import type { Course, Department } from './types'

/* ---------- 科目の一覧 ---------- */

export interface StatusCourse {
  code: string
  name: string
  /** 入る学期（通年は春と秋）。分からなければ空 */
  terms: TermKey[]
  /** 単位。分からなければ null */
  credits: number | null
  /** 曜限（例 ['月2']。曜限の無い科目は []）。科目のデータが読めていなければ null */
  slots: string[] | null
  /** 系統図のまとまり（系統図に載っていない科目は null） */
  frameId: string | null
  /** 学科の必修（区分のデータがあるときだけ true になりうる） */
  required: boolean
}

function fromCourse(c: Course): StatusCourse {
  return {
    code: c.code,
    name: c.name,
    terms: termsOf(c),
    credits: c.credits,
    slots: c.slots,
    frameId: c.frameId,
    required: c.kind === '必修',
  }
}

function planTermKey(t: { year: number; term: DiagnoseTerm }): TermKey {
  return { year: t.year, half: t.term }
}

/**
 * 候補から。科目は 学科の系統図の科目 → 読み込み済みの詳細（D5）→ プランの科目 の順に引く。
 * どれにも無ければ名前と学期が分からない科目として入れる（チェックは「判定できない」になる）。
 * withRequired: 時間割と同じく、学科の必修を最初から入れる（旗 requirements=shown のとき）
 */
export function statusCoursesFromShortlist(
  dept: Department,
  shortlist: string[],
  lookup: (code: string) => Course | undefined,
  plan: WorkingPlan | null,
  withRequired: boolean,
): StatusCourse[] {
  const required = withRequired ? requiredCourses(dept).map(fromCourse) : []
  const picked = shortlist
    .filter((code) => !required.some((r) => r.code === code))
    .map((code): StatusCourse => {
      const course = findCourse(dept, code) ?? lookup(code)
      if (course !== undefined) return fromCourse(course)
      const inPlan = plan === null ? undefined : findInPlan(plan, code)
      if (inPlan !== undefined) return inPlan
      return { code, name: code, terms: [], credits: null, slots: null, frameId: null, required: false }
    })
  return [...required, ...picked]
}

function findInPlan(plan: WorkingPlan, code: string): StatusCourse | undefined {
  for (const t of plan.terms) {
    const c = t.courses.find((x) => x.syllabus_id === code)
    if (c !== undefined) {
      return { code, name: c.name, terms: [planTermKey(t)], credits: c.credits, slots: c.slots, frameId: null, required: false }
    }
  }
  return undefined
}

/** プランから。学期はプランの学期、まとまりと必修は学科の系統図の科目から引く */
export function statusCoursesFromPlan(dept: Department, plan: WorkingPlan): StatusCourse[] {
  return plan.terms.flatMap((t) =>
    t.courses.map((c): StatusCourse => {
      const course = findCourse(dept, c.syllabus_id)
      return {
        code: c.syllabus_id,
        name: c.name,
        terms: [planTermKey(t)],
        credits: c.credits,
        slots: c.slots,
        frameId: course?.frameId ?? null,
        required: course?.kind === '必修',
      }
    }),
  )
}

/* ---------- 履修状況 ---------- */

export interface SlotOverlap {
  slot: string
  codes: string[]
}

export interface StatusTerm {
  term: TermKey
  courses: StatusCourse[]
  /** 単位の合計（単位の分からない科目は数えない） */
  credits: number
  /** 単位の分からない科目の数 */
  unknownCredits: number
  /** 同じ曜限に2つ以上ある曜限 */
  overlaps: SlotOverlap[]
}

export interface CourseStatus {
  courses: StatusCourse[]
  /** 科目のある学期（早い順） */
  terms: StatusTerm[]
  totalCredits: number
  unknownCredits: number
  /** 学期の分からない科目 */
  unplaced: StatusCourse[]
}

function inTermOf(c: StatusCourse, t: TermKey): boolean {
  return c.terms.some((x) => sameTerm(x, t))
}

function overlapsOf(courses: StatusCourse[]): SlotOverlap[] {
  const map = new Map<string, string[]>()
  for (const c of courses) {
    for (const s of c.slots ?? []) map.set(s, [...(map.get(s) ?? []), c.code])
  }
  return [...map.entries()].filter(([, codes]) => codes.length > 1).map(([slot, codes]) => ({ slot, codes }))
}

function statusTerm(courses: StatusCourse[], term: TermKey): StatusTerm {
  const here = courses.filter((c) => inTermOf(c, term))
  return {
    term,
    courses: here,
    credits: here.reduce((n, c) => n + (c.credits ?? 0), 0),
    unknownCredits: here.filter((c) => c.credits === null).length,
    overlaps: overlapsOf(here),
  }
}

/** 1年春〜4年秋の外の学期（5年以上など）も落とさないよう、科目の学期から並べる */
function termsIn(courses: StatusCourse[]): TermKey[] {
  const all = courses.flatMap((c) => c.terms)
  const unique = all.filter((t, i) => all.findIndex((x) => sameTerm(x, t)) === i)
  const rank = (t: TermKey) => (termIndex(t) >= 0 ? termIndex(t) : t.year * 2 + (t.half === '秋' ? 1 : 0))
  return unique.sort((a, b) => rank(a) - rank(b))
}

export function buildStatus(courses: StatusCourse[]): CourseStatus {
  const terms = termsIn(courses).map((t) => statusTerm(courses, t))
  return {
    courses,
    terms,
    // 通年の科目は春と秋の両方に出るので、合計は科目ごとに1回だけ数える
    totalCredits: courses.reduce((n, c) => n + (c.credits ?? 0), 0),
    unknownCredits: courses.filter((c) => c.credits === null).length,
    unplaced: courses.filter((c) => c.terms.length === 0),
  }
}

/* ---------- チェック ---------- */

export const CHECK_DAYS = ['月', '火', '水', '木', '金', '土'] as const
export type CheckDay = (typeof CHECK_DAYS)[number]
export const CHECK_PERIODS = [1, 2, 3, 4, 5, 6, 7] as const

export type Checkpoint =
  /** 単位の合計。per: total は全体、term は学期ごと（判定する学期は CheckContext.terms） */
  | { id: string; kind: 'credits'; per: 'total' | 'term'; min: number | null; max: number | null }
  /** その曜日（periods を書けばその時限だけ）を空ける */
  | { id: string; kind: 'free_slot'; days: CheckDay[]; periods: number[] }
  /** そのまとまり（系統図。複数ならどれか）の科目を合わせて min 個以上 */
  | { id: string; kind: 'group_count'; groups: string[]; min: number }
  /** 選んだ科目（必修を除く）の、系統図の線で前のまとまりの科目が、一覧に1つはある */
  | { id: string; kind: 'prerequisite' }
  /** 同じ学期・同じ曜限に2つ入れていない */
  | { id: string; kind: 'no_overlap' }
  /** 学科の必修を入れている（区分のデータが無いあいだは判定できない） */
  | { id: string; kind: 'required' }

export type CheckKind = Checkpoint['kind']

export type CheckStatus = 'met' | 'unmet' | 'unknown'

export interface CheckResult {
  id: string
  kind: CheckKind
  status: CheckStatus
  /** 短い理由 */
  reason: string
  /** 原因の科目（満たさないときはその科目、数えるものは数えた科目、判定できないときはデータの無い科目） */
  codes: string[]
}

export interface CheckContext {
  dept: Department
  /** 学期ごとのチェックで見る学期。空なら科目のある学期 */
  terms: TermKey[]
  /** 必修の区分のデータがあるか（無ければ必修のチェックは判定できない） */
  kindsAvailable: boolean
}

/** はじめの一覧。数を決める必要が無いものだけ（学期の上限は学科のデータに無いので、数は利用者が決める） */
export const DEFAULT_CHECKPOINTS: readonly Checkpoint[] = [
  { id: 'no_overlap', kind: 'no_overlap' },
  { id: 'prerequisite', kind: 'prerequisite' },
  { id: 'required', kind: 'required' },
]

/** 区分のデータがあるか（学科の科目のどれかに区分が付いていれば、ある） */
export function kindsAvailable(dept: Department): boolean {
  return dept.courses.some((c) => c.kind !== null)
}

function frameName(dept: Department, id: string): string {
  return dept.frames.find((f) => f.id === id)?.name ?? id
}

function nameOf(status: CourseStatus, code: string): string {
  return status.courses.find((c) => c.code === code)?.name ?? code
}

function namesOf(status: CourseStatus, codes: string[]): string {
  return codes.map((c) => nameOf(status, c)).join('、')
}

const PER_LABEL = { total: '全体で', term: '各学期' } as const

/** チェックの見出し（例 各学期 24単位まで、月曜を空ける、「物理化学系」を2つ以上） */
export function checkpointLabel(cp: Checkpoint, dept: Department): string {
  switch (cp.kind) {
    case 'credits': {
      const per = PER_LABEL[cp.per]
      if (cp.min !== null && cp.max !== null) return `${per}${cp.min}〜${cp.max}単位`
      if (cp.min !== null) return `${per}${cp.min}単位以上`
      if (cp.max !== null) return `${per}${cp.max}単位まで`
      return `${per}の単位`
    }
    case 'free_slot': {
      const days = cp.days.map((d) => `${d}曜`).join('・')
      return cp.periods.length === 0 ? `${days}を空ける` : `${days}${cp.periods.join('・')}限を空ける`
    }
    case 'group_count':
      return `${cp.groups.map((g) => `「${frameName(dept, g)}」`).join('か')}の科目を${cp.min}つ以上`
    case 'prerequisite':
      return '前のまとまりの科目が抜けていない'
    case 'no_overlap':
      return '曜限が重なっていない'
    case 'required':
      return '必修が入っている'
  }
}

function worst(statuses: CheckStatus[]): CheckStatus {
  if (statuses.includes('unmet')) return 'unmet'
  if (statuses.includes('unknown')) return 'unknown'
  return 'met'
}

/** 単位の範囲の判定（分からない単位は 0 以上のどれか、として扱う） */
function creditRange(credits: number, unknown: number, min: number | null, max: number | null): CheckStatus {
  const results: CheckStatus[] = []
  if (min !== null) results.push(credits >= min ? 'met' : unknown > 0 ? 'unknown' : 'unmet')
  if (max !== null) results.push(credits > max ? 'unmet' : unknown > 0 ? 'unknown' : 'met')
  return worst(results)
}

function checkCredits(cp: Extract<Checkpoint, { kind: 'credits' }>, status: CourseStatus, ctx: CheckContext): CheckResult {
  const base = { id: cp.id, kind: cp.kind }
  const unknownCodes = (courses: StatusCourse[]) => courses.filter((c) => c.credits === null).map((c) => c.code)
  if (cp.per === 'total') {
    const s = creditRange(status.totalCredits, status.unknownCredits, cp.min, cp.max)
    const note = status.unknownCredits > 0 ? `（単位の分からない科目 ${status.unknownCredits}）` : ''
    return {
      ...base,
      status: s,
      reason: `合計 ${status.totalCredits}単位${note}`,
      // 上限を超えたら全部の科目、判定できないなら単位の分からない科目。満たすなら無し
      codes:
        s === 'met'
          ? []
          : s === 'unmet' && cp.max !== null && status.totalCredits > cp.max
            ? status.courses.map((c) => c.code)
            : unknownCodes(status.courses),
    }
  }
  const terms = ctx.terms.length > 0 ? ctx.terms : status.terms.map((t) => t.term)
  if (terms.length === 0) return { ...base, status: cp.min === null ? 'met' : 'unmet', reason: '科目がありません', codes: [] }
  const per = terms.map((t) => {
    const st = status.terms.find((x) => sameTerm(x.term, t)) ?? statusTerm([], t)
    return { st, s: creditRange(st.credits, st.unknownCredits, cp.min, cp.max) }
  })
  const bad = per.filter((p) => p.s === 'unmet')
  const unsure = per.filter((p) => p.s === 'unknown')
  if (bad.length > 0) {
    return {
      ...base,
      status: 'unmet',
      reason: bad.map((p) => `${termLabel(p.st.term)} ${p.st.credits}単位`).join('、'),
      // 上限を超えた学期はその学期の科目、下限に足りない学期は原因の科目が無い
      codes: bad.filter((p) => cp.max !== null && p.st.credits > cp.max).flatMap((p) => p.st.courses.map((c) => c.code)),
    }
  }
  if (unsure.length > 0) {
    return {
      ...base,
      status: 'unknown',
      reason: `単位の分からない科目があります（${unsure.map((p) => termLabel(p.st.term)).join('、')}）`,
      codes: unsure.flatMap((p) => unknownCodes(p.st.courses)),
    }
  }
  return { ...base, status: 'met', reason: per.map((p) => `${termLabel(p.st.term)} ${p.st.credits}単位`).join('、'), codes: [] }
}

const SLOT_PATTERN = /^([月火水木金土日])(\d+)$/

function hitsSlot(slot: string, days: readonly string[], periods: readonly number[]): boolean {
  const m = SLOT_PATTERN.exec(slot)
  if (m === null) return false
  return days.includes(m[1] ?? '') && (periods.length === 0 || periods.includes(Number(m[2])))
}

function checkFreeSlot(cp: Extract<Checkpoint, { kind: 'free_slot' }>, status: CourseStatus): CheckResult {
  const base = { id: cp.id, kind: cp.kind }
  const hits = status.courses.filter((c) => (c.slots ?? []).some((s) => hitsSlot(s, cp.days, cp.periods)))
  if (hits.length > 0) {
    const slots = hits.flatMap((c) => (c.slots ?? []).filter((s) => hitsSlot(s, cp.days, cp.periods)))
    return { ...base, status: 'unmet', reason: `${[...new Set(slots)].join('・')}に入っています`, codes: hits.map((c) => c.code) }
  }
  const unknown = status.courses.filter((c) => c.slots === null)
  if (unknown.length > 0) return { ...base, status: 'unknown', reason: '曜限の分からない科目があります', codes: unknown.map((c) => c.code) }
  return { ...base, status: 'met', reason: '空いています', codes: [] }
}

function checkGroupCount(cp: Extract<Checkpoint, { kind: 'group_count' }>, status: CourseStatus): CheckResult {
  const hits = status.courses.filter((c) => c.frameId !== null && cp.groups.includes(c.frameId))
  return {
    id: cp.id,
    kind: cp.kind,
    status: hits.length >= cp.min ? 'met' : 'unmet',
    reason: `${hits.length}つ`,
    codes: hits.map((c) => c.code),
  }
}

function checkPrerequisite(cp: Extract<Checkpoint, { kind: 'prerequisite' }>, status: CourseStatus, dept: Department): CheckResult {
  const base = { id: cp.id, kind: cp.kind }
  const has = (frameId: string) => status.courses.some((c) => c.frameId === frameId)
  const missing: { code: string; frameId: string }[] = []
  const noData: string[] = []
  for (const c of status.courses) {
    // 必修は自分で選んだ科目ではない（時間割に最初から入る）ので、前の科目の抜けを問わない。前の科目としては数える
    if (c.frameId === null || c.required) continue
    for (const e of dept.edges.filter((x) => x.to === c.frameId)) {
      if (has(e.from)) continue
      // 前のまとまりに学科のデータの科目が無ければ、入れようがないので「判定できない」に回す
      if (dept.courses.some((x) => x.frameId === e.from)) missing.push({ code: c.code, frameId: e.from })
      else noData.push(c.code)
    }
  }
  if (missing.length > 0) {
    const codes = [...new Set(missing.map((m) => m.code))]
    const frames = [...new Set(missing.map((m) => m.frameId))].map((f) => `「${frameName(dept, f)}」`)
    return { ...base, status: 'unmet', reason: `${namesOf(status, codes)}の前の${frames.join('・')}がありません`, codes }
  }
  if (noData.length > 0) {
    return { ...base, status: 'unknown', reason: '前のまとまりの科目がデータにありません', codes: [...new Set(noData)] }
  }
  return { ...base, status: 'met', reason: '抜けはありません', codes: [] }
}

function checkNoOverlap(cp: Extract<Checkpoint, { kind: 'no_overlap' }>, status: CourseStatus): CheckResult {
  const base = { id: cp.id, kind: cp.kind }
  const clashes = status.terms.flatMap((t) => t.overlaps.map((o) => ({ term: t.term, ...o })))
  if (clashes.length > 0) {
    return {
      ...base,
      status: 'unmet',
      reason: clashes.map((c) => `${termLabel(c.term)}の${c.slot}`).join('、'),
      codes: [...new Set(clashes.flatMap((c) => c.codes))],
    }
  }
  const unknown = status.courses.filter((c) => c.slots === null || c.terms.length === 0)
  if (unknown.length > 0) return { ...base, status: 'unknown', reason: '曜限か学期の分からない科目があります', codes: unknown.map((c) => c.code) }
  return { ...base, status: 'met', reason: '重なりはありません', codes: [] }
}

function checkRequired(cp: Extract<Checkpoint, { kind: 'required' }>, status: CourseStatus, ctx: CheckContext): CheckResult {
  const base = { id: cp.id, kind: cp.kind }
  if (!ctx.kindsAvailable) return { ...base, status: 'unknown', reason: '必修の区分は準備中です', codes: [] }
  const terms = ctx.terms.length > 0 ? ctx.terms : ALL_TERMS
  const need = requiredCourses(ctx.dept).filter((c) => termsOf(c).some((t) => terms.some((x) => sameTerm(x, t))))
  const lacking = need.filter((c) => !status.courses.some((s) => s.code === c.code))
  if (lacking.length > 0) {
    return { ...base, status: 'unmet', reason: `${lacking.map((c) => c.name).join('、')}がありません`, codes: lacking.map((c) => c.code) }
  }
  return { ...base, status: 'met', reason: `${need.length}科目とも入っています`, codes: [] }
}

export function evaluateCheckpoint(cp: Checkpoint, status: CourseStatus, ctx: CheckContext): CheckResult {
  switch (cp.kind) {
    case 'credits':
      return checkCredits(cp, status, ctx)
    case 'free_slot':
      return checkFreeSlot(cp, status)
    case 'group_count':
      return checkGroupCount(cp, status)
    case 'prerequisite':
      return checkPrerequisite(cp, status, ctx.dept)
    case 'no_overlap':
      return checkNoOverlap(cp, status)
    case 'required':
      return checkRequired(cp, status, ctx)
  }
}

export function evaluateCheckpoints(checkpoints: readonly Checkpoint[], status: CourseStatus, ctx: CheckContext): CheckResult[] {
  return checkpoints.map((cp) => evaluateCheckpoint(cp, status, ctx))
}

/* ---------- 保存と記録 ---------- */

const CHECK_KINDS: readonly string[] = ['credits', 'free_slot', 'group_count', 'prerequisite', 'no_overlap', 'required']

function isNullableNumber(v: unknown): v is number | null {
  return v === null || isNumber(v)
}

export function isCheckpoint(v: unknown): v is Checkpoint {
  if (!isRecord(v) || !isString(v.id) || !isString(v.kind) || !CHECK_KINDS.includes(v.kind)) return false
  switch (v.kind) {
    case 'credits':
      return (v.per === 'total' || v.per === 'term') && isNullableNumber(v.min) && isNullableNumber(v.max)
    case 'free_slot':
      return (
        isStringArray(v.days) &&
        v.days.every((d) => (CHECK_DAYS as readonly string[]).includes(d)) &&
        Array.isArray(v.periods) &&
        v.periods.every(isNumber)
      )
    case 'group_count':
      return isStringArray(v.groups) && isNumber(v.min)
    default:
      return true
  }
}

export function isCheckpointList(v: unknown): v is Checkpoint[] {
  return Array.isArray(v) && v.every(isCheckpoint)
}

/** 研究のログに載せるチェック（そのままの形） */
export function checkpointPayload(cp: Checkpoint): EventPayload {
  switch (cp.kind) {
    case 'credits':
      return { id: cp.id, kind: cp.kind, per: cp.per, min: cp.min, max: cp.max }
    case 'free_slot':
      return { id: cp.id, kind: cp.kind, days: [...cp.days], periods: [...cp.periods] }
    case 'group_count':
      return { id: cp.id, kind: cp.kind, groups: [...cp.groups], min: cp.min }
    default:
      return { id: cp.id, kind: cp.kind }
  }
}

export function resultsPayload(results: CheckResult[]): JsonValue {
  return results.map((r) => ({ id: r.id, status: r.status, codes: [...r.codes] }))
}
