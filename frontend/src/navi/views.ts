/**
 * 学科データと状態から、画面に出す提案カードの中身と「なぜ」の文を作る（UX 仕様 7.2 の書き分け）。
 */
import type { AskSession, Origin, PaneState, PcTab } from './state'
import { courseHref } from './state'
import type { Course, Department, Direction, EvidenceKind, Frame } from './types'
import { extractReasons } from './ask'
import {
  defaultProposals,
  findCourse,
  findDirection,
  findFrame,
  hasEdge,
  realDirections,
  reachedDirectionCount,
  termLabel,
} from './graph'
import type { StageFrame } from './graph'

export interface ProposalView {
  code: string
  name: string
  /** 学期・曜限・単位（例 1年春・月2・2単位） */
  meta: string
  /** 「なぜ:」または「なぜ（AIの説明より）:」 */
  whyLabel: string
  why: string
  evidence: EvidenceKind
  /** 根拠のラベルの横の補足（例 同じ枠にほかに2科目） */
  aside?: string
  href: string
  linkState: PaneState
}

export function courseMeta(course: Course): string {
  return `${termLabel(course)}・${course.slot}・${course.credits}単位`
}

/** 左の一覧（またはスマホの一覧）から詳細へ進むときの履歴の state。道筋はその科目から始まる */
export function rootState(label: string, href: string, tab: PcTab): PaneState {
  return { trail: [{ label, href }], tab }
}

function view(course: Course, origin: Origin, why: string, tab: PcTab, aside?: string): ProposalView {
  const href = courseHref(course.code, origin)
  return {
    code: course.code,
    name: course.name,
    meta: courseMeta(course),
    whyLabel: 'なぜ:',
    why,
    evidence: 'route',
    aside,
    href,
    linkState: rootState(course.name, href, tab),
  }
}

export function directionsReachedText(dept: Department, count: number): string {
  return `この科目の枠から、3年の${realDirections(dept).length}つの方向のうち${count}つへ線がつながっています`
}

/** 既定の提案（W1） */
export function defaultViews(dept: Department, year: number): ProposalView[] {
  return defaultProposals(dept, year).map((p) =>
    view(
      p.course,
      { kind: 'default' },
      directionsReachedText(dept, p.directionCount),
      'search',
      p.othersInFrame > 0 ? `同じ枠にほかに${p.othersInFrame}科目` : undefined,
    ),
  )
}

/** PC の一覧の短い「なぜ」（W11 のワイヤーフレーム） */
export function defaultShortWhy(dept: Department, course: Course): string {
  return `${reachedDirectionCount(dept, course.frameId)}つの方向へ線がつながる枠`
}

export function stageCardWhy(sf: StageFrame): string {
  return sf.isTarget ? `あなたが選んだ方向の枠（${sf.frame.name}）の科目です` : '選んだ方向の枠へ、この枠から線がつながっています'
}

/** 方向を選んだあとの段の中の科目（W2） */
export function stageViews(direction: Direction, sf: StageFrame): ProposalView[] {
  return sf.shown.map((c) => view(c, { kind: 'dir', dirId: direction.id }, stageCardWhy(sf), 'search'))
}

/** 枠の科目（W13）のカードの「なぜ」 */
export function groupCardWhy(dept: Department, frame: Frame, origin: Origin): string {
  if (origin.kind === 'course') {
    const from = findCourse(dept, origin.code)
    if (from !== undefined) {
      if (hasEdge(dept, from.frameId, frame.id)) return `${from.name}の枠から線がつながる枠の科目です`
      if (hasEdge(dept, frame.id, from.frameId)) return `${from.name}の枠へ線がつながる枠（先に取っておく枠）の科目です`
      if (from.frameId === frame.id) return `${from.name}と同じ枠の科目です`
    }
  }
  if (origin.kind === 'dir') {
    const dir = findDirection(dept, origin.dirId)
    if (dir !== undefined && dir.targets.includes(frame.id)) return `あなたが選んだ方向の枠（${frame.name}）の科目です`
    if (dir !== undefined) return '選んだ方向の枠へ、この枠から線がつながっています'
  }
  if (origin.kind === 'shortlist') return '候補の科目の枠へ線がつながる枠の科目です'
  return `系統図の${frame.year}年「${frame.name}」の枠の科目です`
}

