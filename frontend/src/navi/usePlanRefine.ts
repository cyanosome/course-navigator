/**
 * プランの微修正（旗 diagnose=quiz かつ assistant=on）。「このプランを〇〇に変えたい」を A1 に送り、回答と提案を持つ。
 * - いまのプランは plan_context（answers_summary と学期ごとの syllabus_id）で送る。サーバーが科目名などを DB で引いて
 *   相談に付け、足す・外すの提案（plan_suggestions、照合の後）を返す。文にはプランを入れない。
 * - plan_context が届かないとき:
 *   - サーバーが plan_context を断った（422）: plan_context を外し、プランと答えの要約を文に入れて聞き直す（text_only）
 *   - サーバーが plan_context を知らない（応答に plan_suggestions の項目が無い。E1 より前）: 回答はそのまま出し、
 *     プランが AI に届いていないと添える（not_supported）。提案が無いので、出典の科目から足し外しする
 *   - つながらない・時間切れ（画面の上限か、サーバーの打ち切りの 504）: 失敗として出し、［もう一度送る］で送り直す
 * - 送るたびに plan_refine_send を記録し、その event_id を A1 の client_event_id に渡す（サーバーの chat_response と結ぶ）。
 * - 待つあいだもほかの画面を使える（状態は NaviRoot にあり、画面を移っても送信は続く）。
 * 質問と回答は sessionStorage（KEYS.refine。タブを閉じると消える）。NaviRoot で1つ作り、PlanRefineContext で配る。
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { ApiError, isPlanSuggestions } from './api'
import type { PlanSuggestions } from './apiTypes'
import type { AskAdapter } from './ask'
import { composeRefineQuestion, planContext, planPayload } from './diagnose'
import type { AnswerSummaryItem, WorkingPlan } from './diagnose'
import type { ResearchLog } from './research'
import { ASK_TIMEOUT_MS } from './state'
import type { AskStatus } from './state'
import { isNumber, isRecord, isString, KEYS, readJson, writeJson } from './storage'
import type { Department, McpAgentRunResult } from './types'

/** with_context: plan_context が届いた、text_only: 断られたので文にプランを入れて聞き直した、not_supported: サーバーが知らない */
export type RefineDelivery = 'with_context' | 'text_only' | 'not_supported'

export interface RefineSession {
  /** 端末の中で付けた番号 */
  localId: string
  /** 利用者が書いた頼み */
  request: string
  status: AskStatus
  startedAt: number
  finishedAt: number | null
  result: McpAgentRunResult | null
  /** 照合の後の足す・外すの提案（サーバーが返さなかったときは null） */
  suggestions: PlanSuggestions | null
  /** 回答が届いたときだけ意味がある */
  delivery: RefineDelivery
}

const DELIVERIES: readonly string[] = ['with_context', 'text_only', 'not_supported']

/** サーバーが時間内に答えを作れず打ち切った（backend の A1 の上限、プロキシの上限） */
const GATEWAY_TIMEOUT = 504

function isRefineSession(v: unknown): v is RefineSession {
  return (
    isRecord(v) &&
    isString(v.localId) &&
    isString(v.request) &&
    (v.status === 'waiting' || v.status === 'done' || v.status === 'error' || v.status === 'timeout' || v.status === 'empty') &&
    isNumber(v.startedAt) &&
    (v.finishedAt === null || isNumber(v.finishedAt)) &&
    (v.result === null || isRecord(v.result)) &&
    (v.suggestions === null || isPlanSuggestions(v.suggestions)) &&
    isString(v.delivery) &&
    DELIVERIES.includes(v.delivery)
  )
}

/** タブを開き直したとき、待ちの途中だった頼みは取り戻せないので失敗として出す */
function restore(): RefineSession | null {
  const saved = readJson('session', KEYS.refine, isRefineSession)
  if (saved === null || saved.status !== 'waiting') return saved
  return { ...saved, status: 'error', finishedAt: saved.startedAt }
}

/** 応答から提案を取り出す。plan_suggestions の項目ごと無ければ、サーバーが plan_context を知らない */
function suggestionsOf(result: McpAgentRunResult): { known: boolean; suggestions: PlanSuggestions | null } {
  if (!('plan_suggestions' in result)) return { known: false, suggestions: null }
  const value: unknown = result.plan_suggestions
  return { known: true, suggestions: isPlanSuggestions(value) ? value : null }
}

