/**
 * コースナビ（/navi の下）の画面。UX 仕様（docs/frontend/ux-spec.md）の流れに、画面の改訂案 E1（2026-11-04）の
 * 見た目と時間割を組む体験を合わせた。データは要るときに backend の API へ問い合わせる（src/navi/dataSource.ts）。
 * 架空の見本（src/navi/fixture*.ts）は開発ビルドだけのデータ源。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useMatch } from 'react-router-dom'
import '../../navi/fonts.css'
import '../../navi/navi.css'
import { apiErrorMessage } from '../../navi/api'
import type { DepartmentSummary } from '../../navi/apiTypes'
import type { AskAdapter } from '../../navi/ask'
import { composeQuestion, createFakeAskAdapter, isFakeWaitMode } from '../../navi/ask'
import type { FakeWaitMode } from '../../navi/ask'
import { createHttpAskAdapter } from '../../navi/askAdapter'
import { createCourseStore, createNaviDataSource, NaviDataContext } from '../../navi/dataSource'
import type { NaviData, NaviDataSource } from '../../navi/dataSource'
import { createDiagnoseSource } from '../../navi/diagnose'
import type { DiagnoseSource } from '../../navi/diagnose'
import { findCourse } from '../../navi/graph'
import { PC_QUERY, REDUCED_MOTION_QUERY, useMediaQuery } from '../../navi/hooks'
import {
  isTaskRunning,
  NOOP_RESEARCH_LOG,
  RESEARCH_LOG,
  ResearchLogContext,
  useFallbackVariant,
  useResearchLog,
  useStudy,
} from '../../navi/research'
import type { ShortlistFrom } from '../../navi/research'
import { ASK_TIMEOUT_MS, DIAGNOSE_HREF, isAskSession, isStudyRecord, NaviContext } from '../../navi/state'
import type { AskSession, NaviContextValue, StudyEvent, StudyRecord, ToastState } from '../../navi/state'
import { isNumber, isString, isStringArray, KEYS, readJson, writeJson } from '../../navi/storage'
import type { TermKey } from '../../navi/timetable'
import type { Department } from '../../navi/types'
import { DiagnoseContext, useDiagnoseState } from '../../navi/useDiagnose'
import type { DiagnoseState } from '../../navi/useDiagnose'
import { useLoadable } from '../../navi/useLoadable'
import { PlanRefineContext, usePlanRefineState } from '../../navi/usePlanRefine'
import type { PlanRefineState, RefineTarget } from '../../navi/usePlanRefine'
import { CheckpointsContext, useCheckpointsState } from '../../navi/useStatus'
import type { CheckpointsState } from '../../navi/useStatus'
import { DEFAULT_VARIANT, ruleEdgeTypes, toVariantState, useFlags, VariantContext } from '../../navi/variant'
import { addedNotice } from '../../navi/views'
import AboutScreen from './AboutScreen'
import CourseScreen from './CourseScreen'
import DepartmentScreen from './DepartmentScreen'
import DiagnoseScreen from './DiagnoseScreen'
import GroupScreen from './GroupScreen'
import NaviLayout from './NaviLayout'
import NaviShell from './NaviShell'
import PageFrame from './PageFrame'
import SearchScreen from './SearchScreen'
import StudyEndScreen from './StudyEndScreen'
import StudyGate from './StudyGate'
import StudyStartScreen from './StudyStartScreen'
import TimetableScreen from './TimetableScreen'

const SESSION_ID_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
const SESSION_ID_LENGTH = 6
const MAX_ASSUMED_YEAR = 4

interface InitialParams {
  /** リンクの ?d=（学科の一覧を読んでから照らす） */
  linkDeptId: string | null
  /** 端末に覚えた学科 */
  storedDeptId: string | null
  assumedYear: number
  /** 偽のアダプタの待ち方。開発ビルドで ?wait= を付けたときだけ。null なら本物の API に聞く */
  wait: FakeWaitMode | null
  studySurveyId: string | null
}

