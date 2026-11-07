/**
 * 診断（旗 diagnose=quiz）の純関数とデータ源。LLM は使わない（プランはサーバーのエンジンが決まった規則で組む）。
 * - 答えの検査と更新（single・multi・scale5）、設定が変わったときの答えの刈り込み、答えの要約
 * - 作業用のプラン（サーバーのプランの写しに、微修正で足し外しする）と、微修正で A1 に送る plan_context と文
 * - データ源: 本物は GET /api/diagnose/config と POST /api/diagnose/plan。開発ビルドで VITE_NAVI_DATA=fixture のときだけ
 *   見本（fixtureDiagnose.ts）を動的に読み込む。本番の束には入らない。
 * 設定の形は診断のコンペの事前登録（protocol.md の「設定の形」）。画面は設定から組み立て、質問の中身を持たない。
 */
import * as api from './api'
import type {
  DiagnoseAnswers,
  DiagnoseConfig,
  DiagnosePlanIn,
  DiagnosePlanOut,
  DiagnoseQuestion,
  DiagnoseTerm,
  EventPayload,
  JsonValue,
  PlanContextIn,
  PlanReason,
} from './apiTypes'
import { PLAN_CONTEXT_LIMITS } from './apiTypes'
import { isNumber, isRecord, isString, isStringArray } from './storage'
import type { Course, Department } from './types'

/* ---------- データ源 ---------- */

export interface DiagnoseSource {
  getConfig(deptId: string, signal: AbortSignal): Promise<DiagnoseConfig>
  makePlan(input: DiagnosePlanIn, signal: AbortSignal): Promise<DiagnosePlanOut>
}

export function createDiagnoseSource(): DiagnoseSource {
  if (import.meta.env.DEV && import.meta.env.VITE_NAVI_DATA === 'fixture') {
    const loading = import('./fixtureDiagnose').then((m) => m.createFixtureDiagnoseSource())
    return {
      getConfig: async (deptId, signal) => (await loading).getConfig(deptId, signal),
      makePlan: async (input, signal) => (await loading).makePlan(input, signal),
    }
  }
  return { getConfig: api.getDiagnoseConfig, makePlan: api.makeDiagnosePlan }
}

/* ---------- 答え ---------- */

export type DiagnoseAnswer = DiagnoseAnswers[string]

/** scale5 の答え。答えの n が n 番目の選択肢に当たる（設定は選択肢をちょうど5つ書く） */
export const SCALE_POINTS = [1, 2, 3, 4, 5] as const

function maxSelect(q: DiagnoseQuestion): number {
  return q.kind === 'single' ? 1 : (q.max_select ?? q.options.length)
}

/** その質問に読める答えがあるか（選択肢が設定にあり、重ならず、数が合う。scale5 は 1〜5 の整数） */
export function isAnswered(q: DiagnoseQuestion, a: DiagnoseAnswer | undefined): boolean {
  if (a === undefined) return false
  if (q.kind === 'scale5') return typeof a === 'number' && Number.isInteger(a) && a >= 1 && a <= SCALE_POINTS.length
  if (!Array.isArray(a)) return false
  const ids = new Set(q.options.map((o) => o.id))
  if (!a.every((id) => ids.has(id)) || new Set(a).size !== a.length) return false
  return a.length >= 1 && a.length <= maxSelect(q)
}

/** 答えていない最初の質問の番号（全部答えていれば -1） */
export function firstUnanswered(config: DiagnoseConfig, answers: DiagnoseAnswers): number {
  return config.questions.findIndex((q) => !isAnswered(q, answers[q.id]))
}

export function selectedIds(answers: DiagnoseAnswers, questionId: string): string[] {
  const a = answers[questionId]
  return Array.isArray(a) ? a : []
}

