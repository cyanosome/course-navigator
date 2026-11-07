/**
 * 変種の旗（ab-variants.md 2 章の 19 個と、11/7 に足した diagnose）と、旗の文脈（React context）。
 * 旗の正本は backend の変種の表（course_core/research/variants.py）で、画面はサーバーから受け取った旗だけで出し分ける。
 * 受け取る前と、調査でないときの既定は V00 相当（何も隠さない）。
 */
import { createContext, useContext } from 'react'
import type { GroupEdgeType, VariantOut } from './apiTypes'
import { isRecord, isString } from './storage'

export interface VariantFlags {
  search: 'kw' | 'kw_filter' | 'off'
  graph: 'on' | 'off'
  recommend: 'reach' | 'reach_seeded' | 'catalog' | 'off'
  assistant: 'on' | 'off'
  /* ここから AI の旗。assistant=off のときはすべて null（制約 C3） */
  ai_route: 'mcp_grounded' | 'mcp_free' | 'static' | 'static_llm' | null
  verify: 'on' | 'off' | null
  citations: 'cards' | 'text' | null
  first_suggestion: 'rule' | 'llm' | 'none'
  style: 'standard' | 'brief' | 'detailed' | null
  timetable: 'on' | 'off'
  detail: 'full' | 'core'
  question_frame: 'composed' | 'raw' | 'composed_guardrail' | null
  toolset: 'reused' | 'per_request' | null
  rule_edges: 'official_all' | 'official_prereq' | 'with_inferred'
  ai_edges: 'official' | 'with_similar' | 'with_inferred' | null
  model: 'default' | 'alt' | null
  retrieval: 'agent_tools' | 'vector_seed' | null
  similar_panel: 'off' | 'on'
  requirements: 'shown' | 'hidden'
  /**
   * 診断（F20、11/7 に足した）。quiz: 質問に答えるとプランを出す画面を足す。
   * 表の版 1 のサーバーは送ってこないので省けるようにし、省いたときは off と同じに扱う（指紋も省いたまま計算する）
   */
  diagnose?: 'off' | 'quiz'
}

type FlagKey = keyof VariantFlags

/** 各旗の取りうる値（null を除く）。受け取った旗の検査に使う */
const FLAG_VALUES: { [K in FlagKey]: readonly NonNullable<VariantFlags[K]>[] } = {
  search: ['kw', 'kw_filter', 'off'],
  graph: ['on', 'off'],
  recommend: ['reach', 'reach_seeded', 'catalog', 'off'],
  assistant: ['on', 'off'],
  ai_route: ['mcp_grounded', 'mcp_free', 'static', 'static_llm'],
  verify: ['on', 'off'],
  citations: ['cards', 'text'],
  first_suggestion: ['rule', 'llm', 'none'],
  style: ['standard', 'brief', 'detailed'],
  timetable: ['on', 'off'],
  detail: ['full', 'core'],
  question_frame: ['composed', 'raw', 'composed_guardrail'],
  toolset: ['reused', 'per_request'],
  rule_edges: ['official_all', 'official_prereq', 'with_inferred'],
  ai_edges: ['official', 'with_similar', 'with_inferred'],
  model: ['default', 'alt'],
  retrieval: ['agent_tools', 'vector_seed'],
  similar_panel: ['off', 'on'],
  requirements: ['shown', 'hidden'],
  diagnose: ['off', 'quiz'],
}

/** null を取りうる旗（AI の旗） */
const NULLABLE_FLAGS: readonly FlagKey[] = [
  'ai_route',
  'verify',
  'citations',
  'style',
  'question_frame',
  'toolset',
  'model',
  'ai_edges',
  'retrieval',
]

/** 省いてよい旗（表の版 1 に無かった因子）。省けば off と同じ */
const OPTIONAL_FLAGS: readonly FlagKey[] = ['diagnose']

/** 変種の表の版（付録 A の flags_version。diagnose を足して 2） */
export const FLAGS_VERSION = '2'

