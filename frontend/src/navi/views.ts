/**
 * 学科データと状態から、一覧の行（W1・W2・W5・W13）と詳細（W3）の「なぜ」を作る（E1 1〜3章・8章）。
 */
import type { CourseSummary } from './apiTypes'
import { extractReasons } from './ask'
import { courseIndex, findCourse, findFrame, findInterest, hasEdge, interestGroups, reachedInterests, realInterests } from './graph'
import type { AskSession, Origin, TrailEntry } from './state'
import { courseHref, DIAGNOSE_HREF, groupHref, listHref, TIMETABLE_HREF } from './state'
import type { Placement, TermKey } from './timetable'
import {
  clashesOf,
  courseTermLabel,
  gradProgress,
  inTerm,
  isRequired,
  sameTerm,
  shortName,
  slotShort,
  termCredits as termCreditsOf,
  termLabel,
  termsOf,
} from './timetable'
import type { AgentSource, Course, Department, Interest } from './types'
import type { VariantFlags } from './variant'

/** 和文の区切りの全角空白（U+3000。例「月2」と「1年春は7単位」の間） */
export const WIDE_SPACE = '　'

/** 一覧の計算に使う状態 */
export interface ListContext {
  dept: Department
  shortlist: string[]
  /** いま見ている学期（重なりと学期の表記の基準） */
  focusTerm: TermKey
  /** 想定の時点の学期（おすすめを選ぶ学期） */
  assumedTerm: TermKey
  /** 変種の旗（graph・recommend）。省くと基準 V00 と同じ（系統図もおすすめも出す） */
  flags?: VariantFlags
  /** 時間割に置く科目の引き方（系統図に無い科目の引き方と、必修を最初から入れるか）。省くと系統図の科目と必修だけ */
  placement?: Placement
}

/** 一覧に使う興味関心。系統図を出さない変種（graph=off）では、URL に ?dir= があっても使わない */
export function listInterest(ctx: ListContext, dirId: string): Interest | undefined {
  if (ctx.flags?.graph === 'off') return undefined
  const interest = findInterest(ctx.dept, dirId)
  return interest === undefined || interest.targets.length === 0 ? undefined : interest
}

export interface RowView {
  code: string
  name: string
  faculty: string | null
  /** 左の列の1段目（曜限。2コマなら2行） */
  slotLines: string[]
  /** 左の列の2段目（単位）。記載が無ければ null */
  credits: number | null
  /** 左の列の3段目（学期）。いま見ている学期と違うときだけ */
  termNote: string | null
  learn: string
  learnMissing: boolean
  /** 同じ曜限に入っている科目（例 無機化学と重なる、3年春は無機化学と重なる） */
  clash: string | null
  why: string | null
  source: string | null
  href: string
  /** 学科の必修（＋を出さない。時間割に最初から入っている） */
  required: boolean
}

/** 授業でやること。概要が無ければ授業計画の最初の3回、どちらも無ければ「シラバスに記載なし」（E1 8章） */
export function learnText(course: Course): { text: string; missing: boolean } {
  if (course.learn !== '') return { text: course.learn, missing: false }
  if (course.summary !== '') return { text: course.summary, missing: false }
  if (course.plan.length > 0) {
    return {
      text: course.plan
        .slice(0, 3)
        .map((t, i) => `第${i + 1}回 ${t}`)
        .join(WIDE_SPACE),
      missing: false,
    }
  }
  return { text: 'シラバスに記載なし', missing: true }
}

/** 詳細の本文。概要 → 授業でやること → 授業計画の最初の3回 */
export function leadText(course: Course): { text: string; missing: boolean } {
  if (course.summary !== '') return { text: course.summary, missing: false }
  return learnText(course)
}

export function isOtherTerm(course: Course, focusTerm: TermKey): boolean {
  return !termsOf(course).some((t) => sameTerm(t, focusTerm))
}