/** 開発ビルドで ?wait= を付けたときだけ偽のアダプタを使う（本番のビルドは常に null） */
function readFakeWait(params: URLSearchParams): FakeWaitMode | null {
  if (!import.meta.env.DEV) return null
  const wait = params.get('wait')
  if (isFakeWaitMode(wait)) writeJson('session', KEYS.wait, wait)
  const stored = readJson('session', KEYS.wait, isString)
  return isFakeWaitMode(stored) ? stored : null
}

/** リンクの指定（?d= 学科、?t= 想定の学年、?wait= 偽の待ち方、?mode=study&s= 調査）を読み、端末に覚える */
function readInitialParams(search: string): InitialParams {
  const params = new URLSearchParams(search)
  const t = Number(params.get('t'))
  if (Number.isInteger(t) && t >= 1 && t <= MAX_ASSUMED_YEAR) writeJson('session', KEYS.assumedYear, t)
  const s = params.get('s')
  return {
    linkDeptId: params.get('d'),
    storedDeptId: readJson('local', KEYS.dept, isString),
    assumedYear: readJson('session', KEYS.assumedYear, isNumber) ?? 1,
    wait: readFakeWait(params),
    studySurveyId: params.get('mode') === 'study' && s !== null && s !== '' ? s : null,
  }
}

/** 開く学科（リンクの ?d= が先、次に端末に覚えた学科）。どちらも一覧に無ければ null（学科えらび） */
function pickDepartment(list: DepartmentSummary[], initial: InitialParams): string | null {
  const ids = new Set(list.map((d) => d.id))
  if (initial.linkDeptId !== null && ids.has(initial.linkDeptId)) return initial.linkDeptId
  if (initial.storedDeptId !== null && ids.has(initial.storedDeptId)) return initial.storedDeptId
  return null
}

/** タブを開き直したとき、待ちの途中だった質問は取り戻せない（requirements.md R1-4 は後の段階）ので失敗として出す */
function restoreAsk(): AskSession | null {
  const saved = readJson('session', KEYS.ask, isAskSession)
  if (saved === null || saved.status !== 'waiting') return saved
  return { ...saved, status: 'error', finishedAt: saved.startedAt, seen: false }
}

function newSessionId(): string {
  const bytes = new Uint8Array(SESSION_ID_LENGTH)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => SESSION_ID_CHARS[b % SESSION_ID_CHARS.length]).join('')
}

function newStudyRecord(surveyId: string): StudyRecord {
  return {
    surveyId,
    sessionId: newSessionId(),
    startedAt: Date.now(),
    endedAt: null,
    detailOpened: [],
    keptAfterReason: [],
    originalOpened: 0,
    traversed: 0,
    asked: 0,
    dirs: [],
  }
}

/**
 * 旗と研究のログの文脈。
 * - 調査のセッション中: サーバーが返したブロックの旗（R4）と、記録する口。課題のあいだだけ画面を開け、
 *   ほかの段階で画面を開いたら調査の入口へ戻す（条件の違う画面を先に見せない）。
 * - 調査でないとき: R8 の既定の旗（開発ビルドの ?variant=V02 は R9）と、何も記録しない口。
 */
function NaviProviders({ children }: { children: ReactNode }) {
  const study = useStudy()
  const location = useLocation()
  const onGate = useMatch('/navi/s/:token') !== null
  const fallback = useFallbackVariant(study === null, location.search)
  const studyVariant = study?.variant ?? null
  const fromStudy = useMemo(() => (studyVariant === null ? DEFAULT_VARIANT : toVariantState(studyVariant)), [studyVariant])
  if (study !== null && !onGate && !isTaskRunning(study)) return <Navigate to={study.gatePath} replace />
  return (
    <VariantContext.Provider value={study === null ? fallback : fromStudy}>
      <ResearchLogContext.Provider value={study === null ? NOOP_RESEARCH_LOG : RESEARCH_LOG}>{children}</ResearchLogContext.Provider>
    </VariantContext.Provider>
  )
}

