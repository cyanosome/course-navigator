/**
 * 時間割の計算（E1 5章）。学期、曜限のマス、必修と候補の置き方、重なり、単位、卒業要件の進み具合。
 * どの関数も入力だけで結果が決まる。
 */
import { findCourse } from './graph'
import type { Course, Department, GradCategory } from './types'

export type Half = '春' | '秋'

/** 時間割の1学期（例 1年春） */
export interface TermKey {
  year: number
  half: Half
}

export const DAYS = ['月', '火', '水', '木', '金'] as const
export const PERIODS = [1, 2, 3, 4, 5] as const
export const MAX_YEAR = 4

/** 1年春〜4年秋 */
export const ALL_TERMS: TermKey[] = Array.from({ length: MAX_YEAR }, (_, i) => i + 1).flatMap((year) => [
  { year, half: '春' as const },
  { year, half: '秋' as const },
])

export function termLabel(t: TermKey): string {
  return `${t.year}年${t.half}`
}

export function sameTerm(a: TermKey, b: TermKey): boolean {
  return a.year === b.year && a.half === b.half
}

export function termIndex(t: TermKey): number {
  return ALL_TERMS.findIndex((x) => sameTerm(x, t))
}

/** 科目が入る学期（通年は春と秋の両方） */
export function termsOf(course: Course): TermKey[] {
  if (course.term === '通年') return [{ year: course.year, half: '春' }, { year: course.year, half: '秋' }]
  return [{ year: course.year, half: course.term }]
}

export function inTerm(course: Course, t: TermKey): boolean {
  return termsOf(course).some((x) => sameTerm(x, t))
}

/** 科目の学期の表記（例 3年春、4年通年） */
export function courseTermLabel(course: Course): string {
  return `${course.year}年${course.term}`
}

/** 時間割の表に入る曜限（月〜金・1〜5限）。表の外の書き方（土曜・6限など）は「曜限なし」に回す */
export function gridSlots(course: Course): string[] {
  return course.slots.filter((s) => /^[月火水木金][1-5]$/.test(s))
}

export function isOnGrid(course: Course): boolean {
  return gridSlots(course).length > 0
}

/** 一覧の左の列の曜限（E1 8章: オンデマンドは随時、ほかは「なし」） */
export function slotShort(course: Course): string[] {
  if (course.slots.length > 0) return course.slots
  return [course.slotNote === 'オンデマンド' ? '随時' : 'なし']
}

/** 詳細の曜限（例 月2・木2、随時（オンデマンド）、なし（集中講義）） */
export function slotLong(course: Course): string {
  if (course.slots.length > 0) return course.slots.join('・')
  if (course.slotNote === 'オンデマンド') return '随時（オンデマンド）'
  if (course.slotNote !== null) return `なし（${course.slotNote}）`
  return 'なし'
}

export function shortName(course: Course): string {
  return course.short ?? course.name
}

/** 学科の必修（最初から時間割に灰で入れておく。区分が分からない学科では空。E1 5章・8章） */
export function requiredCourses(dept: Department): Course[] {
  return dept.courses.filter((c) => c.kind === '必修')
}

export function isRequired(course: Course): boolean {
  return course.kind === '必修'
}

/** 学科の系統図に無い科目を引く口（科目の入れ物に読んだ詳細、プランの科目）。無ければ undefined */
export type CourseLookup = (code: string) => Course | undefined

/**
 * 時間割に置く科目の引き方。
 * - lookup: 系統図に無い科目を引く口。省くと系統図の科目だけを置く
 * - withRequired: 学科の必修を最初から入れるか（省くと入れる。プランを時間割にするときは入れない）
 */
export interface Placement {
  lookup?: CourseLookup
  withRequired?: boolean
}

/** 科目を引く（系統図の科目 → lookup の順） */
export function resolveCourse(dept: Department, code: string, placement: Placement = {}): Course | undefined {
  return findCourse(dept, code) ?? placement.lookup?.(code)
}