/** 重なりの1行。いま見ている学期と違う学期の重なりは学期を添える */
export function clashText(ctx: ListContext, course: Course): string | null {
  const first = clashesOf(ctx.dept, ctx.shortlist, course, ctx.placement)[0]
  if (first === undefined) return null
  const prefix = sameTerm(first.term, ctx.focusTerm) ? '' : `${termLabel(first.term)}は`
  return `${prefix}${shortName(first.other)}と重なる`
}

export function rowView(ctx: ListContext, course: Course, origin: Origin, why: string | null, source: string | null): RowView {
  const learn = learnText(course)
  return {
    code: course.code,
    name: course.name,
    faculty: course.faculty,
    slotLines: slotShort(course),
    credits: course.credits,
    termNote: isOtherTerm(course, ctx.focusTerm) ? courseTermLabel(course) : null,
    learn: learn.text,
    learnMissing: learn.missing,
    clash: clashText(ctx, course),
    why,
    source,
    href: courseHref(course.code, origin),
    required: isRequired(course),
  }
}

/** 学科データに無い科目（自由記述の結果の sources だけで作る行。UX 仕様 W3 の注） */
export function sourceRowView(source: AgentSource, origin: Origin, why: string): RowView {
  return {
    code: source.code,
    name: source.title,
    faculty: null,
    slotLines: [source.schedule ?? 'なし'],
    credits: source.credits,
    termNote: null,
    learn: source.excerpt !== '' ? source.excerpt : 'シラバスに記載なし',
    learnMissing: source.excerpt === '',
    clash: null,
    why,
    source: 'AIの判断',
    href: courseHref(source.code, origin),
    required: false,
  }
}

/** 診断のプランの科目のうち、学科の系統図に無い科目の行（プランの項目だけで作る。学期はプランの見出しに出す） */
export function planRowView(
  c: { syllabus_id: string; name: string; credits: number | null; slots: string[]; slot_note: string | null },
  origin: Origin,
  why: string | null,
  source: string | null,
): RowView {
  return {
    code: c.syllabus_id,
    name: c.name,
    faculty: null,
    slotLines: c.slots.length > 0 ? c.slots : [c.slot_note === 'オンデマンド' ? '随時' : 'なし'],
    credits: c.credits,
    termNote: null,
    learn: '',
    learnMissing: false,
    clash: null,
    why,
    source,
    href: courseHref(c.syllabus_id, origin),
    required: false,
  }
}

/** キーワード検索の結果（D4 の1件）の行。学科の系統図に無い科目もあるので、API の項目だけで作る */
export function summaryRowView(item: CourseSummary, origin: Origin, focusTerm: TermKey): RowView {
  const term = item.year_min !== null && item.term !== null ? `${item.year_min}年${item.term}` : null
  const sameAsFocus = item.year_min === focusTerm.year && (item.term === focusTerm.half || item.term === '通年')
  return {
    code: item.syllabus_id,
    name: item.name,
    faculty: null,
    slotLines: item.slots.length > 0 ? item.slots : ['なし'],
    credits: item.credits,
    termNote: term !== null && !sameAsFocus ? term : null,
    learn: item.lead !== '' ? item.lead : 'シラバスに記載なし',
    learnMissing: item.lead === '',
    clash: null,
    why: null,
    source: null,
    href: courseHref(item.syllabus_id, origin),
    required: item.kind === 'required',
  }
}

/* ---------- おすすめ（W1） ---------- */

/** 系統図から言える「なぜ」（一覧の短い形） */
function reachWhy(dept: Department, course: Course): { why: string; source: string } {
  const reached = reachedInterests(dept, course.frameId)
  if (reached.length >= 2) return { why: `${reached.length}分野につながる`, source: '系統図' }
  const only = reached[0]
  if (only !== undefined) return { why: `「${only.label}」につながる`, source: '系統図' }
  if (course.faculty !== null) return { why: `${course.faculty}の科目`, source: 'シラバス' }
  return { why: '系統図に載っている科目', source: '系統図' }
}

interface Pick {
  course: Course
  why: string
  source: string
}

