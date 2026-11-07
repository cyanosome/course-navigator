/**
 * backend の API（約束の版 navi-v1、api-contract.md）を呼ぶ薄い関数。
 * 応答の JSON は境界なので unknown で受け、型の検査関数を通してから返す。失敗は ApiError で投げる。
 * 中断（AbortSignal）は投げ直すだけで ApiError にしない（呼び出し側が無視できるように）。
 */
import type {
  AssistIn,
  AssistOut,
  BulletinInfo,
  CourseDetail,
  CoursePage,
  CourseQuery,
  CourseSummary,
  DataStatus,
  DepartmentDataStatus,
  DepartmentGraph,
  DepartmentOverview,
  DepartmentSummary,
  DiagnoseConfig,
  DiagnoseEffect,
  DiagnoseOption,
  DiagnosePlanIn,
  DiagnosePlanOut,
  DiagnoseQuestion,
  GraduationRequirements,
  GroupEdge,
  GroupEdgeType,
  GroupNode,
  InterestOut,
  PlanCourse,
  PlanSuggestions,
  PlanTerm,
  RequirementsOut,
} from './apiTypes'
import { CONTRACT_VERSION } from './apiTypes'
import { isNumber, isRecord, isString, isStringArray } from './storage'
import type { AgentSource, AgentToolCall } from './types'

const API_BASE = '/api'
const CONTRACT_HEADER = 'X-Navi-Contract'

/* ---------- 失敗 ---------- */

/** http: 2xx 以外の応答、network: 通信の失敗（応答が無い）、shape: 応答が約束の形でない */
export type ApiErrorKind = 'http' | 'network' | 'shape'

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  /** HTTP の状態。通信の失敗なら null */
  readonly status: number | null
  /** 応答の detail（FastAPI の既定の形）。無ければ null */
  readonly detail: string | null

  constructor(kind: ApiErrorKind, status: number | null, detail: string | null, message: string, cause?: unknown) {
    super(message, { cause })
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.detail = detail
  }
}

/** 画面に出す1文（requirements R2-4 の書き分け） */
export function apiErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return '読み込めませんでした。'
  if (err.kind === 'network') return 'サーバーにつながりません。'
  if (err.kind === 'shape') return 'サーバーの応答を読めませんでした。'
  switch (err.status) {
    case 404:
      return '見つかりませんでした。'
    case 503:
      return 'データベースにつながりません。'
    case 504:
      return '時間内に返りませんでした。'
    case 409:
      return '今は受け付けられません。'
    case 422:
      return '問い合わせの形が正しくありません。'
    default:
      return 'サーバーのエラーです。'
  }
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}

/* ---------- 形の検査 ---------- */

type Guard<T> = (v: unknown) => v is T
/** T のすべての項目に検査関数を1つずつ（項目を足し忘れると型の誤りになる） */
type Shape<T> = { [K in keyof T]-?: Guard<T[K]> }

function shape<T>(spec: Shape<T>): Guard<T> {
  const keys = Object.keys(spec) as (keyof T & string)[]
  return (v: unknown): v is T => isRecord(v) && keys.every((k) => spec[k](v[k]))
}

function nullable<T>(guard: Guard<T>): Guard<T | null> {
  return (v: unknown): v is T | null => v === null || guard(v)
}

/** 項目が無くてもよい（古いサーバーが送らない項目） */
function optional<T>(guard: Guard<T>): Guard<T | undefined> {
  return (v: unknown): v is T | undefined => v === undefined || guard(v)
}

function arrayOf<T>(guard: Guard<T>): Guard<T[]> {
  return (v: unknown): v is T[] => Array.isArray(v) && v.every(guard)
}

function oneOf<const T extends string>(values: readonly T[]): Guard<T> {
  return (v: unknown): v is T => isString(v) && (values as readonly string[]).includes(v)
}

function isBoolean(v: unknown): v is boolean {
  return typeof v === 'boolean'
}

function isNumberRecord(v: unknown): v is Record<string, number> {
  return isRecord(v) && Object.values(v).every(isNumber)
}

const isNullableString = nullable(isString)
const isNullableNumber = nullable(isNumber)
const isAvailability = oneOf(['available', 'pending'])
const isKindCode = oneOf(['required', 'elective_required', 'elective'])
const isTerm = oneOf(['春', '秋', '通年'])
const isGroupEdgeType = oneOf<GroupEdgeType>(['prerequisite', 'capstone', 'english_track'])

const departmentSummaryShape: Shape<DepartmentSummary> = {
  id: isString,
  university: isString,
  faculty: isString,
  name: isString,
  syllabus_year: isNumber,
  data_version: isString,
  course_count: isNumber,
  group_count: isNumber,
}
const isDepartmentSummary = shape(departmentSummaryShape)

