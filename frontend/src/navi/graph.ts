/**
 * 学科データ（系統図の枠・線・科目）から、画面に出す提案と並びを決まった規則で計算する（UX 仕様 9.4 F3）。
 * LLM は使わない。どの関数も入力だけで結果が決まる。
 */
import type { Course, Department, Direction, Frame, Term } from './types'

const TERM_ORDER: Record<Term, number> = { 春: 0, 秋: 1, 通年: 2 }
/** 1度に見せる提案の数（UX 仕様 3.2 原則3） */
export const SHOWN_PER_GROUP = 3

export function findCourse(dept: Department, code: string): Course | undefined {
  return dept.courses.find((c) => c.code === code)
}

export function findFrame(dept: Department, id: string): Frame | undefined {
  return dept.frames.find((f) => f.id === id)
}

export function findDirection(dept: Department, id: string): Direction | undefined {
  return dept.directions.find((d) => d.id === id)
}

/** 既定（まず見ておきたい）以外の方向 */
export function realDirections(dept: Department): Direction[] {
  return dept.directions.filter((d) => d.targets.length > 0)
}

export function termLabel(course: Course): string {
  return `${course.year}年${course.term}`
}

export function frameLabel(frame: Frame): string {
  return `${frame.year}年 ${frame.name}`
}

/** 枠の中の並び: 学期（春が先）→ 系統図の記載順（UX 仕様 3.7・3.8、C24） */
export function coursesInFrame(dept: Department, frameId: string): Course[] {
  const order = new Map(dept.courses.map((c, i) => [c.code, i]))
  return dept.courses
    .filter((c) => c.frameId === frameId)
    .sort((a, b) => TERM_ORDER[a.term] - TERM_ORDER[b.term] || (order.get(a.code) ?? 0) - (order.get(b.code) ?? 0))
}

function frameOrder(dept: Department, id: string): number {
  return dept.frames.findIndex((f) => f.id === id)
}

function byFrameOrder(dept: Department, frames: Frame[]): Frame[] {
  return [...frames].sort((a, b) => frameOrder(dept, a.id) - frameOrder(dept, b.id))
}

/** その枠から線が出ていく先の枠（つながる先の枠） */
export function nextFrames(dept: Department, frameId: string): Frame[] {
  const ids = dept.edges.filter((e) => e.from === frameId).map((e) => e.to)
  return byFrameOrder(dept, dept.frames.filter((f) => ids.includes(f.id)))
}

/** その枠に線が入ってくる側の枠（先に取っておく枠） */
export function prevFrames(dept: Department, frameId: string): Frame[] {
  const ids = dept.edges.filter((e) => e.to === frameId).map((e) => e.from)
  return byFrameOrder(dept, dept.frames.filter((f) => ids.includes(f.id)))
}

export function hasEdge(dept: Department, from: string, to: string): boolean {
  return dept.edges.some((e) => e.from === from && e.to === to)
}

/** 線を下流へたどって届く枠（自分を含む） */
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

/** 線を上流へたどって届く枠（起点を含む） */
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

/** その枠から届く方向の数（方向のどれか1つの枠に届けば、その方向に届いたと数える。UX 仕様 3.7） */
export function reachedDirectionCount(dept: Department, frameId: string): number {
  const reach = downstream(dept, frameId)
  return realDirections(dept).filter((d) => d.targets.some((t) => reach.has(t))).length
}

export interface DefaultProposal {
  course: Course
  frame: Frame
  directionCount: number
  othersInFrame: number
}

/**
 * 既定の提案「まず見ておきたい科目」（UX 仕様 3.7）。
 * 想定の学年の枠を、届く方向の数→学科の枠を先→届く枠の総数→記載順で並べ、上位3枠から1科目ずつ出す。
 */
export function defaultProposals(dept: Department, year: number): DefaultProposal[] {
  const frames = dept.frames.filter((f) => f.year === year)
  const ranked = frames
    .map((frame) => ({
      frame,
      count: reachedDirectionCount(dept, frame.id),
      reach: downstream(dept, frame.id).size,
      order: frameOrder(dept, frame.id),
    }))
    .sort(
      (a, b) =>
        b.count - a.count ||
        Number(a.frame.common) - Number(b.frame.common) ||
        b.reach - a.reach ||
        a.order - b.order,
    )
  const out: DefaultProposal[] = []
  for (const r of ranked) {
    if (out.length >= SHOWN_PER_GROUP) break
    const courses = coursesInFrame(dept, r.frame.id)
    const first = courses[0]
    if (first === undefined) continue
    out.push({ course: first, frame: r.frame, directionCount: r.count, othersInFrame: courses.length - 1 })
  }
  return out
}