/** 選択肢を押したとき。single は置き換え、multi は足し外し（上限に達していれば足さない）。scale5 は変えない */
export function pickOption(q: DiagnoseQuestion, answers: DiagnoseAnswers, optionId: string): DiagnoseAnswers {
  if (q.kind === 'scale5') return answers
  if (q.kind === 'single') return { ...answers, [q.id]: [optionId] }
  const list = selectedIds(answers, q.id)
  if (list.includes(optionId)) {
    const rest = list.filter((id) => id !== optionId)
    if (rest.length > 0) return { ...answers, [q.id]: rest }
    const next = { ...answers }
    delete next[q.id]
    return next
  }
  if (list.length >= maxSelect(q)) return answers
  return { ...answers, [q.id]: [...list, optionId] }
}

/** multi で、上限に達しているので足せない選択肢か */
export function isPickBlocked(q: DiagnoseQuestion, answers: DiagnoseAnswers, optionId: string): boolean {
  if (q.kind !== 'multi') return false
  const list = selectedIds(answers, q.id)
  return !list.includes(optionId) && list.length >= maxSelect(q)
}

export function setScale(q: DiagnoseQuestion, answers: DiagnoseAnswers, value: number): DiagnoseAnswers {
  if (q.kind !== 'scale5') return answers
  return { ...answers, [q.id]: value }
}

/** 設定が変わったとき（409 で読み直した、保存した答えが古い）、今の設定で読める答えだけ残す */
export function pruneAnswers(config: DiagnoseConfig, answers: DiagnoseAnswers): DiagnoseAnswers {
  const kept: DiagnoseAnswers = {}
  for (const q of config.questions) {
    const a = answers[q.id]
    if (a !== undefined && isAnswered(q, a)) kept[q.id] = a
  }
  return kept
}

/** 答えの1件の文（選んだ選択肢の文を「・」でつなぐ。scale5 は n 番目の選択肢の文） */
export function answerText(q: DiagnoseQuestion, a: DiagnoseAnswer | undefined): string {
  if (a === undefined) return ''
  if (typeof a === 'number') return q.options[a - 1]?.label ?? `${a}（${SCALE_POINTS.length}段階）`
  return a.map((id) => q.options.find((o) => o.id === id)?.label ?? id).join('・')
}

export interface AnswerSummaryItem {
  question_id: string
  question: string
  answer: string
}

/** 答えの要約（設定の質問の順。答えていない質問は入れない） */
export function answersSummary(config: DiagnoseConfig, answers: DiagnoseAnswers): AnswerSummaryItem[] {
  return config.questions
    .filter((q) => isAnswered(q, answers[q.id]))
    .map((q) => ({ question_id: q.id, question: q.text, answer: answerText(q, answers[q.id]) }))
}

/** 端末に保存した答えの形 */
export function isDiagnoseAnswers(v: unknown): v is DiagnoseAnswers {
  return isRecord(v) && Object.values(v).every((a) => isNumber(a) || isStringArray(a))
}

/** 研究のログに載せる答え（そのままの形。single・multi は選択肢の ID、scale5 は数） */
export function answersPayload(answers: DiagnoseAnswers): EventPayload {
  const out: EventPayload = {}
  for (const [id, a] of Object.entries(answers)) out[id] = Array.isArray(a) ? [...a] : a
  return out
}

/* ---------- 作業用のプラン ---------- */

export interface WorkingCourse {
  syllabus_id: string
  name: string
  credits: number | null
  slots: string[]
  slot_note: string | null
  /** 診断の点。微修正で足した科目は null */
  score: number | null
  reasons: PlanReason[]
  /** diagnose: 診断が選んだ、refine: 微修正の AI の回答から足した */
  origin: 'diagnose' | 'refine'
}

export interface WorkingTerm {
  year: number
  term: DiagnoseTerm
  courses: WorkingCourse[]
}

export interface WorkingPlan {
  terms: WorkingTerm[]
}

function isWorkingCourse(v: unknown): v is WorkingCourse {
  return (
    isRecord(v) &&
    isString(v.syllabus_id) &&
    isString(v.name) &&
    (v.credits === null || isNumber(v.credits)) &&
    isStringArray(v.slots) &&
    (v.slot_note === null || isString(v.slot_note)) &&
    (v.score === null || isNumber(v.score)) &&
    Array.isArray(v.reasons) &&
    v.reasons.every((r) => isRecord(r) && isString(r.primitive) && isString(r.text)) &&
    (v.origin === 'diagnose' || v.origin === 'refine')
  )
}