export interface DefaultList {
  rows: Pick[]
  more: Pick[]
  foot: string
  /** 卒業要件から選んだ1科目（無ければ null） */
  deficitCode: string | null
  /** 同点の並べ方（recommend_shown に残す）。reach_seeded は凍結の後に入れるので、いまは記載順 */
  tieBreak: 'catalog_order'
}

/** recommend=catalog の「なぜ」（まとまりの事実だけ。ab-variants.md F03） */
function catalogWhy(dept: Department, course: Course): { why: string; source: string } {
  const frame = findFrame(dept, course.frameId)
  if (frame !== undefined) return { why: `${frame.year}年の「${frame.name}」`, source: '系統図' }
  if (course.faculty !== null) return { why: `${course.faculty}の科目`, source: 'シラバス' }
  return { why: '系統図に載っている科目', source: '系統図' }
}

/** おすすめの、つながる分野の数で選ぶ科目の数（E1 の「多くの分野につながる順に2つ」） */
const REACH_PICKS = 2
/** 卒業要件から選ぶ区分（E1 5章: 教養が足りなければ、空いた曜限に入る教養や他学部の科目を1つ混ぜる） */
const DEFICIT_CATEGORY = '教養'

/**
 * おすすめ（W1）。想定の学期の、必修でない科目を、3年の分野へつながる数が多い順（同じなら系統図の記載順）に2つ。
 * 卒業要件があり、教養が足りなければ、必修と重ならない教養の科目（他学部を先）を1つ混ぜる。残りは「ほかに N 科目」。
 * 旗 recommend（ab-variants.md F03）: off は出さない（行が空）。catalog は同じ候補を記載順に並べ、「なぜ」はまとまりの事実だけ。
 * reach_seeded（同点を参加者ごとの種で並べ替える）は凍結の後に入れる。いまは reach と同じ並びで、tieBreak に記載順と残す。
 */
export function defaultList(ctx: ListContext): DefaultList {
  const { dept, shortlist, assumedTerm } = ctx
  const recommend = ctx.flags?.recommend ?? 'reach'
  if (recommend === 'off') return { rows: [], more: [], foot: '', deficitCode: null, tieBreak: 'catalog_order' }
  const candidates = dept.courses.filter((c) => !isRequired(c) && inTerm(c, assumedTerm))
  if (recommend === 'catalog') {
    const listed = candidates
      .sort((a, b) => courseIndex(dept, a.code) - courseIndex(dept, b.code))
      .map((c) => ({ course: c, ...catalogWhy(dept, c) }))
    const main = listed.slice(0, REACH_PICKS + 1)
    return { rows: main, more: listed.slice(main.length), foot: '系統図の記載順に出しています。', deficitCode: null, tieBreak: 'catalog_order' }
  }
  const ranked = candidates
    .map((c) => ({ course: c, count: reachedInterests(dept, c.frameId).length }))
    .sort((a, b) => b.count - a.count || courseIndex(dept, a.course.code) - courseIndex(dept, b.course.code))
    .map((r) => ({ course: r.course, ...reachWhy(dept, r.course) }))

  const progress = gradProgress(dept, shortlist, ctx.placement)
  const lack = progress?.find((p) => p.category === DEFICIT_CATEGORY)
  const remaining = lack === undefined ? 0 : lack.need - lack.placed
  const top = ranked.slice(0, REACH_PICKS)
  const deficit =
    remaining > 0
      ? ranked
          .slice(REACH_PICKS)
          .filter((p) => p.course.grad === DEFICIT_CATEGORY && clashesOf(dept, [], p.course).length === 0)
          .sort((a, b) => Number(b.course.faculty !== null) - Number(a.course.faculty !== null))[0]
      : undefined

  if (deficit === undefined) {
    const main = ranked.slice(0, REACH_PICKS + 1)
    return {
      rows: main,
      more: ranked.slice(main.length),
      foot: '3年の多くの分野につながる順に出しています。',
      deficitCode: null,
      tieBreak: 'catalog_order',
    }
  }
  const rows = [...top, { course: deficit.course, why: `${DEFICIT_CATEGORY}があと${remaining}単位`, source: '卒業要件' }]
  return {
    rows,
    more: ranked.filter((p) => !rows.some((r) => r.course.code === p.course.code)),
    foot: '3年の多くの分野につながる順に2つと、卒業に足りない区分から1つを出しています。',
    deficitCode: deficit.course.code,
    tieBreak: 'catalog_order',
  }
}