const isDataStatus = shape<DataStatus>({ status: isAvailability, reason: isNullableString })

const isDepartmentDataStatus = shape<DepartmentDataStatus>({
  requirements: isDataStatus,
  kinds: isDataStatus,
  classified_courses: isNumber,
  similar_to_edges: isNumber,
  similar_models: isStringArray,
  group_edges: isNumber,
})

const isDepartmentOverview = shape<DepartmentOverview>({ ...departmentSummaryShape, data_status: isDepartmentDataStatus })

const courseSummaryShape: Shape<CourseSummary> = {
  syllabus_id: isString,
  course_code: isString,
  name: isString,
  subtitle: isNullableString,
  group_id: isNullableString,
  year_min: isNullableNumber,
  year_max: isNullableNumber,
  year_range: isNullableString,
  term: nullable(isTerm),
  term_raw: isNullableString,
  slots: isStringArray,
  slot_note: isNullableString,
  credits: isNullableNumber,
  faculties: isStringArray,
  teacher: isNullableString,
  lead: isString,
  kind: nullable(isKindCode),
  detail_url: isNullableString,
}
const isCourseSummary = shape(courseSummaryShape)

const isGroupNode = shape<GroupNode>({
  group_id: isString,
  label: isString,
  name: isString,
  plain: isNullableString,
  common: isBoolean,
  academic_year: isNumber,
  semester: isNullableString,
  member_count: isNumber,
})

const isGroupEdge = shape<GroupEdge>({ source: isString, target: isString, edge_type: isGroupEdgeType, is_major: isBoolean })

const isInterestOut = shape<InterestOut>({
  id: isString,
  label: isString,
  targets: isStringArray,
  extras: arrayOf(shape({ syllabus_id: isString, why: isString, source: isString })),
})

const isDepartmentGraph = shape<DepartmentGraph>({
  department_id: isString,
  edge_types: isStringArray,
  groups: arrayOf(isGroupNode),
  edges: arrayOf(isGroupEdge),
  interests: arrayOf(isInterestOut),
  members: arrayOf(isCourseSummary),
})

const isCoursePage = shape<CoursePage>({
  total: isNumber,
  limit: isNumber,
  offset: isNumber,
  items: arrayOf(isCourseSummary),
  kinds_status: isAvailability,
})

const isBulletinInfo = shape<BulletinInfo>({
  subject_name_bulletin: isString,
  requirement_type: isKindCode,
  credits: isNumber,
  assigned_year: isNullableNumber,
  bulletin_code: isNullableString,
  field_category: isNullableString,
})

const isCourseDetail = shape<CourseDetail>({
  ...courseSummaryShape,
  academic_year: isNumber,
  description: isNullableString,
  objectives: isNullableString,
  schedule: arrayOf(shape({ number: isNullableNumber, topic: isString })),
  work_outside_class: isNullableString,
  grading_policy: isNullableString,
  evaluation_criteria: isNullableString,
  textbooks: isStringArray,
  textbook_notes: isNullableString,
  references: isStringArray,
  notes: isNullableString,
  instructors: arrayOf(shape({ name: isString, is_primary: isBoolean })),
  language: isNullableString,
  teaching_type: isNullableString,
  bulletin: nullable(isBulletinInfo),
  source: isString,
})

const isGraduationRequirements = shape<GraduationRequirements>({
  requirement_id: isString,
  academic_year: isNumber,
  total_credits: isNumber,
  buckets: arrayOf(shape({ key: isString, label: isString, credits: isNumber })),
  thesis: shape({
    max_unearned_required_courses: isNumber,
    max_unearned_required_credits: isNumber,
    min_major_elective_required_credits: isNumber,
    mandatory_courses_completed: isStringArray,
    prerequisite_course: isNullableString,
    raw_condition_text: isString,
  }),
  rules_notes: isStringArray,
  term_cap: isNullableNumber,
})

const isRequirementsOut = shape<RequirementsOut>({
  department_id: isString,
  status: isAvailability,
  reason: isNullableString,
  requirements: nullable(isGraduationRequirements),
  kinds: isDataStatus,
  kinds_count: isNumberRecord,
  source: isString,
})

const isAgentSource = shape<AgentSource>({
  code: isString,
  title: isString,
  instructor: isNullableString,
  schedule: isNullableString,
  credits: isNullableNumber,
  excerpt: isString,
  origin: isString,
  url: isNullableString,
})

const isAgentToolCall = shape<AgentToolCall>({ name: isString, args: isRecord, result_summary: isNullableString })

