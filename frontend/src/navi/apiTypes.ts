/**
 * backend の API（約束の版 navi-v1）の応答と入力の型。項目名は API のまま snake_case で写す。
 * 画面の型（types.ts、camelCase）への写像は mapping.ts の純関数でする。
 * 正本は backend の Pydantic の型（course_core/schemas/catalog.py・research.py、agent/route_options.py）。
 */
import type { McpAgentRunResult } from './types'
import type { VariantFlags } from './variant'

/** 応答のヘッダ X-Navi-Contract の値 */
export const CONTRACT_VERSION = 'navi-v1'

/* ---------- データ（D1〜D6） ---------- */

/** D1 GET /api/departments の1件 */
export interface DepartmentSummary {
  id: string
  university: string
  faculty: string
  name: string
  syllabus_year: number
  data_version: string
  course_count: number
  group_count: number
}

export interface DataStatus {
  status: 'available' | 'pending'
  /** pending の理由（"表が無い"・"この学科の行が無い"） */
  reason: string | null
}

export interface DepartmentDataStatus {
  requirements: DataStatus
  kinds: DataStatus
  classified_courses: number
  similar_to_edges: number
  similar_models: string[]
  group_edges: number
}

/** D2 GET /api/departments/{dept_id} */
export interface DepartmentOverview extends DepartmentSummary {
  data_status: DepartmentDataStatus
}

export type GroupEdgeType = 'prerequisite' | 'capstone' | 'english_track'

export interface GroupNode {
  group_id: string
  /** 系統図の表記（例 【物理化学系グループ】） */
  label: string
  /** 画面の表記 */
  name: string
  /** 「なぜ」の文で使う短い呼び名（無ければ null） */
  plain: string | null
  common: boolean
  /** 学年（1〜4） */
  academic_year: number
  semester: string | null
  member_count: number
}

export interface GroupEdge {
  source: string
  target: string
  edge_type: GroupEdgeType
  is_major: boolean
}

export interface InterestExtraOut {
  syllabus_id: string
  why: string
  source: string
}

export interface InterestOut {
  id: string
  label: string
  /** group_id */
  targets: string[]
  extras: InterestExtraOut[]
}

/** D3 GET /api/departments/{dept_id}/graph */
export interface DepartmentGraph {
  department_id: string
  /** 実際に使った線の種類 */
  edge_types: string[]
  groups: GroupNode[]
  edges: GroupEdge[]
  interests: InterestOut[]
  /** 系統図に載る科目 */
  members: CourseSummary[]
}

export type KindCode = 'required' | 'elective_required' | 'elective'

export type ApiTerm = '春' | '秋' | '通年'

/** D4 の一覧の1件（D3 の members も同じ形） */
export interface CourseSummary {
  syllabus_id: string
  course_code: string
  name: string
  subtitle: string | null
  group_id: string | null
  year_min: number | null
  year_max: number | null
  /** NFKC 済みの表記（例 1〜4年次） */
  year_range: string | null
  term: ApiTerm | null
  /** DB の semester のまま */
  term_raw: string | null
  /** 例 ['火2']。読めなければ [] */
  slots: string[]
  /** 読めなかった term_schedule のまま */
  slot_note: string | null
  credits: number | null
  faculties: string[]
  teacher: string | null
  /** description の先頭 120 文字（無ければ ""） */
  lead: string
  kind: KindCode | null
  detail_url: string | null
}

/** D4 GET /api/courses */
export interface CoursePage {
  total: number
  limit: number
  offset: number
  items: CourseSummary[]
  kinds_status: 'available' | 'pending'
}

/** D4 のクエリ（すべて任意） */
export interface CourseQuery {
  dept?: string
  /** 空白区切りの語の AND（5語・100 文字まで） */
  q?: string
  year?: number
  term?: ApiTerm
  slot?: string[]
  group?: string[]
  kind?: KindCode[]
  limit?: number
  offset?: number
}

export interface ScheduleItem {
  number: number | null
  topic: string
}

export interface Instructor {
  name: string
  is_primary: boolean
}

/** 要覧の区分の行（course_requirements） */
export interface BulletinInfo {
  subject_name_bulletin: string
  requirement_type: KindCode
  credits: number
  assigned_year: number | null
  bulletin_code: string | null
  field_category: string | null
}

/** D5 GET /api/courses/{syllabus_id} */
export interface CourseDetail extends CourseSummary {
  academic_year: number
  description: string | null
  objectives: string | null
  schedule: ScheduleItem[]
  work_outside_class: string | null
  grading_policy: string | null
  evaluation_criteria: string | null
  textbooks: string[]
  textbook_notes: string | null
  references: string[]
  notes: string | null
  instructors: Instructor[]
  language: string | null
  teaching_type: string | null
  bulletin: BulletinInfo | null
  source: string
}

