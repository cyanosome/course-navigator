/**
 * 診断の変種（diagnose=quiz）の「確かめる場所」（PC は右の列、スマホは上の帯）の見せ方を作る純関数。
 * 判定は status.ts の関数をそのまま使い、ここでは 学期ごとに分ける・短い名前と値にする・時間割のマスにする・
 * AI の案を入れた場合と比べる、だけをする。どの関数も入力だけで結果が決まる。
 */
import type { CourseSummary } from './apiTypes'
import type { CheckContext, Checkpoint, CheckResult, CheckStatus, CourseStatus, StatusCourse } from './status'
import { buildStatus, evaluateCheckpoints } from './status'
import type { TermKey } from './timetable'
import { sameTerm, termIndex, termLabel } from './timetable'
import type { Department } from './types'
import { WIDE_SPACE } from './views'

/* ---------- 学期 ---------- */

function rankOf(t: TermKey): number {
  const i = termIndex(t)
  return i >= 0 ? i : t.year * 2 + (t.half === '秋' ? 1 : 0)
}

/** 切り替えられる学期（プランの学期と、科目のある学期。早い順。重ならない） */
export function ledgerTerms(planTerms: TermKey[], status: CourseStatus): TermKey[] {
  const all = [...planTerms, ...status.terms.map((t) => t.term)]
  return all.filter((t, i) => all.findIndex((x) => sameTerm(x, t)) === i).sort((a, b) => rankOf(a) - rankOf(b))
}

/** その学期の科目だけの履修状況（通年の科目も、この学期の分として1つに数える） */
export function termStatus(status: CourseStatus, term: TermKey): CourseStatus {
  const here = status.courses.filter((c) => c.terms.some((t) => sameTerm(t, term))).map((c) => ({ ...c, terms: [term] }))
  return buildStatus(here)
}

/* ---------- チェック ---------- */

/** 学期ごとに見るチェック（単位の各学期・空ける曜日・重なり）。ほかはプラン全体で見る */
export function isTermCheck(cp: Checkpoint): boolean {
  return cp.kind === 'free_slot' || cp.kind === 'no_overlap' || (cp.kind === 'credits' && cp.per === 'term')
}

export interface TermChecks {
  term: TermKey
  /** その学期の科目だけの履修状況 */
  status: CourseStatus
  results: CheckResult[]
}

export function termChecks(
  status: CourseStatus,
  term: TermKey,
  checkpoints: readonly Checkpoint[],
  ctx: Omit<CheckContext, 'terms'>,
): TermChecks {
  const st = termStatus(status, term)
  return { term, status: st, results: evaluateCheckpoints(checkpoints.filter(isTermCheck), st, { ...ctx, terms: [term] }) }
}

/** プラン全体で見るチェック（全体の単位・まとまりの数・前のまとまりの抜け・必修） */
export function planChecks(status: CourseStatus, checkpoints: readonly Checkpoint[], ctx: CheckContext): CheckResult[] {
  return evaluateCheckpoints(
    checkpoints.filter((cp) => !isTermCheck(cp)),
    status,
    ctx,
  )
}

export function unmetCount(results: readonly CheckResult[]): number {
  return results.filter((r) => r.status === 'unmet').length
}

function frameName(dept: Department, id: string): string {
  return dept.frames.find((f) => f.id === id)?.name ?? id
}

/** チェックの短い名前（値は右に別に出すので、名前には入れない） */
export function checkShortLabel(cp: Checkpoint, dept: Department): string {
  switch (cp.kind) {
    case 'credits': {
      const head = cp.per === 'total' ? '全体の単位' : '単位'
      if (cp.min !== null && cp.max !== null) return `${head} ${cp.min}〜${cp.max}`
      if (cp.min !== null) return `${head} ${cp.min}以上`
      if (cp.max !== null) return `${head} ${cp.max}まで`
      return head
    }
    case 'free_slot': {
      const days = `${cp.days.join('・')}曜`
      return cp.periods.length === 0 ? `${days}を空ける` : `${days}${cp.periods.join('・')}限を空ける`
    }
    case 'group_count':
      return `${cp.groups.map((g) => `「${frameName(dept, g)}」`).join('か')}${cp.min}つ以上`
    case 'prerequisite':
      return '前のまとまりの抜け'
    case 'no_overlap':
      return '曜限の重なり'
    case 'required':
      return '必修'
  }
}

const SLOT_PATTERN = /^([月火水木金土日])(\d+)$/

