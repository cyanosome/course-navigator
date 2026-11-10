/**
 * 学科データ（系統図のまとまり・線・科目）から、画面に出す並びと「取る順」を決まった規則で計算する（UX 仕様 9.4 F3）。
 * LLM は使わない。どの関数も入力だけで結果が決まる。
 */
import type { Course, Department, Frame, Interest, Term } from './types'

const TERM_ORDER: Record<Term, number> = { 春: 0, 秋: 1, 通年: 2 }
/** 興味関心の一覧で、学年ごとに出す科目の数 */
export const SHOWN_PER_YEAR = 2

export function findCourse(dept: Department, code: string): Course | undefined {
  return dept.courses.find((c) => c.code === code)
}

export function findFrame(dept: Department, id: string | null): Frame | undefined {
  if (id === null) return undefined
  return dept.frames.find((f) => f.id === id)
}

export function findInterest(dept: Department, id: string): Interest | undefined {
  return dept.interests.find((d) => d.id === id)
}

/** 既定（おすすめ）以外の興味関心（3年の分野） */
export function realInterests(dept: Department): Interest[] {
  return dept.interests.filter((d) => d.targets.length > 0)
}

function courseOrder(dept: Department): Map<string, number> {
  return new Map(dept.courses.map((c, i) => [c.code, i]))
}

function frameOrder(dept: Department, id: string): number {
  return dept.frames.findIndex((f) => f.id === id)
}

function byFrameOrder(dept: Department, frames: Frame[]): Frame[] {
  return [...frames].sort((a, b) => frameOrder(dept, a.id) - frameOrder(dept, b.id))
}

/** まとまりの中の並び: 学期（春が先）→ 系統図の記載順（UX 仕様 C24） */
export function coursesInFrame(dept: Department, frameId: string): Course[] {
  const order = courseOrder(dept)
  return dept.courses
    .filter((c) => c.frameId === frameId)
    .sort((a, b) => TERM_ORDER[a.term] - TERM_ORDER[b.term] || (order.get(a.code) ?? 0) - (order.get(b.code) ?? 0))
}

/** そのまとまりから線が出ていく先 */
export function nextFrames(dept: Department, frameId: string): Frame[] {
  const ids = dept.edges.filter((e) => e.from === frameId).map((e) => e.to)
  return byFrameOrder(dept, dept.frames.filter((f) => ids.includes(f.id)))
}

/** そのまとまりに線が入ってくる側 */
export function prevFrames(dept: Department, frameId: string): Frame[] {
  const ids = dept.edges.filter((e) => e.to === frameId).map((e) => e.from)
  return byFrameOrder(dept, dept.frames.filter((f) => ids.includes(f.id)))
}

export function hasEdge(dept: Department, from: string, to: string): boolean {
  return dept.edges.some((e) => e.from === from && e.to === to)
}

/** 線を下流へたどって届くまとまり（自分を含む） */
function downstream(dept: Department, frameId: string): Set<string> {
  const seen = new Set<string>([frameId])
  const stack = [frameId]
  while (stack.length > 0) {
    const id = stack.pop()
    if (id === undefined) break
    for (const e of dept.edges) {
      if (e.from === id && !seen.has(e.to)) {
        seen.add(e.to)
        stack.push(e.to)
      }
    }
  }
  return seen
}

/** 線を上流へたどって届くまとまり（起点を含む） */
function upstream(dept: Department, frameIds: string[]): Set<string> {
  const seen = new Set<string>(frameIds)
  const stack = [...frameIds]
  while (stack.length > 0) {
    const id = stack.pop()
    if (id === undefined) break
    for (const e of dept.edges) {
      if (e.to === id && !seen.has(e.from)) {
        seen.add(e.from)
        stack.push(e.from)
      }
    }
  }
  return seen
}