/* ---------- 一覧の最初の科目（PC は開いた時点で中央に出す。UX 仕様 S1 の PC） ---------- */

/** keywordActive: キーワード検索の結果を出している（結果は非同期に届くので、中央には出さない） */
export function firstListCode(
  ctx: ListContext,
  dirId: string,
  ask: AskSession | null,
  showAsk: boolean,
  keywordActive = false,
): string | null {
  if (showAsk && ask !== null && ask.status === 'done') {
    const s = ask.result?.sources[0]
    if (s !== undefined) return s.code
  }
  if (keywordActive) return null
  const interest = listInterest(ctx, dirId)
  if (interest !== undefined) return interestGroups(ctx.dept, interest)[0]?.rows[0]?.course.code ?? null
  return defaultList(ctx).rows[0]?.course.code ?? null
}

/* ---------- 詳細（W3）の「なぜ」 ---------- */

export interface DetailWhy {
  text: string
  source: string
  /** AI の判断（「間違うことがあります」の1文を添える） */
  ai: boolean
}

export const AI_WHY_FALLBACK = 'AIの説明の中で触れています'

function frameFact(dept: Department, course: Course): DetailWhy {
  const frame = findFrame(dept, course.frameId)
  if (frame !== undefined) {
    return { text: `${frame.year}年の「${frame.name}」のまとまりの科目です`, source: '履修系統図より', ai: false }
  }
  if (course.faculty !== null) {
    return { text: `${course.faculty}の科目で、この学科の系統図には載っていません`, source: `${dept.syllabusYear}年度シラバスより`, ai: false }
  }
  return { text: 'この学科の系統図には載っていない科目です', source: `${dept.syllabusYear}年度シラバスより`, ai: false }
}

export function detailWhy(ctx: ListContext, course: Course, origin: Origin, ask: AskSession | null): DetailWhy {
  const { dept } = ctx
  switch (origin.kind) {
    case 'default': {
      // おすすめの並びの説明は recommend=reach のときだけ（catalog・off は、まとまりの事実だけ）
      const recommend = ctx.flags?.recommend ?? 'reach'
      if (recommend === 'catalog' || recommend === 'off') return frameFact(dept, course)
      const list = defaultList(ctx)
      const progress = gradProgress(dept, ctx.shortlist, ctx.placement)?.find((p) => p.category === DEFICIT_CATEGORY)
      if (list.deficitCode === course.code && progress !== undefined) {
        return {
          text: `卒業に要る${DEFICIT_CATEGORY}が、あと${progress.need - progress.placed}単位あります。必修と重ならない${DEFICIT_CATEGORY}の科目です`,
          source: '卒業要件より（見本の数）',
          ai: false,
        }
      }
      const reached = reachedInterests(dept, course.frameId).length
      if (reached === 0) return frameFact(dept, course)
      return {
        text: `3年の${realInterests(dept).length}分野のうち、${reached}つへ線がつながる科目です`,
        source: '履修系統図より',
        ai: false,
      }
    }
    case 'dir': {
      const interest = findInterest(dept, origin.dirId)
      if (interest === undefined) return frameFact(dept, course)
      const extra = interest.extras.find((e) => e.code === course.code)
      if (extra !== undefined) return { text: `${extra.why}です`, source: `${dept.syllabusYear}年度シラバスより`, ai: false }
      const frame = findFrame(dept, course.frameId)
      if (frame === undefined) return frameFact(dept, course)
      if (interest.targets.includes(frame.id)) {
        return { text: `選んだ「${interest.label}」の${frame.year}年の科目です`, source: '履修系統図より', ai: false }
      }
      return { text: `選んだ「${interest.label}」へ、線をたどってつながる科目です`, source: '履修系統図より', ai: false }
    }
    case 'course': {
      const from = findCourse(dept, origin.code)
      if (from === undefined || from.frameId === null || course.frameId === null) return frameFact(dept, course)
      if (hasEdge(dept, course.frameId, from.frameId)) return { text: `${from.name}の前に取る科目です`, source: '履修系統図より', ai: false }
      if (hasEdge(dept, from.frameId, course.frameId)) return { text: `${from.name}のあとに続く科目です`, source: '履修系統図より', ai: false }
      if (from.frameId === course.frameId) return { text: `${from.name}と同じまとまりの科目です`, source: '履修系統図より', ai: false }
      return frameFact(dept, course)
    }
    case 'ask': {
      const result = ask !== null && ask.localId === origin.localId ? ask.result : null
      if (result === null) return frameFact(dept, course)
      return { text: extractReasons(result.answer).get(course.code) ?? AI_WHY_FALLBACK, source: '（AIの判断）', ai: true }
    }
    case 'tt':
      if (isRequired(course)) return { text: `学科で${courseTermLabel(course)}に取ると決まっている科目です`, source: `${dept.syllabusYear}年度シラバスの区分より`, ai: false }
      return { ...frameFact(dept, course), text: `あなたが候補に入れた科目です。${frameFact(dept, course).text}` }
    case 'group':
    case 'plan':
    case 'none':
      return frameFact(dept, course)
  }
}