function uniq(list: string[]): string[] {
  return [...new Set(list)]
}

/** 右に添える短い値（例 17、なし、火1、2科目、準備中） */
export function checkValue(cp: Checkpoint, r: CheckResult, status: CourseStatus): string {
  switch (cp.kind) {
    case 'credits': {
      const credits = cp.per === 'total' ? status.totalCredits : (status.terms[0]?.credits ?? 0)
      return String(credits)
    }
    case 'free_slot': {
      if (r.status !== 'unmet') return r.status === 'met' ? '空き' : '不明'
      const slots = status.courses
        .filter((c) => r.codes.includes(c.code))
        .flatMap((c) => (c.slots ?? []).filter((s) => {
          const m = SLOT_PATTERN.exec(s)
          return m !== null && (cp.days as readonly string[]).includes(m[1] ?? '') && (cp.periods.length === 0 || cp.periods.includes(Number(m[2])))
        }))
      return uniq(slots).join('・')
    }
    case 'no_overlap': {
      if (r.status !== 'unmet') return r.status === 'met' ? 'なし' : '不明'
      return uniq(status.terms.flatMap((t) => t.overlaps.map((o) => o.slot))).join('・')
    }
    case 'group_count':
      return `${r.codes.length}科目`
    case 'prerequisite':
      return r.status === 'met' ? 'なし' : r.status === 'unmet' ? `${r.codes.length}科目` : '不明'
    case 'required':
      return r.status === 'met' ? 'あり' : r.status === 'unmet' ? `${r.codes.length}科目` : '準備中'
  }
}

/** 名前は3つまで出し、残りは数にする */
const NAMES_SHOWN = 3

/**
 * 満たさないときと判定できないときの2行目（原因の科目の名前か、理由の文）。満たすときと、名前の無いものは空。
 * 前のまとまりの抜けと必修は、理由の文に科目とまとまりの名前が入っているので、その文を使う
 */
export function checkDetail(cp: Checkpoint, r: CheckResult, status: CourseStatus): string {
  if (r.status === 'met') return ''
  if (cp.kind === 'required') return r.status === 'unmet' ? r.reason : ''
  if (cp.kind === 'prerequisite' || r.status === 'unknown') return r.reason
  if (cp.kind === 'group_count') return ''
  const names = r.codes.map((code) => status.courses.find((c) => c.code === code)?.name ?? code)
  if (names.length === 0) return ''
  const shown = names.slice(0, NAMES_SHOWN).join('、')
  return names.length > NAMES_SHOWN ? `${shown}ほか${names.length - NAMES_SHOWN}科目` : shown
}

export const CHECK_STATUS_WORD: Record<CheckStatus, string> = { met: '満たす', unmet: '要確認', unknown: '判定できない' }

/* ---------- 満たさないチェックの直し方（同じ名前の別のクラスへ移す。LLM は使わない） ---------- */

/** 移す先を探すチェック（重なりと空ける曜日）と、その原因の科目 */
export function movableCauses(cp: Checkpoint, r: CheckResult): string[] {
  if (r.status !== 'unmet' || (cp.kind !== 'no_overlap' && cp.kind !== 'free_slot')) return []
  return r.codes
}

function hitsFree(slot: string, checkpoints: readonly Checkpoint[]): boolean {
  const m = SLOT_PATTERN.exec(slot)
  if (m === null) return false
  return checkpoints.some(
    (cp) =>
      cp.kind === 'free_slot' &&
      (cp.days as readonly string[]).includes(m[1] ?? '') &&
      (cp.periods.length === 0 || cp.periods.includes(Number(m[2]))),
  )
}

export interface ClassMove {
  fromCode: string
  fromName: string
  toCode: string
  toSlots: string[]
}

/**
 * 原因の科目を、同じ名前の別のクラスへ移す先（見つからなければ null）。移す先は、同じ学期に取れ（学年が同じで、
 * 学期が同じか通年）、曜限がその学期のほかの科目と重ならず、空けるチェックの曜限にも入らないクラス。
 * candidates は検索（D4）の結果の並びのまま見て、最初に合うものを選ぶ
 */