/** 端末に保存した作業用のプランの形 */
export function isWorkingPlan(v: unknown): v is WorkingPlan {
  return (
    isRecord(v) &&
    Array.isArray(v.terms) &&
    v.terms.every(
      (t) => isRecord(t) && isNumber(t.year) && (t.term === '春' || t.term === '秋') && Array.isArray(t.courses) && t.courses.every(isWorkingCourse),
    )
  )
}

const TERM_ORDER: Record<DiagnoseTerm, number> = { 春: 0, 秋: 1 }

function compareTerm(a: { year: number; term: DiagnoseTerm }, b: { year: number; term: DiagnoseTerm }): number {
  return a.year - b.year || TERM_ORDER[a.term] - TERM_ORDER[b.term]
}

export function planTermLabel(t: { year: number; term: DiagnoseTerm }): string {
  return `${t.year}年${t.term}`
}

/** サーバーのプランから作業用のプランへ（学期は早い順） */
export function toWorkingPlan(plan: DiagnosePlanOut): WorkingPlan {
  return {
    terms: [...plan.terms].sort(compareTerm).map((t) => ({
      year: t.year,
      term: t.term,
      courses: t.courses.map((c) => ({ ...c, reasons: [...c.reasons], origin: 'diagnose' as const })),
    })),
  }
}

export function planCodes(plan: WorkingPlan): string[] {
  return plan.terms.flatMap((t) => t.courses.map((c) => c.syllabus_id))
}

export function inPlan(plan: WorkingPlan, code: string): boolean {
  return plan.terms.some((t) => t.courses.some((c) => c.syllabus_id === code))
}

export function findPlanCourse(plan: WorkingPlan, code: string): { term: WorkingTerm; course: WorkingCourse } | undefined {
  for (const term of plan.terms) {
    const course = term.courses.find((c) => c.syllabus_id === code)
    if (course !== undefined) return { term, course }
  }
  return undefined
}

/** 学期の単位の合計（単位の分からない科目は数えず、その数を unknown に） */
export function workingTermCredits(term: WorkingTerm): { credits: number; unknown: number } {
  return {
    credits: term.courses.reduce((n, c) => n + (c.credits ?? 0), 0),
    unknown: term.courses.filter((c) => c.credits === null).length,
  }
}

/**
 * 科目をプランに足す（微修正の AI の回答から）。入れる学期は科目の配当の学年と学期（通年は春に置く）。
 * その学期がプランに無ければ学期を足す。もう入っていれば変えない
 */
export function addCourseToPlan(plan: WorkingPlan, course: Course): WorkingPlan {
  if (inPlan(plan, course.code)) return plan
  const term: DiagnoseTerm = course.term === '秋' ? '秋' : '春'
  const entry: WorkingCourse = {
    syllabus_id: course.code,
    name: course.name,
    credits: course.credits,
    slots: course.slots,
    slot_note: course.slotNote,
    score: null,
    reasons: [],
    origin: 'refine',
  }
  const exists = plan.terms.some((t) => t.year === course.year && t.term === term)
  const terms = exists
    ? plan.terms.map((t) => (t.year === course.year && t.term === term ? { ...t, courses: [...t.courses, entry] } : t))
    : [...plan.terms, { year: course.year, term, courses: [entry] }].sort(compareTerm)
  return { terms }
}

/** 科目をプランから外す（学期は残す。空の学期も「この学期は空き」と分かるように） */
export function removeCourseFromPlan(plan: WorkingPlan, code: string): WorkingPlan {
  if (!inPlan(plan, code)) return plan
  return { terms: plan.terms.map((t) => ({ ...t, courses: t.courses.filter((c) => c.syllabus_id !== code) })) }
}

/** 研究のログに載せるプラン（学期ごとの syllabus_id） */
export function planPayload(plan: WorkingPlan): JsonValue {
  return plan.terms.map((t) => ({ year: t.year, term: t.term, syllabus_ids: t.courses.map((c) => c.syllabus_id) }))
}

