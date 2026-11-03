/**
 * コースナビ（/navi のモック）の型。
 * 学科データの形は UX 仕様（docs/frontend/ux-spec.md）9.2 の D1・D2 を、画面に要る項目だけに絞ったもの。
 * 自由記述の API の形は backend/src/agent/runner.py の McpAgentRunResult を写したもの（requirements.md R3-2）。
 */

export type Term = '春' | '秋' | '通年'

/** 根拠の種類（UX 仕様 7.2）。色・形・文字の3つで見分ける（DESIGN.md 3.2） */
export type EvidenceKind = 'route' | 'syllabus' | 'ai'

/** 系統図の枠（科目のまとまり）。線は枠どうしを結ぶ（UX 仕様 7.6）。 */
export interface Frame {
  id: string
  year: number
  name: string
  /** 全学共通の枠なら true（既定の提案の並びで学科の枠を先にする。UX 仕様 3.7） */
  common: boolean
}

/** 枠どうしの線（前提 → 先）。 */
export interface FrameEdge {
  from: string
  to: string
}

export interface PlanItem {
  no: number
  title: string
}

export interface Course {
  code: string
  name: string
  frameId: string
  year: number
  term: Term
  /** 曜日・時限（例 月2） */
  slot: string
  credits: number
  /** シラバスの授業計画の抜粋（無ければ空） */
  plan: PlanItem[]
  /** 授業計画の全回数 */
  planTotal: number
  /** 概要の抜粋（無ければ空） */
  summary: string
}

/** 方向（3年の科目のまとまりを日常の言葉で言い直したもの。UX 仕様 3.8） */
export interface Direction {
  id: string
  label: string
  description: string
  /** 対応する枠。既定（まず見ておきたい）は空 */
  targets: string[]
}

export interface Department {
  id: string
  university: string
  faculty: string
  name: string
  /** 学科データの版（W10 の記録に出す。UX 仕様 8.3） */
  dataVersion: string
  syllabusYear: number
  frames: Frame[]
  edges: FrameEdge[]
  courses: Course[]
  directions: Direction[]
}

/* ---------- 自由記述の API（POST /api/test/agent/mcp）の形 ---------- */

/** DB（PostgreSQL）の行から組み立てた出典。LLM の生成テキストではない。 */
export interface AgentSource {
  code: string
  title: string
  instructor: string | null
  schedule: string | null
  credits: number | null
  excerpt: string
  origin: string
  url: string | null
}

export interface AgentToolCall {
  name: string
  /** ツール引数は任意の JSON なので境界の型として unknown で受ける */
  args: Record<string, unknown>
  result_summary: string | null
}

export interface McpAgentRunResult {
  route: 'mcp' | 'static'
  answer: string
  cited_codes: string[]
  sources: AgentSource[]
  unverified_codes: string[]
  notes: string[]
  tool_calls: AgentToolCall[]
  node_sequence: string[]
  model: string | null
  latency_ms: number
}

/** POST /api/test/agent/mcp の入力 */
export interface AgentQueryInput {
  question: string
}
