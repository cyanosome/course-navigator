/**
 * 診断の状態（設定の読み込み・答え・送信・プラン・微修正での足し外し）と、その研究のログ。
 * 画面の部品はこのフックの値と関数だけを使う（見た目を差し替えても状態と記録は変わらない）。
 * NaviRoot で1つ作り（useDiagnoseState）、DiagnoseContext で配る（useDiagnose）。
 * 答えとプランは学科ごとに端末に保存する（KEYS.diagnose。調査の開始時・ブロックの開始時に消える）。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, apiErrorMessage, isAbortError, isDiagnosePlanOut } from './api'
import type { DiagnoseAnswers, DiagnoseConfig, DiagnosePlanOut, DiagnoseQuestion, EventPayload, PlanHistoryIn } from './apiTypes'
import type { CourseMapping } from './mapping'
import {
  addCourseToPlan,
  answersPayload,
  answersSummary,
  coursePlace,
  findPlanCourse,
  firstUnanswered,
  inPlan,
  isDiagnoseAnswers,
  isWorkingPlan,
  keepPastTerms,
  liftPlace,
  moveCourseInPlan,
  pickOption,
  planCodes,
  planPayload,
  pruneAnswers,
  removeCourseFromPlan,
  setScale,
  toWorkingPlan,
} from './diagnose'
import type { AnswerSummaryItem, DiagnoseSource, PlanPlace, WorkingPlan } from './diagnose'
import type { ResearchLog } from './research'
import { isNumber, isRecord, isString, KEYS, readJson, writeJson } from './storage'
import type { Loadable } from './useLoadable'
import { useLoadable } from './useLoadable'

/** fresh: まだ始めていない、answering: 答えている、plan: プランを出している（送っているあいだは submitting） */
export type DiagnosePhase = 'fresh' | 'answering' | 'plan'

export type DiagnoseNoticeKind = 'version_changed' | 'invalid_answers' | 'failed'

export interface DiagnoseNotice {
  kind: DiagnoseNoticeKind
  message: string
}

/** プランへ足した結果（unmapped は学年か学期が読めない科目） */
export type PlanAddResult = 'added' | 'already' | 'unmapped' | 'failed'

/**
 * プランの足し外しがどこからか（研究のログの from。事前登録 study1 の 6.2 の4種）。manual: プランの行や詳細から、
 * search: さがすの一覧から、check_fix: チェックの直し方（別のクラスへ移す）から、refine: 微修正の AI の案から
 */
export type PlanEditFrom = 'manual' | 'search' | 'check_fix' | 'refine'

interface Stored {
  deptId: string
  phase: DiagnosePhase
  /** 診断の画面を一度出したか（出すまでは、さがすを開くと診断へ送る） */
  shown: boolean
  /** 答えた設定の版 */
  configVersion: string | null
  answers: DiagnoseAnswers
  /** いま出している質問の番号 */
  index: number
  /** サーバーが返したプラン（答えとプランを再現するため、そのまま持つ） */
  plan: DiagnosePlanOut | null
  /** プランを作った答え（答え直しをやめたら、これに戻す） */
  planAnswers: DiagnoseAnswers | null
  /** 微修正で足し外しした後のプラン */
  working: WorkingPlan | null
}

function isStored(v: unknown): v is Stored {
  return (
    isRecord(v) &&
    isString(v.deptId) &&
    (v.phase === 'fresh' || v.phase === 'answering' || v.phase === 'plan') &&
    typeof v.shown === 'boolean' &&
    (v.configVersion === null || isString(v.configVersion)) &&
    isDiagnoseAnswers(v.answers) &&
    isNumber(v.index) &&
    (v.plan === null || isDiagnosePlanOut(v.plan)) &&
    (v.planAnswers === null || isDiagnoseAnswers(v.planAnswers)) &&
    (v.working === null || isWorkingPlan(v.working))
  )
}

function freshState(deptId: string): Stored {
  return { deptId, phase: 'fresh', shown: false, configVersion: null, answers: {}, index: 0, plan: null, planAnswers: null, working: null }
}