/* ---------- 微修正（A1 に送るもの） ---------- */

/** 答えの要約を1つの文に（plan_context の answers_summary。上限を超えたら切る） */
export function summaryText(summary: AnswerSummaryItem[]): string {
  const text = summary.map((s) => `${s.question}→${s.answer}`).join('／')
  return text.length > PLAN_CONTEXT_LIMITS.summaryChars ? text.slice(0, PLAN_CONTEXT_LIMITS.summaryChars) : text
}

/**
 * A1 の plan_context。サーバーの上限（学期の数・学期ごとの科目の数・学年・要約の字数）に収める。
 * 収めるために落としたものがあれば clamped を true にする（記録に残す）
 */
export function planContext(plan: WorkingPlan, summary: AnswerSummaryItem[]): { context: PlanContextIn; clamped: boolean } {
  const inRange = plan.terms.filter((t) => t.year >= 1 && t.year <= PLAN_CONTEXT_LIMITS.yearMax)
  const terms = inRange.slice(0, PLAN_CONTEXT_LIMITS.terms).map((t) => ({
    year: t.year,
    term: t.term,
    syllabus_ids: t.courses.slice(0, PLAN_CONTEXT_LIMITS.idsPerTerm).map((c) => c.syllabus_id),
  }))
  const fullSummary = summary.map((s) => `${s.question}→${s.answer}`).join('／')
  const clamped =
    inRange.length !== plan.terms.length ||
    inRange.length > PLAN_CONTEXT_LIMITS.terms ||
    inRange.some((t) => t.courses.length > PLAN_CONTEXT_LIMITS.idsPerTerm) ||
    fullSummary.length > PLAN_CONTEXT_LIMITS.summaryChars
  return { context: { answers_summary: summaryText(summary), terms }, clamped }
}

/** A1 の question の上限（backend の AssistIn の max_length） */
export const QUESTION_MAX_CHARS = 2000

/**
 * 微修正の頼みを、学科を付けた1文にする。plan_context で送るときはプランを文に入れない（サーバーが DB で引いて付ける）。
 * withPlan: plan_context を断られたときの送り直しで、プランと答えの要約を文に入れる。上限を超えるときは、
 * プランの行を後ろから「ほか N 科目」にまとめる
 */
export function composeRefineQuestion(
  dept: Department,
  request: string,
  withPlan: { plan: WorkingPlan; summary: AnswerSummaryItem[] } | null,
): string {
  const head = `${dept.university} ${dept.faculty} ${dept.name}の学生です。`
  const tail =
    `頼みたいこと:『${request}』。` +
    'この頼みに合わせて、いまのプランに足す科目と外す科目を、この学科で取れる科目から挙げてください。' +
    '難しさや単位の取りやすさにはデータが無いので答えないでください'
  if (withPlan === null) return `${head}診断で出た履修プランを直したいです。${tail}`
  const { plan, summary } = withPlan
  const answers = summary.length === 0 ? '' : `診断の答え: ${summaryText(summary)}`
  const lines = plan.terms.map(
    (t) => `${planTermLabel(t)}: ${t.courses.length === 0 ? '（なし）' : t.courses.map((c) => `${c.name} [${c.syllabus_id}]`).join('、')}`,
  )
  const build = (planLines: string[]) =>
    [`${head}診断で次の履修プランが出ました。`, ...planLines, answers, tail].filter((x) => x !== '').join('\n')
  let text = build(lines)
  if (text.length <= QUESTION_MAX_CHARS) return text
  // 長すぎるときは、後ろの学期から1行ずつ「ほか N 科目」にまとめる
  const kept = [...lines]
  let dropped = 0
  while (kept.length > 0) {
    const last = plan.terms[kept.length - 1]
    kept.pop()
    dropped += last?.courses.length ?? 0
    text = build([...kept, `ほか${dropped}科目`])
    if (text.length <= QUESTION_MAX_CHARS) return text
  }
  return text.slice(0, QUESTION_MAX_CHARS)
}