export interface StageFrame {
  frame: Frame
  /** この段で見せる科目（段で3件まで） */
  shown: Course[]
  total: number
  isTarget: boolean
}

export interface DirectionStage {
  year: number
  frames: StageFrame[]
  /** この段の「なぜ」（UX 仕様 3.8） */
  why: string
}

function quoteNames(frames: Frame[]): string {
  return frames.map((f) => `「${f.name}」`).join('')
}

/** 方向へ至る科目を、1年→2年→3年の段に分けて並べる（UX 仕様 3.8、C02） */
export function directionStages(dept: Department, direction: Direction): DirectionStage[] {
  const onPath = upstream(dept, direction.targets)
  const frames = byFrameOrder(dept, dept.frames.filter((f) => onPath.has(f.id)))
  const years = [...new Set(frames.map((f) => f.year))].sort((a, b) => a - b)
  return years.map((year) => {
    const stageFrames = frames.filter((f) => f.year === year)
    const lists = stageFrames.map((f) => coursesInFrame(dept, f.id))
    const shown = roundRobin(lists.slice(0, SHOWN_PER_GROUP), SHOWN_PER_GROUP)
    const items: StageFrame[] = stageFrames.map((frame, i) => ({
      frame,
      shown: shown.filter((c) => c.frameId === frame.id),
      total: lists[i]?.length ?? 0,
      isTarget: direction.targets.includes(frame.id),
    }))
    return { year, frames: items, why: stageWhy(dept, items, onPath) }
  })
}

/** 段の中の枠から、先頭を1件ずつ順に取り、上限になるまで繰り返す */
function roundRobin(lists: Course[][], limit: number): Course[] {
  const out: Course[] = []
  for (let i = 0; out.length < limit; i++) {
    let added = false
    for (const list of lists) {
      const c = list[i]
      if (c !== undefined && out.length < limit) {
        out.push(c)
        added = true
      }
    }
    if (!added) break
  }
  return out
}

function stageWhy(dept: Department, items: StageFrame[], onPath: Set<string>): string {
  const parts: string[] = []
  const targets = items.filter((i) => i.isTarget).map((i) => i.frame.name)
  if (targets.length > 0) parts.push(`あなたが選んだ方向の枠（${targets.join('、')}）`)
  const stageIds = new Set(items.map((i) => i.frame.id))
  const year = items[0]?.frame.year ?? 0
  const next = dept.frames.filter(
    (f) => onPath.has(f.id) && f.year > year && [...stageIds].some((id) => hasEdge(dept, id, f.id)),
  )
  if (next.length > 0) {
    const nextYears = [...new Set(next.map((f) => f.year))].sort((a, b) => a - b)
    const phrase = nextYears
      .map((y) => `${y}年の${quoteNames(byFrameOrder(dept, next.filter((f) => f.year === y)))}`)
      .join('、')
    parts.push(`この段の枠から${phrase}へ線がつながる`)
  }
  return parts.join('。')
}

/** 方向の説明の2行目（例:（3年の「応用化学工学系」の枠）） */
export function directionTargetsLabel(dept: Department, direction: Direction): string {
  const frames = direction.targets
    .map((t) => findFrame(dept, t))
    .filter((f): f is Frame => f !== undefined)
  return `（${frames.map((f) => `${f.year}年の「${f.name}」`).join('、')}の枠）`
}

/** 候補の並び: 学年→学期→記載順 */
export function sortCourses(dept: Department, courses: Course[]): Course[] {
  const order = new Map(dept.courses.map((c, i) => [c.code, i]))
  return [...courses].sort(
    (a, b) =>
      a.year - b.year ||
      TERM_ORDER[a.term] - TERM_ORDER[b.term] ||
      (order.get(a.code) ?? 0) - (order.get(b.code) ?? 0),
  )
}

export interface GapNotice {
  /** 候補の科目がある枠 */
  later: Frame
  /** その前にあって、候補が無い枠 */
  missing: Frame
}

/**
 * 候補の枠の前に、間の段の枠で候補が無いもの（UX 仕様 W4、C13）。
 * 想定の学年より後で、候補の枠より前の学年の「先に取っておく枠」だけを見る。
 */
export function gapNotices(dept: Department, candidates: Course[], assumedYear: number): GapNotice[] {
  const keptFrames = new Set(candidates.map((c) => c.frameId))
  const out: GapNotice[] = []
  const seen = new Set<string>()
  for (const c of sortCourses(dept, candidates)) {
    const later = findFrame(dept, c.frameId)
    if (later === undefined || seen.has(later.id)) continue
    seen.add(later.id)
    for (const p of prevFrames(dept, later.id)) {
      if (p.year > assumedYear && p.year < later.year && !keptFrames.has(p.id)) out.push({ later, missing: p })
    }
  }
  return out
}