/* ---------- 候補に入れたときの知らせ（E1 5章） ---------- */

export interface AddedNotice {
  main: string
  sub: string
  /** 読み上げ用の1文 */
  speech: string
}

/** shortlist は入れたあとの候補 */
export function addedNotice(
  dept: Department,
  shortlist: string[],
  course: Course,
  focusTerm: TermKey,
  placement: Placement = {},
): AddedNotice {
  const main = `${course.name}を候補に入れました`
  let sub: string
  if (inTerm(course, focusTerm)) {
    const credits = termCreditsOf(dept, shortlist, focusTerm, placement)
    const where = course.slots.length > 0 ? course.slots.join('・') : '曜限なし'
    sub = `${where}${WIDE_SPACE}${termLabel(focusTerm)}は${credits}単位`
  } else {
    const where = course.slots.length > 0 ? course.slots.join('・') : '曜限なし'
    const later = course.year > focusTerm.year ? '（先の学年）' : ''
    sub = `${courseTermLabel(course)} ${where}${later}`
  }
  return { main, sub, speech: `${main}。${sub.replace(WIDE_SPACE, '。')}です。` }
}

/* ---------- 来た一覧（パンくずの1段目、スマホの戻るの名前） ---------- */

export function rootEntry(dept: Department, origin: Origin): TrailEntry {
  switch (origin.kind) {
    case 'default':
      return { label: 'おすすめ', href: listHref('default') }
    case 'dir':
      return { label: findInterest(dept, origin.dirId)?.label ?? 'さがす', href: listHref(origin.dirId) }
    case 'ask':
      return { label: '探した結果', href: `/navi/ask/${encodeURIComponent(origin.localId)}` }
    case 'tt':
      return { label: '時間割', href: TIMETABLE_HREF }
    case 'plan':
      return { label: 'プラン', href: DIAGNOSE_HREF }
    case 'course': {
      const from = findCourse(dept, origin.code)
      return { label: from?.name ?? 'さがす', href: courseHref(origin.code, { kind: 'none' }) }
    }
    case 'group': {
      const frame = findFrame(dept, origin.frameId)
      return { label: frame?.name ?? 'さがす', href: groupHref(origin.frameId, { kind: 'none' }) }
    }
    case 'none':
      return { label: 'さがす', href: '/navi' }
  }
}