export interface RefineTarget {
  configVersion: string
  answersDigest: string
  plan: WorkingPlan
  summary: AnswerSummaryItem[]
}

export interface PlanRefineState {
  session: RefineSession | null
  /** 送れたら端末内の番号、前の頼みを待っているとき・プランが無いときは null */
  send: (request: string, opts?: { retry?: boolean }) => string | null
  cancel: () => void
}

interface RefineDeps {
  adapter: AskAdapter
  dept: Department
  log: ResearchLog['log']
  /** いまのプラン（無ければ送れない） */
  target: RefineTarget | null
}

export function usePlanRefineState({ adapter, dept, log, target }: RefineDeps): PlanRefineState {
  const [session, setSession] = useState<RefineSession | null>(restore)
  useEffect(() => writeJson('session', KEYS.refine, session), [session])
  const control = useRef<AbortController | null>(null)

  const send = useCallback(
    (request: string, opts?: { retry?: boolean }): string | null => {
      if (target === null || (session !== null && session.status === 'waiting')) return null
      const seq = (readJson('session', KEYS.refineSeq, isNumber) ?? 0) + 1
      writeJson('session', KEYS.refineSeq, seq)
      const localId = String(seq)
      const { context, clamped } = planContext(target.plan, target.summary)
      setSession({
        localId,
        request,
        status: 'waiting',
        startedAt: Date.now(),
        finishedAt: null,
        result: null,
        suggestions: null,
        delivery: 'with_context',
      })

      const c = new AbortController()
      control.current = c
      let timedOut = false
      const timer = setTimeout(() => {
        timedOut = true
        c.abort()
      }, ASK_TIMEOUT_MS)
      const finish = (patch: Partial<RefineSession>) =>
        setSession((s) => (s !== null && s.localId === localId ? { ...s, ...patch, finishedAt: Date.now() } : s))

      const attempt = (withContext: boolean): Promise<void> => {
        const question = composeRefineQuestion(dept, request, withContext ? null : { plan: target.plan, summary: target.summary })
        const clientEventId = log('plan_refine_send', {
          input: request,
          question,
          refine_local_id: localId,
          config_version: target.configVersion,
          answers_digest: target.answersDigest,
          plan: planPayload(target.plan),
          plan_context: withContext,
          ...(withContext && clamped ? { plan_context_clamped: true } : {}),
          ...(opts?.retry === true ? { retry: true } : {}),
          ...(withContext ? {} : { fallback: 'plan_context_rejected' }),
        })
        return adapter
          .ask({ question, rawInput: request, clientEventId, ...(withContext ? { planContext: context } : {}) }, c.signal)
          .then((result) => {
            const { known, suggestions } = suggestionsOf(result)
            const delivery: RefineDelivery = !withContext ? 'text_only' : known ? 'with_context' : 'not_supported'
            if (delivery === 'not_supported') console.warn('サーバーが plan_context を知らないため、プランが AI に届いていません（E1 の口が要ります）')
            const hasAny = result.sources.length > 0 || (suggestions !== null && suggestions.add.length + suggestions.remove.length > 0)
            finish({ status: hasAny ? 'done' : 'empty', result, suggestions, delivery })
          })
          .catch((err: unknown) => {
            if (timedOut) {
              finish({ status: 'timeout' })
              return
            }
            if (c.signal.aborted) return // ［やめる］で止めた
            if (err instanceof ApiError && err.status === GATEWAY_TIMEOUT) {
              console.warn('プランの微修正がサーバーで時間切れになりました', err)
              finish({ status: 'timeout' })
              return
            }
            if (withContext && err instanceof ApiError && err.status === 422) {
              console.warn('サーバーが plan_context を受け付けないので、プランを文に入れて聞き直します', err)
              return attempt(false)
            }
            console.error('プランの微修正の回答を受け取れませんでした', err)
            finish({ status: 'error' })
          })
      }
      void attempt(true).finally(() => {
        clearTimeout(timer)
        if (control.current === c) control.current = null
      })
      return localId
    },
    [adapter, dept, log, session, target],
  )

  const cancel = useCallback(() => {
    control.current?.abort()
    control.current = null
    setSession(null)
  }, [])

  return { session, send, cancel }
}

export const PlanRefineContext = createContext<PlanRefineState | null>(null)

export function usePlanRefine(): PlanRefineState {
  const value = useContext(PlanRefineContext)
  if (value === null) throw new Error('usePlanRefine は NaviApp の中で使ってください')
  return value
}