export function groupViews(dept: Department, frame: Frame, courses: Course[], origin: Origin, tab: PcTab): ProposalView[] {
  const why = groupCardWhy(dept, frame, origin)
  // 枠の科目から詳細へ進むときは、元の文脈（どこから来たか）を引き継ぐ
  return courses.map((c) => view(c, origin.kind === 'none' ? { kind: 'none' } : origin, why, tab))
}

export const AI_WHY_FALLBACK = 'AIの説明の中で触れています'

/** 自由記述の結果（W5-3）。カードにするのは DB で確かめられた科目（sources）だけ（UX 仕様 7.4） */
export function askViews(dept: Department, session: AskSession, tab: PcTab): ProposalView[] {
  const result = session.result
  if (result === null) return []
  const reasons = extractReasons(result.answer)
  const origin: Origin = { kind: 'ask', localId: session.localId }
  return result.sources.map((s) => {
    const course = findCourse(dept, s.code)
    const href = courseHref(s.code, origin)
    const meta =
      course !== undefined
        ? courseMeta(course)
        : [s.schedule, s.credits === null ? null : `${s.credits}単位`].filter((x) => x !== null).join('・')
    return {
      code: s.code,
      name: course?.name ?? s.title,
      meta,
      whyLabel: 'なぜ（AIの説明より）:',
      why: reasons.get(s.code) ?? AI_WHY_FALLBACK,
      evidence: 'ai' as const,
      aside: '間違うことがあります。詳細の抜粋と照らしてください',
      href,
      linkState: rootState(course?.name ?? s.title, href, tab),
    }
  })
}

export interface DetailWhy {
  /** AI の説明（自由記述から来たときだけ） */
  ai: string | null
  /** 系統図から言えること */
  route: string
}

/** 詳細（W3）の「なぜ出てきたか」（UX 仕様 7.2） */
export function detailWhy(dept: Department, course: Course, origin: Origin, ask: AskSession | null): DetailWhy {
  const frame = findFrame(dept, course.frameId)
  const frameText = frame === undefined ? '' : `${frame.year}年「${frame.name}」`
  const fact = `系統図では、${frameText}の枠の科目です`
  switch (origin.kind) {
    case 'default':
      return { ai: null, route: directionsReachedText(dept, reachedDirectionCount(dept, course.frameId)) }
    case 'dir': {
      const dir = findDirection(dept, origin.dirId)
      if (dir === undefined || frame === undefined) return { ai: null, route: fact }
      if (dir.targets.includes(frame.id))
        return { ai: null, route: `あなたが選んだ方向「${dir.label}」の枠（${frame.name}）の科目です` }
      return { ai: null, route: `あなたが選んだ方向「${dir.label}」の枠へ、この科目の枠（${frame.name}）から線がつながっています` }
    }
    case 'course': {
      const from = findCourse(dept, origin.code)
      if (from === undefined || frame === undefined) return { ai: null, route: fact }
      if (hasEdge(dept, from.frameId, frame.id)) return { ai: null, route: `${from.name}の枠から線がつながる枠の科目です` }
      if (hasEdge(dept, frame.id, from.frameId))
        return { ai: null, route: `${from.name}の枠へ線がつながる枠（先に取っておく枠）の科目です` }
      if (from.frameId === frame.id) return { ai: null, route: `${from.name}と同じ枠の科目です` }
      return { ai: null, route: fact }
    }
    case 'ask': {
      const result = ask !== null && ask.localId === origin.localId ? ask.result : null
      const reason = result === null ? null : (extractReasons(result.answer).get(course.code) ?? AI_WHY_FALLBACK)
      return { ai: reason, route: fact }
    }
    case 'shortlist':
      return { ai: null, route: `あなたが候補に残した科目です。${fact}` }
    case 'none':
      return { ai: null, route: fact }
  }
}
