/**
 * コースナビ（/navi のモック）の型。
 * 学科データの形は UX 仕様（docs/frontend/ux-spec.md）9.2 の D1・D2 を、画面の改訂案 E1（2026-11-04）で
 * 出す項目（曜限・単位・対象・区分・担当・授業でやること・卒業要件）まで広げたもの。
 * 自由記述の API の形は backend/src/agent/runner.py の McpAgentRunResult を写したもの（requirements.md R3-2）。
 */

export type Term = '春' | '秋' | '通年'

/** 区分（シラバスの科目区分。コードの意味が決まるまでは null = 準備中。E1 8章） */
export type Kind = '必修' | '選択' | '他学部'

/** 卒業要件の区分（W4 の「卒業に要る単位」と、推薦の理由に使う） */
export type GradCategory = '必修' | '選択' | '教養'

/** 担当教員。無いときは理由を書き分ける（E1 8章） */
export type TeacherInfo =
  | { status: 'known'; name: string }
  /** 大学のシラバスに書かれていない */
  | { status: 'notInSyllabus' }
  /** 元データにはあるが、こちらにまだ届いていない */
  | { status: 'notDelivered' }

/** 系統図のまとまり（枠）。線はまとまりどうしを結ぶ（UX 仕様 7.6） */
export interface Frame {
  id: string
  year: number
  /** 系統図の表記 */
  name: string
  /** 「なぜ」の文の中で使う短い呼び名（例 2年の「物理化学」につながる） */
  plain: string
  /** 全学共通のまとまりなら true */
  common: boolean
}

/** まとまりどうしの線（前 → 後） */
export interface FrameEdge {
  from: string
  to: string
}

export interface Course {
  code: string
  name: string
  /** 時間割のマスに出す略称（無ければ科目名） */
  short: string | null
  /** 系統図のまとまり。系統図に載っていない科目（他学部など）は null */
  frameId: string | null
  /** 他学部の科目なら学部名 */
  faculty: string | null
  /** 時間割に入れる学年（配当の学年） */
  year: number
  /** 配当年次の表記（例 1〜4年）。無いときは year を使う */
  yearRange: string | null
  term: Term
  /** 曜限（例 ['月2']。2コマの科目は2つ。無いときは空） */
  slots: string[]
  /** 曜限が無い理由（オンデマンド、集中講義、研究室で決める など） */
  slotNote: string | null
  /** 単位。シラバスに書かれていなければ null */
  credits: number | null
  kind: Kind | null
  grad: GradCategory | null
  teacher: TeacherInfo
  /** 授業でやること（一覧の1行）。無ければ空 */
  learn: string
  /** 概要（詳細の本文）。無ければ空 */
  summary: string
  /** 授業計画の各回の題目。無ければ空 */
  plan: string[]
  grading: string | null
  textbook: string | null
  /** シラバス原文の URL。無ければリンクの行を出さない */
  syllabusUrl: string | null
}

/** 興味関心（3年の科目のまとまりを日常の言葉で言い直したもの。UX 仕様 3.8、E1 2章） */
export interface Interest {
  id: string
  label: string
  /** 対応するまとまり。既定（おすすめ）は空 */
  targets: string[]
  /** 系統図に載っていないが一覧に混ぜる科目（他学部など）と、その理由 */
  extras: InterestExtra[]
}

export interface InterestExtra {
  code: string
  why: string
  /** 根拠の種類（灰の文字で添える） */
  source: string
}

export interface GradNeed {
  category: GradCategory
  need: number
}

/** 卒業要件と学期の上限。元データに無いので、無い学科は null（E1 8章） */
export interface Requirements {
  total: number
  termCap: number
  needs: GradNeed[]
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
  interests: Interest[]
  requirements: Requirements | null
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