const MESSAGE_MAX_CHARS = 200

/** backend が履修の状況の誤りで返す 422 の detail の頭（course_core の routers/diagnose.py） */
const HISTORY_ERROR_PREFIX = '履修の状況'

export interface DiagnoseState {
  /** 診断の設定（旗が diagnose=quiz でなければ null） */
  config: Loadable<DiagnoseConfig> | null
  reloadConfig: () => void
  phase: DiagnosePhase
  submitting: boolean
  shown: boolean
  /** 今の設定で読める答え（設定が変わったら、読めない答えは落とす） */
  answers: DiagnoseAnswers
  /** いま出している質問の番号（設定の質問の数の中に収める） */
  index: number
  plan: DiagnosePlanOut | null
  /** プランを作った答え（プランが無ければ null。答え直しの途中でも変わらない） */
  planAnswers: DiagnoseAnswers | null
  working: WorkingPlan | null
  /** 答えの要約（設定が読めるまでは空） */
  summary: AnswerSummaryItem[]
  notice: DiagnoseNotice | null
  /** 診断の画面を出した（さがすから送らなくなる） */
  markShown: () => void
  /** ［はじめる］。diag_start を記録する */
  start: () => void
  pick: (q: DiagnoseQuestion, optionId: string) => void
  scale: (q: DiagnoseQuestion, value: number) => void
  goTo: (index: number) => void
  /** 答えを送ってプランを受け取る（diag_submit・plan_shown） */
  submit: () => void
  /** ［答え直す］。前の答えを残して最初の質問へ（diag_retake） */
  retake: () => void
  /** 答え直しをやめてプランへ戻る（答えはプランを作った答えに戻す） */
  backToPlan: () => void
  /**
   * 科目をプランに足す（plan_course_add。detail は記録に足す項目）。入れる学年と学期は at、無ければ科目の詳細を読んで決める。
   * from が refine なら AI の案、それ以外は利用者が自分で足した科目として持つ
   */
  addToPlan: (code: string, from: PlanEditFrom, detail?: EventPayload, at?: PlanPlace) => Promise<PlanAddResult>
  /** プランから外す（plan_course_remove） */
  removeFromPlan: (code: string, from: PlanEditFrom, detail?: EventPayload) => void
  /** プランの科目を別の学期へ移す（学期の切り替わりで、春の通年の科目を秋の登録済みにするとき。調査のモードでは使わない） */
  moveInPlan: (code: string, to: PlanPlace) => void
}

interface DiagnoseDeps {
  deptId: string
  enabled: boolean
  source: DiagnoseSource
  log: ResearchLog['log']
  loadCourse: (syllabusId: string, signal: AbortSignal) => Promise<CourseMapping>
  /**
   * 履修の状況（今の学期・履修済み・登録済み）。あれば答えといっしょに送り、返ったプラン（start から先だけ）に
   * 前のプランの start より前の学期を残す。調査のモードでは null（今までどおり送らない）
   */
  history?: PlanHistoryIn | null
  /** プランに自分で足す科目を入れる最初の学期（今の学期。これより前の学期には入れない）。無ければ null */
  minPlace?: PlanPlace | null
}

function truncate(text: string): string {
  return text.length > MESSAGE_MAX_CHARS ? `${text.slice(0, MESSAGE_MAX_CHARS)}…` : text
}