interface StatusScreenProps {
  heading: string
  message?: string
  onRetry?: () => void
}

/** 学科が決まる前の、読み込み中と失敗の画面 */
function StatusScreen({ heading, message, onRetry }: StatusScreenProps) {
  return (
    <div className="navi-app">
      <title>コースナビ</title>
      <div className="sp">
        <header className="bar">
          <span className="brand">コースナビ</span>
        </header>
        <PageFrame>
          <div role={onRetry === undefined ? 'status' : 'alert'}>
            <h1 className="title">{heading}</h1>
            {message !== undefined && <p className="text">{message}</p>}
          </div>
          {onRetry !== undefined && (
            <div className="page-acts">
              <button className="primary" type="button" onClick={onRetry}>
                もう一度読み込む
              </button>
            </div>
          )}
        </PageFrame>
      </div>
    </div>
  )
}

export default function NaviApp() {
  const location = useLocation()
  const studyLink = useMatch('/navi/s/:token')
  const [initial] = useState(() => readInitialParams(location.search))
  const [source] = useState<NaviDataSource>(createNaviDataSource)
  // 系統図の線の種類は旗（rule_edges）で決まる。旗はいまは既定（V00 相当）
  const edgeTypes = ruleEdgeTypes(DEFAULT_VARIANT.flags)
  const [reload, setReload] = useState(0)
  const retry = useCallback(() => setReload((n) => n + 1), [])

  // D1 の学科の一覧を読み終えてから、リンクと端末の学科を照らす
  const listDepartments = useCallback((signal: AbortSignal) => source.listDepartments(signal), [source])
  const departments = useLoadable(`departments#${reload}`, listDepartments, '学科の一覧')
  const list = departments?.status === 'ready' ? departments.value : null
  const [chosenId, setChosenId] = useState<string | null>(null)
  // 調査のセッション中は、セッションの学科（R1 の department_id。API の学科 ID）に決める。
  // タブを開き直して chosenId が消えても、学科の一覧やリンクに左右されない
  const study = useStudy()
  const studyDeptId = study === null ? null : study.session.department_id
  const deptId = studyDeptId ?? chosenId ?? (list === null ? null : pickDepartment(list, initial))
  useEffect(() => {
    if (deptId !== null) writeJson('local', KEYS.dept, deptId)
  }, [deptId])

  const loadDepartment = useCallback(
    (signal: AbortSignal) => {
      if (deptId === null) return Promise.reject(new Error('学科が決まっていません'))
      if (edgeTypes === null) return Promise.reject(new Error('rule_edges=with_inferred はまだ使えません（制約 C7）'))
      return source.loadDepartment(deptId, edgeTypes, signal)
    },
    [deptId, edgeTypes, source],
  )
  const deptLoad = useLoadable(
    deptId === null ? null : `${deptId}|${edgeTypes?.join(',') ?? ''}#${reload}`,
    loadDepartment,
    '学科のデータ',
  )

  // R6-1: このページの言語は日本語（index.html は既存のテスト画面と共有なので、ここで切り替えて戻す）
  useEffect(() => {
    const before = document.documentElement.lang
    document.documentElement.lang = 'ja'
    return () => {
      document.documentElement.lang = before
    }
  }, [])

  const chooseDept = useCallback((id: string) => setChosenId(id), [])

  // 調査のカードの URL は、学科えらびより先に調査の入口へ
  if (studyLink !== null) {
    return (
      <NaviProviders>
        <StudyGate token={studyLink.params.token ?? ''} chooseDept={chooseDept} />
      </NaviProviders>
    )
  }
  if (departments === null || departments.status === 'loading') {
    return <StatusScreen heading="読み込んでいます" />
  }
  if (departments.status === 'failed') {
    return (
      <StatusScreen heading="学科の一覧を読み込めませんでした" message={apiErrorMessage(departments.error)} onRetry={retry} />
    )
  }
  // 学科なしで開いたときは W7（学科えらび）から（UX 仕様 S1-d）
  if (deptId === null) {
    return (
      <NaviProviders>
        <div className="navi-app">
          <title>学科えらび | コースナビ</title>
          <div className="sp">
            <header className="bar">
              <span className="brand">コースナビ</span>
            </header>
            <DepartmentScreen departments={departments.value} onChoose={chooseDept} />
          </div>
        </div>
      </NaviProviders>
    )
  }
  if (deptLoad === null || deptLoad.status === 'loading') {
    return <StatusScreen heading="読み込んでいます" />
  }
  if (deptLoad.status === 'failed') {
    return <StatusScreen heading="学科のデータを読み込めませんでした" message={apiErrorMessage(deptLoad.error)} onRetry={retry} />
  }
  return (
    <NaviProviders>
      <NaviRoot dept={deptLoad.value} departments={departments.value} source={source} initial={initial} chooseDept={chooseDept} />
    </NaviProviders>
  )
}