export interface CreditBucket {
  key: string
  label: string
  credits: number
}

export interface ThesisRule {
  max_unearned_required_courses: number
  max_unearned_required_credits: number
  min_major_elective_required_credits: number
  mandatory_courses_completed: string[]
  prerequisite_course: string | null
  raw_condition_text: string
}

export interface GraduationRequirements {
  requirement_id: string
  academic_year: number
  total_credits: number
  buckets: CreditBucket[]
  thesis: ThesisRule
  rules_notes: string[]
  /** 学期の履修上限。DB に無いので常に null */
  term_cap: number | null
}

/** D6 GET /api/departments/{dept_id}/requirements */
export interface RequirementsOut {
  department_id: string
  /** 卒業要件の有無。DB に無いときだけ pending */
  status: 'available' | 'pending'
  reason: string | null
  requirements: GraduationRequirements | null
  kinds: DataStatus
  kinds_count: Record<string, number>
  source: string
}

/* ---------- 研究（R1〜R9） ---------- */

export interface BlockPlan {
  /** 0 = 練習、1・2 */
  block: number
  condition_id: string
  task_set_id: string
  task_ids: string[]
}

export interface VariantOut {
  variant_id: string
  condition_id: string | null
  flags: VariantFlags
  flags_version: string
}

export interface SessionOut {
  session_id: string
  pid: string
  study_id: string
  sequence_id: string
  mode: 'onsite' | 'remote'
  department_id: string
  consent_version: string
  consent_recorded: boolean
  blocks: BlockPlan[]
  current_block: number | null
  variant: VariantOut | null
  backend_version: string
  /** 終えたブロック（開き直したときにどこから続けるか。B2 で足した項目） */
  completed_blocks: number[]
  /** サーバーが受け付けた seq の最大（開き直したときに seq を続けるため。まだ無ければ 0。B2 で足した項目） */
  last_seq: number
}

/** R3 POST /api/research/consent の入力 */
export interface ConsentIn {
  consent_version: string
  /** 紙の同意書の通し番号（英数字とハイフン、1〜16 文字。FORM_SERIAL_PATTERN） */
  form_serial: string
  agreed: boolean
}

/** R3 の form_serial の形（backend の ConsentIn と同じ） */
export const FORM_SERIAL_PATTERN = /^[0-9A-Za-z-]{1,16}$/

/** R4 POST /api/research/blocks/{block}/start の応答 */
export interface BlockStartOut {
  plan: BlockPlan
  variant: VariantOut
}

/** クライアントが送るイベントの種類（ab-variants.md 7.2 のクライアント側） */
export const CLIENT_EVENT_TYPES = [
  'session_end',
  'variant_applied',
  'task_start',
  'task_submit',
  'search_query',
  'result_click',
  'recommend_shown',
  'interest_select',
  'group_open',
  'sequence_click',
  'syllabus_open',
  'syllabus_close',
  'original_open',
  'shortlist_add',
  'shortlist_remove',
  'timetable_open',
  'chat_send',
  'ai_full_open',
  'citation_click',
  'questionnaire_submit',
  'page_hidden',
  'page_visible',
  'client_error',
  /* 診断（diagnose=quiz）と、プランの微修正 */
  'diag_start',
  'diag_answer',
  'diag_submit',
  'diag_retake',
  'plan_shown',
  'plan_course_add',
  'plan_course_remove',
  'plan_refine_send',
  /* 履修状況のチェック */
  'checkpoint_add',
  'checkpoint_remove',
  'status_open',
] as const

export type ClientEventType = (typeof CLIENT_EVENT_TYPES)[number]

/** イベントの payload に入れられる値（JSON にそのまま書ける形） */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

export type EventPayload = { [key: string]: JsonValue }

/** R6 の1件 */
export interface ClientEvent {
  event_id: string
  event_type: ClientEventType
  /** セッション内の通し番号（1 から） */
  seq: number
  /** ISO 8601 */
  ts_client: string
  task_id: string | null
  payload: EventPayload
}

export interface EventBatchIn {
  events: ClientEvent[]
}

export interface EventBatchOut {
  accepted: number
  duplicates: number
  last_seq: number
  warnings: string[]
}

/* ---------- AI（A1） ---------- */

export interface AssistOptions {
  route: 'mcp_grounded' | 'static'
  style: 'standard' | 'brief' | 'detailed'
  verify: 'on' | 'off'
  citations: 'cards' | 'text'
}