const isAssistOptions = shape({
  route: oneOf(['mcp_grounded', 'static']),
  style: oneOf(['standard', 'brief', 'detailed']),
  verify: oneOf(['on', 'off']),
  citations: oneOf(['cards', 'text']),
})

const isPlanSuggestion = shape({ syllabus_id: isString, title: isNullableString, reason: isString })

/** プランの微修正の提案（A1 の plan_suggestions）。端末に保存した回答を読み直すときにも使う */
export const isPlanSuggestions = shape<PlanSuggestions>({
  add: arrayOf(isPlanSuggestion),
  remove: arrayOf(isPlanSuggestion),
  dropped: arrayOf(
    shape({
      action: oneOf(['add', 'remove']),
      syllabus_id: isString,
      reason: oneOf(['not_in_db', 'already_in_plan', 'not_in_plan']),
    }),
  ),
})

const isAssistOut = shape<AssistOut>({
  route: oneOf(['mcp', 'static']),
  answer: isString,
  cited_codes: isStringArray,
  sources: arrayOf(isAgentSource),
  unverified_codes: isStringArray,
  notes: isStringArray,
  tool_calls: arrayOf(isAgentToolCall),
  node_sequence: isStringArray,
  model: isNullableString,
  latency_ms: isNumber,
  request_id: isString,
  variant_id: isNullableString,
  options_applied: isAssistOptions,
  options_ignored: isBoolean,
  route_requested: oneOf(['mcp_grounded', 'static']),
  unverified_items: arrayOf(shape({ code: isString, reason: oneOf(['not_in_db', 'lookup_failed']) })),
  plan_suggestions: optional(nullable(isPlanSuggestions)),
})

const isDiagnoseTerm = oneOf(['春', '秋'])

const isDiagnoseEffect = shape<DiagnoseEffect>({ primitive: isString, args: isRecord, weight: isNumber })

const isDiagnoseOption = shape<DiagnoseOption>({ id: isString, label: isString, effects: arrayOf(isDiagnoseEffect) })

const isDiagnoseQuestionBase = shape<Omit<DiagnoseQuestion, 'max_select'>>({
  id: isString,
  text: isString,
  kind: oneOf(['single', 'multi', 'scale5']),
  options: arrayOf(isDiagnoseOption),
})

/** max_select は multi のときだけ要る（それ以外は省いてよい） */
function isDiagnoseQuestion(v: unknown): v is DiagnoseQuestion {
  if (!isDiagnoseQuestionBase(v)) return false
  const max: unknown = (v as Record<string, unknown>).max_select
  if (v.kind === 'multi') return isNumber(max) && max >= 1
  return max === undefined || max === null || isNumber(max)
}

function isStringRecord(v: unknown): v is Record<string, string> {
  return isRecord(v) && Object.values(v).every(isString)
}

const isDiagnoseConfig = shape<DiagnoseConfig>({
  version: isString,
  department_id: isString,
  scope: shape({
    terms: arrayOf(shape({ year: isNumber, term: isDiagnoseTerm })),
    credit_cap_per_term: isNullableNumber,
  }),
  questions: arrayOf(isDiagnoseQuestion),
  base_effects: arrayOf(isDiagnoseEffect),
  tie_break: isString,
  reason_templates: isStringRecord,
})

const isPlanCourse = shape<PlanCourse>({
  syllabus_id: isString,
  name: isString,
  credits: isNullableNumber,
  slots: isStringArray,
  slot_note: isNullableString,
  score: isNumber,
  reasons: arrayOf(shape({ primitive: isString, text: isString })),
})

const isPlanTerm = shape<PlanTerm>({
  year: isNumber,
  term: isDiagnoseTerm,
  credits_total: isNumber,
  courses: arrayOf(isPlanCourse),
})

/** 端末に保存したプランを読み直すときにも使う */
export const isDiagnosePlanOut = shape<DiagnosePlanOut>({
  config_version: isString,
  answers_digest: isString,
  terms: arrayOf(isPlanTerm),
})

/* ---------- 呼び出し ---------- */

/** 応答の detail（FastAPI の既定 {"detail": …}）。読めなければ null */
async function readDetail(res: Response): Promise<string | null> {
  let body: unknown
  try {
    body = await res.json()
  } catch {
    return null // 本文が JSON でない（プロキシのエラー画面など）。状態の番号だけで書き分ける
  }
  if (!isRecord(body) || body.detail === undefined) return null
  return isString(body.detail) ? body.detail : JSON.stringify(body.detail)
}