interface PlanProvidersProps {
  diagnose: DiagnoseState
  refine: PlanRefineState
  checkpoints: CheckpointsState
  children: ReactNode
}

/** 診断・プランの微修正・履修状況のチェックの文脈 */
function PlanProviders({ diagnose, refine, checkpoints, children }: PlanProvidersProps) {
  return (
    <DiagnoseContext.Provider value={diagnose}>
      <PlanRefineContext.Provider value={refine}>
        <CheckpointsContext.Provider value={checkpoints}>{children}</CheckpointsContext.Provider>
      </PlanRefineContext.Provider>
    </DiagnoseContext.Provider>
  )
}

interface NaviRootProps {
  dept: Department
  departments: DepartmentSummary[]
  source: NaviDataSource
  initial: InitialParams
  chooseDept: (id: string) => void
}

/** 学科が決まったあとの状態と画面 */
function NaviRoot({ dept, departments, source, initial, chooseDept }: NaviRootProps) {
  const location = useLocation()
  const isPc = useMediaQuery(PC_QUERY)
  const reducedMotion = useMediaQuery(REDUCED_MOTION_QUERY)
  const { log } = useResearchLog()
  const flags = useFlags()
  // 偽のアダプタは開発ビルドで ?wait= を付けたときだけ（本番のビルドには入らない）
  const adapter = useMemo<AskAdapter>(
    () => (import.meta.env.DEV && initial.wait !== null ? createFakeAskAdapter(initial.wait) : createHttpAskAdapter()),
    [initial.wait],
  )
  const naviData = useMemo<NaviData>(
    () => ({ source, ...createCourseStore(source, { ownFaculty: dept.faculty }) }),
    [source, dept.faculty],
  )
  const assumedTerm = useMemo<TermKey>(() => ({ year: initial.assumedYear, half: '春' }), [initial.assumedYear])

  /* ---------- 時間割の学期・読み上げ・知らせ ---------- */
  const [focusTerm, setFocusTerm] = useState<TermKey>(assumedTerm)
  const [announcement, setAnnouncement] = useState('')
  const announce = useCallback((text: string) => setAnnouncement(text), [])
  const [toast, setToast] = useState<ToastState | null>(null)
  const toastSeq = useRef(0)
  const clearToast = useCallback((id: number) => setToast((t) => (t?.id === id ? null : t)), [])

  /* ---------- 候補 ---------- */
  const [shortlist, setShortlist] = useState<string[]>(() => readJson('local', KEYS.shortlist, isStringArray) ?? [])
  useEffect(() => writeJson('local', KEYS.shortlist, shortlist), [shortlist])

  /* ---------- 調査モード ---------- */
  const [study, setStudy] = useState<StudyRecord | null>(() => readJson('local', KEYS.study, isStudyRecord))
  useEffect(() => writeJson('local', KEYS.study, study), [study])
  const track = useCallback((event: StudyEvent) => {
    setStudy((s) => {
      if (s === null) return s
      switch (event.type) {
        case 'detail':
          return s.detailOpened.includes(event.code) ? s : { ...s, detailOpened: [...s.detailOpened, event.code] }
        case 'original':
          return { ...s, originalOpened: s.originalOpened + 1 }
        case 'traverse':
          return { ...s, traversed: s.traversed + 1 }
        case 'ask':
          return { ...s, asked: s.asked + 1 }
        case 'dir':
          return { ...s, dirs: [...s.dirs, event.dirId] }
      }
    })
  }, [])

  const isKept = useCallback((code: string) => shortlist.includes(code), [shortlist])
  const courseName = useCallback((code: string) => findCourse(dept, code)?.name ?? code, [dept])

  const toggleKeep = useCallback(
    (code: string, from: ShortlistFrom = 'unknown') => {
      if (shortlist.includes(code)) {
        // 外すときは知らせを消し、読み上げだけで伝える（同じ＋がもう一度押せる。E1 5章）
        setShortlist(shortlist.filter((c) => c !== code))
        log('shortlist_remove', { syllabus_id: code, from })
        setToast(null)
        announce(`${courseName(code)}を候補から外しました。`)
        return
      }
      const next = [...shortlist, code]
      setShortlist(next)
      log('shortlist_add', { syllabus_id: code, from })
      setStudy((s) =>
        s !== null && s.detailOpened.includes(code) && !s.keptAfterReason.includes(code)
          ? { ...s, keptAfterReason: [...s.keptAfterReason, code] }
          : s,
      )
      const course = findCourse(dept, code)
      if (course === undefined) {
        // 学科データに無い科目（自由記述の結果）は時間割に入らないので、読み上げだけ
        announce(`${code}を候補に入れました。`)
        return
      }
      toastSeq.current += 1
      setToast({ id: toastSeq.current, kind: 'added', code })
      announce(addedNotice(dept, next, course, focusTerm).speech)
    },
    [announce, courseName, dept, focusTerm, log, shortlist],
  )

  const removeKeep = useCallback(
    (code: string) => {
      const index = shortlist.indexOf(code)
      if (index < 0) return
      setShortlist(shortlist.filter((c) => c !== code))
      log('shortlist_remove', { syllabus_id: code, from: 'timetable' })
      toastSeq.current += 1
      setToast({ id: toastSeq.current, kind: 'removed', code, index })
      announce(`${courseName(code)}を候補から外しました。`)
    },
    [announce, courseName, log, shortlist],
  )

  const keepAll = useCallback(
    (codes: string[], from: ShortlistFrom) => {
      const added = codes.filter((code, i) => !shortlist.includes(code) && codes.indexOf(code) === i)
      if (added.length === 0) return
      setShortlist([...shortlist, ...added])
      for (const code of added) log('shortlist_add', { syllabus_id: code, from })
      setToast(null)
      announce(`${added.length}科目を候補に入れました。`)
    },
    [announce, log, shortlist],
  )

  const undoRemove = useCallback(
    (t: ToastState) => {
      if (t.kind !== 'removed') return
      if (!shortlist.includes(t.code)) log('shortlist_add', { syllabus_id: t.code, from: 'undo' })
      setShortlist((list) => {
        if (list.includes(t.code)) return list
        const copy = [...list]
        copy.splice(Math.min(t.index, copy.length), 0, t.code)
        return copy
      })
      setToast((cur) => (cur?.id === t.id ? null : cur))
      announce(`${courseName(t.code)}を元に戻しました。`)
    },
    [announce, courseName, log, shortlist],
  )

  /* ---------- 自由記述 ---------- */
  const [ask, setAsk] = useState<AskSession | null>(restoreAsk)
  const [askDraft, setAskDraftState] = useState<string>(() => readJson('session', KEYS.askDraft, isString) ?? '')
  /** 最後に送った文。送ったあと欄に残っていても、送っていない文には数えない */
  const [askSent, setAskSent] = useState<string>(() => readJson('session', KEYS.askSent, isString) ?? '')
  const askDraftUnsent = askDraft.trim() !== '' && askDraft.trim() !== askSent
  const askControl = useRef<AbortController | null>(null)
  useEffect(() => writeJson('session', KEYS.ask, ask), [ask])
  useEffect(() => writeJson('session', KEYS.askSent, askSent), [askSent])
  const setAskDraft = useCallback((text: string) => {
    setAskDraftState(text)
    writeJson('session', KEYS.askDraft, text)
  }, [])

  const sendAsk = useCallback(
    (interest: string, withGuardrail: boolean, opts?: { retry?: boolean }): string | null => {
      if (ask !== null && ask.status === 'waiting') return null
      const seq = (readJson('session', KEYS.askSeq, isNumber) ?? 0) + 1
      writeJson('session', KEYS.askSeq, seq)
      const localId = String(seq)
      const question = composeQuestion(dept, interest, withGuardrail)
      // chat_send を先に記録し、その event_id を A1 の client_event_id に渡す（サーバーが書く chat_response と結ぶ）
      const clientEventId = log('chat_send', {
        input: interest,
        question,
        guardrail: withGuardrail,
        ask_local_id: localId,
        ...(opts?.retry === true ? { retry: true } : {}),
      })
      const session: AskSession = {
        localId,
        interest,
        guardrail: withGuardrail,
        status: 'waiting',
        startedAt: Date.now(),
        finishedAt: null,
        result: null,
        seen: false,
      }
      setAsk(session)
      setAskDraft(interest)
      setAskSent(interest)
      track({ type: 'ask' })

      const control = new AbortController()
      askControl.current = control
      let timedOut = false
      const timer = setTimeout(() => {
        timedOut = true
        control.abort()
      }, ASK_TIMEOUT_MS)
      const finish = (patch: Partial<AskSession>) =>
        setAsk((cur) => (cur !== null && cur.localId === localId ? { ...cur, ...patch, finishedAt: Date.now() } : cur))

      adapter
        .ask({ question, rawInput: interest, clientEventId }, control.signal)
        .then((result) => finish({ status: result.sources.length === 0 ? 'empty' : 'done', result }))
        .catch((err: unknown) => {
          if (timedOut) {
            finish({ status: 'timeout' })
            return
          }
          if (control.signal.aborted) return // ［やめる］で止めた
          console.error('自由記述の回答を受け取れませんでした', err)
          finish({ status: 'error' })
        })
        .finally(() => {
          clearTimeout(timer)
          if (askControl.current === control) askControl.current = null
        })
      return localId
    },
    [adapter, ask, dept, log, setAskDraft, track],
  )
  /** ［やめる］と［この結果を閉じる］。入力した文は askDraft に残る（UX 仕様 C11） */
  const cancelAsk = useCallback(() => {
    askControl.current?.abort()
    askControl.current = null
    setAsk(null)
  }, [])
  const markAskSeen = useCallback(() => {
    setAsk((cur) => (cur !== null && cur.status !== 'waiting' && !cur.seen ? { ...cur, seen: true } : cur))
  }, [])

  /* ---------- 調査の開始と終了 ---------- */
  const startStudy = useCallback(
    (surveyId: string, mode: 'fresh' | 'continue') => {
      if (mode === 'continue') {
        setStudy((s) => (s === null ? newStudyRecord(surveyId) : { ...s, endedAt: null }))
        return
      }
      cancelAsk()
      setAskDraft('')
      setAskSent('')
      setShortlist([])
      setStudy(newStudyRecord(surveyId))
    },
    [cancelAsk, setAskDraft],
  )
  const endStudy = useCallback(() => {
    setStudy((s) => (s === null ? s : { ...s, endedAt: Date.now() }))
  }, [])

  const [lastDir, setLastDir] = useState('default')

  /* ---------- 診断・プランの微修正・履修状況のチェック（状態は navi/useDiagnose・usePlanRefine・useStatus） ---------- */
  const [diagnoseSource] = useState<DiagnoseSource>(createDiagnoseSource)
  const diagnose = useDiagnoseState({
    deptId: dept.id,
    enabled: flags.diagnose === 'quiz',
    source: diagnoseSource,
    log,
    loadCourse: naviData.loadCourse,
  })
  // 微修正は、いまのプラン（足し外しの後）と、プランを作った答えの版・指紋・要約を送る
  const refineTarget = useMemo<RefineTarget | null>(
    () =>
      diagnose.plan === null || diagnose.working === null
        ? null
        : {
            configVersion: diagnose.plan.config_version,
            answersDigest: diagnose.plan.answers_digest,
            plan: diagnose.working,
            summary: diagnose.summary,
          },
    [diagnose.plan, diagnose.working, diagnose.summary],
  )
  const refine = usePlanRefineState({ adapter, dept, log, target: refineTarget })
  const checkpoints = useCheckpointsState(log)

  const ctx: NaviContextValue = useMemo(
    () => ({
      dept,
      assumedYear: initial.assumedYear,
      assumedTerm,
      isPc,
      reducedMotion,
      shortlist,
      isKept,
      toggleKeep,
      keepAll,
      removeKeep,
      undoRemove,
      focusTerm,
      setFocusTerm,
      toast,
      clearToast,
      announcement,
      announce,
      ask,
      askDraft,
      setAskDraft,
      askDraftUnsent,
      sendAsk,
      cancelAsk,
      closeAsk: cancelAsk,
      markAskSeen,
      study,
      track,
      startStudy,
      endStudy,
      lastDir,
      setLastDir,
    }),
    [
      dept,
      initial.assumedYear,
      assumedTerm,
      isPc,
      reducedMotion,
      shortlist,
      isKept,
      toggleKeep,
      keepAll,
      removeKeep,
      undoRemove,
      focusTerm,
      toast,
      clearToast,
      announcement,
      announce,
      ask,
      askDraft,
      setAskDraft,
      askDraftUnsent,
      sendAsk,
      cancelAsk,
      markAskSeen,
      study,
      track,
      startStudy,
      endStudy,
      lastDir,
    ],
  )

  return (
    <div className="navi-app">
      <title>コースナビ</title>
      <NaviContext.Provider value={ctx}>
        <NaviDataContext.Provider value={naviData}>
          <PlanProviders diagnose={diagnose} refine={refine} checkpoints={checkpoints}>
            <NaviShell>
              <Routes>
                <Route element={<NaviLayout />}>
                  <Route
                    index
                    element={
                      initial.studySurveyId !== null && location.key === 'default' ? (
                        <Navigate to={`/navi/study?s=${encodeURIComponent(initial.studySurveyId)}`} replace />
                      ) : flags.diagnose === 'quiz' && !diagnose.shown ? (
                        // 診断のある変種は、最初に診断を出す（一度出したら、さがすはそのまま開く）
                        <Navigate to={DIAGNOSE_HREF} replace />
                      ) : (
                        <SearchScreen />
                      )
                    }
                  />
                  <Route path="ask/:localId" element={<SearchScreen />} />
                  <Route path="course/:code" element={<CourseScreen />} />
                  <Route path="group/:frameId" element={<GroupScreen />} />
                  <Route path="timetable" element={<TimetableScreen />} />
                </Route>
                {/* 改訂前の候補の画面のリンク */}
                <Route path="shortlist" element={<Navigate to="/navi/timetable" replace />} />
                <Route path="diagnose" element={<DiagnoseScreen />} />
                <Route path="about" element={<AboutScreen />} />
                <Route path="departments" element={<DepartmentScreen departments={departments} onChoose={chooseDept} />} />
                <Route path="study" element={<StudyStartScreen />} />
                <Route path="study/end" element={<StudyEndScreen />} />
                <Route path="*" element={<Navigate to="/navi" replace />} />
              </Routes>
            </NaviShell>
          </PlanProviders>
        </NaviDataContext.Provider>
      </NaviContext.Provider>
    </div>
  )
}