/** 時間割に入っている科目（必修 → 候補の順。重ならない） */
export function placedCourses(dept: Department, shortlist: string[], placement: Placement = {}): Course[] {
  const required = placement.withRequired === false ? [] : requiredCourses(dept)
  const picked = shortlist
    .map((code) => resolveCourse(dept, code, placement))
    .filter((c): c is Course => c !== undefined && !required.some((r) => r.code === c.code))
  return [...required, ...picked]
}

export function placedInTerm(dept: Department, shortlist: string[], t: TermKey, placement: Placement = {}): Course[] {
  return placedCourses(dept, shortlist, placement).filter((c) => inTerm(c, t))
}

/** その学期の単位（単位の分からない科目は数えない） */
export function termCredits(dept: Department, shortlist: string[], t: TermKey, placement: Placement = {}): number {
  return placedInTerm(dept, shortlist, t, placement).reduce((n, c) => n + (c.credits ?? 0), 0)
}

export function unknownCreditCount(dept: Department, shortlist: string[], t: TermKey, placement: Placement = {}): number {
  return placedInTerm(dept, shortlist, t, placement).filter((c) => c.credits === null).length
}

/** 曜限 → その学期に入っている科目 */
export function slotMap(courses: Course[]): Map<string, Course[]> {
  const map = new Map<string, Course[]>()
  for (const c of courses) {
    for (const s of gridSlots(c)) {
      const list = map.get(s)
      if (list === undefined) map.set(s, [c])
      else list.push(c)
    }
  }
  return map
}

export interface Clash {
  /** 重なっている学期 */
  term: TermKey
  slot: string
  other: Course
}

/**
 * その科目と同じ学期・同じ曜限に、時間割に入っているほかの科目（必修か候補）。入れる前でも後でも使う。
 */
export function clashesOf(dept: Department, shortlist: string[], course: Course, placement: Placement = {}): Clash[] {
  const out: Clash[] = []
  for (const t of termsOf(course)) {
    const others = placedInTerm(dept, shortlist, t, placement).filter((c) => c.code !== course.code)
    for (const slot of gridSlots(course)) {
      for (const other of others) {
        if (gridSlots(other).includes(slot)) out.push({ term: t, slot, other })
      }
    }
  }
  return out
}

export interface GradProgress {
  category: GradCategory
  placed: number
  need: number
}

/** 卒業要件の区分ごとの、時間割に入れた単位（全学期）と要る単位。卒業要件が無い学科は null */
export function gradProgress(dept: Department, shortlist: string[], placement: Placement = {}): GradProgress[] | null {
  const req = dept.requirements
  if (req === null) return null
  const placed = placedCourses(dept, shortlist, placement)
  return req.needs.map((n) => ({
    category: n.category,
    need: n.need,
    placed: placed.filter((c) => c.grad === n.category).reduce((s, c) => s + (c.credits ?? 0), 0),
  }))
}

export function totalPlacedCredits(dept: Department, shortlist: string[], placement: Placement = {}): number {
  return placedCourses(dept, shortlist, placement).reduce((n, c) => n + (c.credits ?? 0), 0)
}

/** 時間割を文字にする（メニューの「時間割を文字でコピー」） */
export function timetableText(dept: Department, shortlist: string[], placement: Placement = {}): string {
  const lines: string[] = [`時間割（コースナビ・${dept.name}）`]
  for (const t of ALL_TERMS) {
    const courses = placedInTerm(dept, shortlist, t, placement)
    if (courses.length === 0) continue
    lines.push('', `${termLabel(t)} ${termCredits(dept, shortlist, t, placement)}単位`)
    for (const c of courses) {
      lines.push(`${slotLong(c)} ${c.name}${isRequired(c) ? '（必修）' : ''}`)
    }
  }
  lines.push('', '候補は履修登録ではありません。')
  return lines.join('\n')
}