export function pickClassMove(
  cause: StatusCourse,
  term: TermKey,
  termCourses: readonly StatusCourse[],
  candidates: readonly CourseSummary[],
  checkpoints: readonly Checkpoint[],
): ClassMove | null {
  const used = new Set(termCourses.filter((c) => c.code !== cause.code).flatMap((c) => c.slots ?? []))
  for (const s of candidates) {
    if (s.syllabus_id === cause.code || s.name !== cause.name || s.slots.length === 0) continue
    if (termCourses.some((c) => c.code === s.syllabus_id)) continue
    if ((s.year_min ?? term.year) !== term.year || (s.term !== term.half && s.term !== '通年')) continue
    if (s.slots.some((slot) => used.has(slot) || hitsFree(slot, checkpoints))) continue
    return { fromCode: cause.code, fromName: cause.name, toCode: s.syllabus_id, toSlots: s.slots }
  }
  return null
}

/* ---------- 時間割のマス ---------- */

const BASE_DAYS = ['月', '火', '水', '木', '金'] as const
const BASE_PERIODS = 5

export interface LedgerGrid {
  days: string[]
  periods: number[]
  /** 曜限 → その学期の科目 */
  cells: Map<string, StatusCourse[]>
  /** 表に置けない科目（曜限の無い科目・曜限の分からない科目） */
  offGrid: StatusCourse[]
}

/**
 * その学期の時間割。月〜金・1〜5限を基本に、土曜の科目か土曜を空けるチェックがあれば土曜の列を、
 * 6限より後の科目があればその時限までの行を足す（月〜金だけだと、土曜のチェックや6限の科目と表が合わない）
 */
export function ledgerGrid(term: CourseStatus, checkpoints: readonly Checkpoint[]): LedgerGrid {
  const cells = new Map<string, StatusCourse[]>()
  const offGrid: StatusCourse[] = []
  let saturday = checkpoints.some((cp) => cp.kind === 'free_slot' && cp.days.includes('土'))
  let lastPeriod = BASE_PERIODS
  for (const c of term.courses) {
    const placed = (c.slots ?? []).filter((s) => {
      const m = SLOT_PATTERN.exec(s)
      if (m === null || m[1] === '日') return false
      if (m[1] === '土') saturday = true
      lastPeriod = Math.max(lastPeriod, Number(m[2]))
      return true
    })
    if (placed.length === 0) offGrid.push(c)
    for (const s of placed) cells.set(s, [...(cells.get(s) ?? []), c])
  }
  return {
    days: saturday ? [...BASE_DAYS, '土'] : [...BASE_DAYS],
    periods: Array.from({ length: lastPeriod }, (_, i) => i + 1),
    cells,
    offGrid,
  }
}

/** 一覧の並び（曜日 → 時限。曜限の無い科目は最後） */
export function slotOrder(slots: string[] | null): number {
  const days = ['月', '火', '水', '木', '金', '土', '日']
  const first = (slots ?? []).map((s) => SLOT_PATTERN.exec(s)).find((m) => m !== null)
  if (first === undefined || first === null) return Number.MAX_SAFE_INTEGER
  return days.indexOf(first[1] ?? '') * 100 + Number(first[2])
}

/* ---------- AI の案を入れた場合（AI の欄の中だけで出す） ---------- */

export interface EffectLine {
  term: TermKey
  text: string
}

/**
 * 案を入れる前と後の、学期ごとの単位・重なり・要確認の数の変わり方。変わった学期だけ、変わったものだけを出す。
 * before・after はプラン全体の履修状況、checks は学期ごとのチェックの計算（右の列と同じ判定）
 */
export function proposalEffects(
  before: CourseStatus,
  after: CourseStatus,
  terms: TermKey[],
  check: (status: CourseStatus, term: TermKey) => CheckResult[],
): EffectLine[] {
  const out: EffectLine[] = []
  for (const term of terms) {
    const a = termStatus(before, term)
    const b = termStatus(after, term)
    const parts: string[] = []
    const ca = a.terms[0]?.credits ?? 0
    const cb = b.terms[0]?.credits ?? 0
    if (ca !== cb) parts.push(`単位 ${ca} → ${cb}`)
    const oa = uniq(a.terms.flatMap((t) => t.overlaps.map((o) => o.slot))).join('・') || 'なし'
    const ob = uniq(b.terms.flatMap((t) => t.overlaps.map((o) => o.slot))).join('・') || 'なし'
    if (oa !== ob) parts.push(`重なり ${oa} → ${ob}`)
    const na = unmetCount(check(before, term))
    const nb = unmetCount(check(after, term))
    if (na !== nb) parts.push(`要確認 ${na} → ${nb}`)
    if (parts.length > 0) out.push({ term, text: `${termLabel(term)}${WIDE_SPACE}${parts.join('、')}` })
  }
  return out
}