async function request<T>(path: string, init: RequestInit, guard: Guard<T>, what: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers: { Accept: 'application/json', ...init.headers } })
  } catch (err) {
    if (isAbortError(err)) throw err
    throw new ApiError('network', null, null, `${what}: サーバーにつながりません`, err)
  }
  const contract = res.headers.get(CONTRACT_HEADER)
  if (contract !== null && contract !== CONTRACT_VERSION) {
    console.warn(`${what}: 約束の版が違います（受け取った ${contract}、画面は ${CONTRACT_VERSION}）`)
  }
  if (!res.ok) {
    throw new ApiError('http', res.status, await readDetail(res), `${what}: HTTP ${res.status}`)
  }
  let body: unknown
  try {
    body = await res.json()
  } catch (err) {
    if (isAbortError(err)) throw err
    throw new ApiError('shape', res.status, null, `${what}: 応答が JSON ではありません`, err)
  }
  if (!guard(body)) throw new ApiError('shape', res.status, null, `${what}: 応答の形が約束と違います`)
  return body
}

function get<T>(path: string, guard: Guard<T>, what: string, signal: AbortSignal): Promise<T> {
  return request(path, { signal }, guard, what)
}

const seg = encodeURIComponent

/** D1 */
export function listDepartments(signal: AbortSignal): Promise<DepartmentSummary[]> {
  return get('/departments', arrayOf(isDepartmentSummary), '学科の一覧', signal)
}

/** D2 */
export function getDepartment(deptId: string, signal: AbortSignal): Promise<DepartmentOverview> {
  return get(`/departments/${seg(deptId)}`, isDepartmentOverview, '学科の概要', signal)
}

/** D3。edgeTypes は rule_edges（F14）から決める */
export function getGraph(deptId: string, edgeTypes: readonly GroupEdgeType[], signal: AbortSignal): Promise<DepartmentGraph> {
  const q = new URLSearchParams({ edge_types: edgeTypes.join(',') })
  return get(`/departments/${seg(deptId)}/graph?${q.toString()}`, isDepartmentGraph, '系統図', signal)
}

/** D6 */
export function getRequirements(deptId: string, signal: AbortSignal): Promise<RequirementsOut> {
  return get(`/departments/${seg(deptId)}/requirements`, isRequirementsOut, '卒業要件', signal)
}

/** D4 のクエリの文字列（複数の値は同じ名前を繰り返す） */
export function courseQueryString(query: CourseQuery): string {
  const q = new URLSearchParams()
  const set = (key: string, value: string | number | undefined) => {
    if (value !== undefined) q.set(key, String(value))
  }
  const add = (key: string, values: readonly string[] | undefined) => {
    for (const v of values ?? []) q.append(key, v)
  }
  set('dept', query.dept)
  set('q', query.q)
  set('year', query.year)
  set('term', query.term)
  add('slot', query.slot)
  add('group', query.group)
  add('kind', query.kind)
  set('limit', query.limit)
  set('offset', query.offset)
  return q.toString()
}

/** D4 */
export function searchCourses(query: CourseQuery, signal: AbortSignal): Promise<CoursePage> {
  const qs = courseQueryString(query)
  return get(qs === '' ? '/courses' : `/courses?${qs}`, isCoursePage, '科目の検索', signal)
}

/** D5 */
export function getCourse(syllabusId: string, signal: AbortSignal): Promise<CourseDetail> {
  return get(`/courses/${seg(syllabusId)}`, isCourseDetail, '科目の詳細', signal)
}

/** A1 */
export function ask(input: AssistIn, signal: AbortSignal): Promise<AssistOut> {
  return request(
    '/assist/ask',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input), signal },
    isAssistOut,
    'AI の回答',
  )
}

/** 診断の設定の応答（設定の JSON は config にそのまま入る） */
const isDiagnoseConfigOut = shape<{ department_id: string; version: string; config: DiagnoseConfig }>({
  department_id: isString,
  version: isString,
  config: isDiagnoseConfig,
})

/** 診断の設定（応答の版と設定の中の版が違えば、どちらで答えるか決められないので形の誤りにする） */
export async function getDiagnoseConfig(deptId: string, signal: AbortSignal): Promise<DiagnoseConfig> {
  const q = new URLSearchParams({ department_id: deptId })
  const out = await get(`/diagnose/config?${q.toString()}`, isDiagnoseConfigOut, '診断の設定', signal)
  if (out.config.version !== out.version) {
    throw new ApiError('shape', 200, null, `診断の設定: 版が合いません（応答 ${out.version}、設定 ${out.config.version}）`)
  }
  return out.config
}

/** 診断の答えからプラン（422 は答えの誤り、409 は設定の版の違い。どちらも ApiError の status で分かる） */
export function makeDiagnosePlan(input: DiagnosePlanIn, signal: AbortSignal): Promise<DiagnosePlanOut> {
  return request(
    '/diagnose/plan',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input), signal },
    isDiagnosePlanOut,
    'プラン',
  )
}