/** そのまとまりから線をたどって届く3年の分野（興味関心のどれか1つのまとまりに届けば、届いたと数える。UX 仕様 3.7） */
export function reachedInterests(dept: Department, frameId: string | null): Interest[] {
  if (frameId === null) return []
  const reach = downstream(dept, frameId)
  return realInterests(dept).filter((d) => d.targets.some((t) => reach.has(t)))
}

export interface Sequence {
  /** 先に取る（線が入ってくるまとまりの、最初の科目） */
  before: Course[]
  /** あとに続く（線が出ていくまとまりの、最初の科目） */
  after: Course[]
  /** 同じまとまりのほかの科目 */
  same: Course[]
}

function firstOf(dept: Department, frames: Frame[]): Course[] {
  return frames.map((f) => coursesInFrame(dept, f.id)[0]).filter((c): c is Course => c !== undefined)
}

/** 詳細（W3）の「取る順」 */
export function sequenceOf(dept: Department, course: Course): Sequence {
  if (course.frameId === null) return { before: [], after: [], same: [] }
  return {
    before: firstOf(dept, prevFrames(dept, course.frameId)),
    after: firstOf(dept, nextFrames(dept, course.frameId)),
    same: coursesInFrame(dept, course.frameId).filter((c) => c.code !== course.code),
  }
}

export interface InterestRow {
  course: Course
  why: string
  source: string
}

export interface InterestGroup {
  year: number
  rows: InterestRow[]
}

/** 興味関心の一覧の行の「なぜ」（E1 の一覧の言い方） */
function interestWhy(dept: Department, interest: Interest, course: Course, onPath: Set<string>): string {
  const frame = findFrame(dept, course.frameId)
  if (frame === undefined) return `「${interest.label}」につながる`
  if (interest.targets.includes(frame.id)) return `「${interest.label}」の科目`
  const next = nextFrames(dept, frame.id).filter((f) => onPath.has(f.id))[0]
  if (next === undefined) return `「${interest.label}」につながる`
  if (interest.targets.includes(next.id)) return `${next.year}年の「${interest.label}」につながる`
  return `${next.year}年の${next.plain}につながる`
}

/**
 * 興味関心を選んだあとの一覧（W2）。分野のまとまりへ線をさかのぼって届くまとまりの科目を、学年ごとに並べる。
 * 必修は選ぶものではないので出さない（E1 5章）。学年ごとに SHOWN_PER_YEAR 件まで（学期→まとまりの記載順→科目の記載順）。
 */
export function interestGroups(dept: Department, interest: Interest): InterestGroup[] {
  const onPath = upstream(dept, interest.targets)
  const order = courseOrder(dept)
  const candidates = dept.courses
    .filter((c) => c.frameId !== null && onPath.has(c.frameId) && c.kind !== '必修')
    .sort(
      (a, b) =>
        a.year - b.year ||
        TERM_ORDER[a.term] - TERM_ORDER[b.term] ||
        frameOrder(dept, a.frameId ?? '') - frameOrder(dept, b.frameId ?? '') ||
        (order.get(a.code) ?? 0) - (order.get(b.code) ?? 0),
    )
  const years = [...new Set(candidates.map((c) => c.year))].sort((a, b) => a - b)
  const groups = years.map((year) => ({
    year,
    rows: candidates
      .filter((c) => c.year === year)
      .slice(0, SHOWN_PER_YEAR)
      .map((course) => ({ course, why: interestWhy(dept, interest, course, onPath), source: '系統図' })),
  }))
  for (const extra of interest.extras) {
    const course = findCourse(dept, extra.code)
    if (course === undefined) continue
    const group = groups.find((g) => g.year === course.year)
    const row = { course, why: extra.why, source: extra.source }
    if (group === undefined) groups.push({ year: course.year, rows: [row] })
    else group.rows.push(row)
  }
  return groups.sort((a, b) => a.year - b.year)
}

/** 系統図の記載順（科目の配列の順） */
export function courseIndex(dept: Department, code: string): number {
  return courseOrder(dept).get(code) ?? Number.MAX_SAFE_INTEGER
}