/** 基準 V00（付録 A の base） */
export const V00_FLAGS: VariantFlags = {
  search: 'kw',
  graph: 'on',
  recommend: 'reach',
  assistant: 'on',
  ai_route: 'mcp_grounded',
  verify: 'on',
  citations: 'cards',
  first_suggestion: 'rule',
  style: 'standard',
  timetable: 'on',
  detail: 'full',
  question_frame: 'composed',
  toolset: 'reused',
  rule_edges: 'official_all',
  ai_edges: 'official',
  model: 'default',
  retrieval: 'agent_tools',
  similar_panel: 'off',
  requirements: 'shown',
  diagnose: 'off',
}

export interface VariantState {
  /** V00〜V29。サーバーから受け取る前は null */
  variantId: string | null
  /** 調査の伏せた記号（K/M/J/L）。調査でなければ null */
  conditionId: string | null
  flags: VariantFlags
  flagsVersion: string
}

/** サーバーから旗を受け取る前の既定。V00 相当で、今の画面から何も隠さない */
export const DEFAULT_VARIANT: VariantState = {
  variantId: null,
  conditionId: null,
  flags: V00_FLAGS,
  flagsVersion: FLAGS_VERSION,
}

export const VariantContext = createContext<VariantState>(DEFAULT_VARIANT)

export function useVariant(): VariantState {
  return useContext(VariantContext)
}

export function useFlags(): VariantFlags {
  return useContext(VariantContext).flags
}

/** 受け取った旗の形の検査（旗がすべてあり、値が一覧にあるか。AI の旗だけ null を、diagnose だけ省くのを許す） */
export function isVariantFlags(v: unknown): v is VariantFlags {
  if (!isRecord(v)) return false
  return (Object.keys(FLAG_VALUES) as FlagKey[]).every((key) => {
    const value = v[key]
    if (value === undefined) return OPTIONAL_FLAGS.includes(key)
    if (value === null) return NULLABLE_FLAGS.includes(key)
    return isString(value) && (FLAG_VALUES[key] as readonly string[]).includes(value)
  })
}

/** R4・R8・R9 の応答から画面の旗の状態へ */
export function toVariantState(out: VariantOut): VariantState {
  return { variantId: out.variant_id, conditionId: out.condition_id, flags: out.flags, flagsVersion: out.flags_version }
}

/** rule_edges（F14）ごとに、系統図の API（D3）へ渡す線の種類。null はまだ使えない水準（制約 C7） */
const RULE_EDGE_TYPES: { [K in VariantFlags['rule_edges']]: readonly GroupEdgeType[] | null } = {
  official_all: ['prerequisite', 'capstone', 'english_track'],
  official_prereq: ['prerequisite'],
  with_inferred: null,
}

export function ruleEdgeTypes(flags: VariantFlags): readonly GroupEdgeType[] | null {
  return RULE_EDGE_TYPES[flags.rule_edges]
}

const FNV_OFFSET = 0x811c9dc5
const FNV_PRIME = 0x01000193

/**
 * variant_applied に載せる旗の指紋（"fnv1a32:" と 16 進 8 桁）。キーを辞書順に並べた空白なしの JSON の UTF-8 に
 * FNV-1a（32 ビット）をかける。値はすべて ASCII なので、Python の
 * json.dumps(flags, sort_keys=True, separators=(',', ':')) の UTF-8 に同じ計算をすれば一致する。
 * 安全のためのハッシュではなく、画面とサーバーの旗が同じかを確かめるためのもの。
 */
export function flagsDigest(flags: VariantFlags): string {
  const sorted = Object.fromEntries(Object.entries(flags).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
  let hash = FNV_OFFSET
  for (const byte of new TextEncoder().encode(JSON.stringify(sorted))) {
    hash ^= byte
    hash = Math.imul(hash, FNV_PRIME) >>> 0
  }
  return `fnv1a32:${hash.toString(16).padStart(8, '0')}`
}