/** A1 の plan_context の上限（backend の agent/route_options.py の PlanContext。超えると 422） */
export const PLAN_CONTEXT_LIMITS = { summaryChars: 1000, terms: 16, idsPerTerm: 40, yearMax: 8 } as const

/** A1 に添える、いまのプラン（プランの微修正のときだけ。backend は科目名などを DB で引いて相談に付ける） */
export interface PlanContextIn {
  /** 診断の答えの短いまとめ（PLAN_CONTEXT_LIMITS.summaryChars 字まで） */
  answers_summary: string
  /** いまのプランの科目（学期ごと。微修正で足し外しした後） */
  terms: { year: number; term: DiagnoseTerm; syllabus_ids: string[] }[]
}

/** 照合を通った提案1件（title は DB の科目名。外す科目が DB に無いときは null） */
export interface PlanSuggestion {
  syllabus_id: string
  title: string | null
  reason: string
}

/** 照合で外した提案 */
export interface DroppedSuggestion {
  action: 'add' | 'remove'
  syllabus_id: string
  reason: 'not_in_db' | 'already_in_plan' | 'not_in_plan'
}

/** プランの微修正の提案（照合の後）。足す科目は DB にありプランに無いもの、外す科目はプランにあるもの */
export interface PlanSuggestions {
  add: PlanSuggestion[]
  remove: PlanSuggestion[]
  dropped: DroppedSuggestion[]
}

/** A1 POST /api/assist/ask の入力 */
export interface AssistIn {
  /** composeQuestion の後の文 */
  question: string
  /** 利用者が打った文（記録用） */
  raw_input?: string
  /** 対応する chat_send（プランの微修正は plan_refine_send）の event_id */
  client_event_id?: string
  /** 開発のときだけ効く */
  options?: AssistOptions
  /** プランの微修正のときだけ */
  plan_context?: PlanContextIn
}

export interface UnverifiedItem {
  code: string
  reason: 'not_in_db' | 'lookup_failed'
}

/** A1 の応答（既存の McpAgentRunResult の上位互換） */
export interface AssistOut extends McpAgentRunResult {
  request_id: string
  variant_id: string | null
  options_applied: AssistOptions
  options_ignored: boolean
  route_requested: 'mcp_grounded' | 'static'
  unverified_items: UnverifiedItem[]
  /**
   * plan_context を送り、mcp の経路で照合まで通ったときだけ埋まる（ほかは null）。
   * plan_context を知らないサーバー（E1 より前）は項目ごと無い
   */
  plan_suggestions?: PlanSuggestions | null
}

/* ---------- 診断（diagnose=quiz。設定の形は診断のコンペの事前登録 protocol.md） ---------- */

export type DiagnoseQuestionKind = 'single' | 'multi' | 'scale5'

/** 点の付け方の1つ（primitive の名前と引数はエンジンの決まり。画面は中身を使わない） */
export interface DiagnoseEffect {
  primitive: string
  args: Record<string, unknown>
  weight: number
}

export interface DiagnoseOption {
  id: string
  label: string
  effects: DiagnoseEffect[]
}

export interface DiagnoseQuestion {
  id: string
  text: string
  kind: DiagnoseQuestionKind
  /** multi のとき選べる数の上限 */
  max_select?: number
  options: DiagnoseOption[]
}

export type DiagnoseTerm = '春' | '秋'

export interface DiagnoseScopeTerm {
  year: number
  term: DiagnoseTerm
}

/** GET /api/diagnose/config?department_id= */
export interface DiagnoseConfig {
  version: string
  department_id: string
  scope: { terms: DiagnoseScopeTerm[]; credit_cap_per_term: number | null }
  questions: DiagnoseQuestion[]
  base_effects: DiagnoseEffect[]
  tie_break: string
  reason_templates: Record<string, string>
}

/** 答え（multi・single は選んだ選択肢の ID、scale5 は 1〜5） */
export type DiagnoseAnswers = Record<string, string[] | number>

/** POST /api/diagnose/plan の入力 */
export interface DiagnosePlanIn {
  department_id: string
  config_version: string
  answers: DiagnoseAnswers
}

export interface PlanReason {
  primitive: string
  text: string
}

export interface PlanCourse {
  syllabus_id: string
  name: string
  credits: number | null
  slots: string[]
  slot_note: string | null
  score: number
  reasons: PlanReason[]
}

export interface PlanTerm {
  year: number
  term: DiagnoseTerm
  credits_total: number
  courses: PlanCourse[]
}

/** POST /api/diagnose/plan の応答。422 は答えの誤り、409 は設定の版の違い */
export interface DiagnosePlanOut {
  config_version: string
  answers_digest: string
  terms: PlanTerm[]
}