export function useDiagnoseState({
  deptId,
  enabled,
  source,
  log,
  loadCourse,
  history = null,
  minPlace = null,
}: DiagnoseDeps): DiagnoseState {
  const [reload, setReload] = useState(0)
  const reloadConfig = useCallback(() => setReload((n) => n + 1), [])
  const loadConfig = useCallback((signal: AbortSignal) => source.getConfig(deptId, signal), [source, deptId])
  const config = useLoadable(enabled ? `${deptId}#${reload}` : null, loadConfig, '診断の設定')
  const ready = config?.status === 'ready' ? config.value : null

  const [stored, setStored] = useState<Stored>(() => {
    const saved = readJson('local', KEYS.diagnose, isStored)
    return saved !== null && saved.deptId === deptId ? saved : freshState(deptId)
  })
  // 学科が変わったら、前の学科の答えとプランは使わない
  const fresh = useMemo(() => freshState(deptId), [deptId])
  const cur = stored.deptId === deptId ? stored : fresh
  useEffect(() => writeJson('local', KEYS.diagnose, cur), [cur])

  const [submitting, setSubmitting] = useState(false)
  const [notice, setNotice] = useState<DiagnoseNotice | null>(null)
  const control = useRef<AbortController | null>(null)
  useEffect(() => () => control.current?.abort(), [])

  const answers = useMemo(
    () => (ready === null || cur.configVersion === ready.version ? cur.answers : pruneAnswers(ready, cur.answers)),
    [ready, cur.configVersion, cur.answers],
  )
  const questionCount = ready?.questions.length ?? 0
  const index = Math.max(0, Math.min(cur.index, questionCount - 1))
  const summary = useMemo(() => (ready === null ? [] : answersSummary(ready, answers)), [ready, answers])

  const update = useCallback(
    (patch: Partial<Stored>) => setStored((s) => ({ ...(s.deptId === deptId ? s : freshState(deptId)), ...patch })),
    [deptId],
  )

  const markShown = useCallback(() => {
    if (!cur.shown) update({ shown: true })
  }, [cur.shown, update])

  const start = useCallback(() => {
    if (ready === null) return
    update({ phase: 'answering', shown: true, index: 0, configVersion: ready.version, answers })
    log('diag_start', { config_version: ready.version, question_count: ready.questions.length })
  }, [answers, log, ready, update])

  const record = useCallback(
    (q: DiagnoseQuestion, next: DiagnoseAnswers) => {
      if (ready === null || next === answers) return
      update({ answers: next, configVersion: ready.version })
      const value = next[q.id]
      log('diag_answer', {
        config_version: ready.version,
        question_id: q.id,
        value: value === undefined ? null : Array.isArray(value) ? [...value] : value,
        index: ready.questions.findIndex((x) => x.id === q.id),
      })
    },
    [answers, log, ready, update],
  )
  const pick = useCallback((q: DiagnoseQuestion, optionId: string) => record(q, pickOption(q, answers, optionId)), [answers, record])
  const scale = useCallback((q: DiagnoseQuestion, value: number) => record(q, setScale(q, answers, value)), [answers, record])
  const goTo = useCallback((i: number) => update({ index: i }), [update])

  const submit = useCallback(() => {
    if (ready === null || submitting || firstUnanswered(ready, answers) >= 0) return
    log('diag_submit', { config_version: ready.version, answers: answersPayload(answers) })
    setSubmitting(true)
    setNotice(null)
    const c = new AbortController()
    control.current = c
    const start = history?.start === undefined ? null : { year: history.start.year, term: history.start.term }
    source
      .makePlan({ department_id: deptId, config_version: ready.version, answers, ...(history ?? {}) }, c.signal)
      .then((plan) => {
        const working = keepPastTerms(cur.working, toWorkingPlan(plan), start)
        update({ phase: 'plan', configVersion: ready.version, answers, plan, planAnswers: answers, working })
        log('plan_shown', {
          config_version: plan.config_version,
          answers_digest: plan.answers_digest,
          plan: planPayload(working),
          course_count: planCodes(working).length,
        })
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return
        const status = err instanceof ApiError ? err.status : null
        console.error('プランを受け取れませんでした', err)
        log('client_error', { kind: 'api', step: 'diagnose_plan', status, message: truncate(String(err)) })
        if (status === 409) {
          setNotice({ kind: 'version_changed', message: '質問が新しくなりました。答えを確かめて、もう一度送ってください。' })
          reloadConfig()
        } else if (status === 422 && history !== null && err instanceof ApiError && err.detail?.startsWith(HISTORY_ERROR_PREFIX) === true) {
          setNotice({ kind: 'invalid_answers', message: '取った科目か今の学期を読み取れませんでした。取った科目を確かめてください。' })
        } else if (status === 422) {
          setNotice({ kind: 'invalid_answers', message: '答えを読み取れませんでした。答え直してください。' })
        } else {
          setNotice({ kind: 'failed', message: `プランを作れませんでした。${apiErrorMessage(err)}` })
        }
      })
      .finally(() => {
        if (control.current === c) control.current = null
        setSubmitting(false)
      })
  }, [answers, cur.working, deptId, history, log, ready, reloadConfig, source, submitting, update])

  const retake = useCallback(() => {
    update({ phase: 'answering', index: 0 })
    setNotice(null)
    const payload: EventPayload = { config_version: ready?.version ?? cur.configVersion, answers_digest: cur.plan?.answers_digest ?? null }
    log('diag_retake', payload)
  }, [cur.configVersion, cur.plan, log, ready, update])

  const backToPlan = useCallback(() => {
    if (cur.plan === null) return
    setNotice(null)
    update({ phase: 'plan', answers: cur.planAnswers ?? cur.answers, configVersion: cur.plan.config_version })
  }, [cur.answers, cur.plan, cur.planAnswers, update])

  const working = cur.working
  const addToPlan = useCallback(
    async (code: string, from: PlanEditFrom, detail: EventPayload = {}, at?: PlanPlace): Promise<PlanAddResult> => {
      if (working === null) return 'failed'
      if (inPlan(working, code)) return 'already'
      let mapping: CourseMapping
      try {
        mapping = await loadCourse(code, new AbortController().signal)
      } catch (err) {
        console.error('プランに足す科目の詳細を読めませんでした', err)
        return 'failed'
      }
      if (!mapping.ok) return 'unmapped'
      const course = mapping.course
      const place = at ?? liftPlace(coursePlace(course), minPlace)
      setStored((s) => {
        const base = s.deptId === deptId ? s : freshState(deptId)
        return base.working === null
          ? base
          : { ...base, working: addCourseToPlan(base.working, course, from === 'refine' ? 'refine' : 'user', place) }
      })
      log('plan_course_add', { ...detail, syllabus_id: code, year: place.year, term: place.term, from })
      return 'added'
    },
    [deptId, loadCourse, log, minPlace, working],
  )

  const removeFromPlan = useCallback(
    (code: string, from: PlanEditFrom, detail: EventPayload = {}) => {
      const hit = working === null ? undefined : findPlanCourse(working, code)
      if (hit === undefined) return
      // 続けて何科目か外す（微修正の案をまとめて入れる）ときに前の外しを消さないよう、いまの状態から外す
      setStored((s) => {
        const base = s.deptId === deptId ? s : freshState(deptId)
        return base.working === null ? base : { ...base, working: removeCourseFromPlan(base.working, code) }
      })
      log('plan_course_remove', { ...detail, syllabus_id: code, year: hit.term.year, term: hit.term.term, from })
    },
    [deptId, log, working],
  )

  const moveInPlan = useCallback(
    (code: string, to: PlanPlace) =>
      setStored((s) => {
        const base = s.deptId === deptId ? s : freshState(deptId)
        return base.working === null ? base : { ...base, working: moveCourseInPlan(base.working, code, to) }
      }),
    [deptId],
  )

  return {
    config,
    reloadConfig,
    phase: cur.phase,
    submitting,
    shown: cur.shown,
    answers,
    index,
    plan: cur.plan,
    planAnswers: cur.plan === null ? null : (cur.planAnswers ?? cur.answers),
    working,
    summary,
    notice,
    markShown,
    start,
    pick,
    scale,
    goTo,
    submit,
    retake,
    backToPlan,
    addToPlan,
    removeFromPlan,
    moveInPlan,
  }
}

export const DiagnoseContext = createContext<DiagnoseState | null>(null)

export function useDiagnose(): DiagnoseState {
  const value = useContext(DiagnoseContext)
  if (value === null) throw new Error('useDiagnose は NaviApp の中で使ってください')
  return value
}
