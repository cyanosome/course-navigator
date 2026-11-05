/**
 * コースナビ（/navi の下）の画面モック。UX 仕様（docs/frontend/ux-spec.md）の流れに、画面の改訂案 E1（2026-11-04）の
 * 見た目と時間割を組む体験を合わせた。データは架空の見本（src/navi/fixture*.ts）で、本物の API は呼ばない。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useMatch } from 'react-router-dom'
import '../../navi/fonts.css'
import '../../navi/navi.css'
import { FIXTURE_DEPARTMENTS } from '../../navi/fixtureDepartment'
import type { AskAdapter } from '../../navi/ask'
import { composeQuestion, createFakeAskAdapter, isFakeWaitMode } from '../../navi/ask'
import type { FakeWaitMode } from '../../navi/ask'
import { findCourse } from '../../navi/graph'
import { PC_QUERY, REDUCED_MOTION_QUERY, useMediaQuery } from '../../navi/hooks'
import { NOOP_RESEARCH_LOG, ResearchLogContext } from '../../navi/research'
import { ASK_TIMEOUT_MS, isAskSession, isStudyRecord, NaviContext } from '../../navi/state'
import type { AskSession, NaviContextValue, StudyEvent, StudyRecord, ToastState } from '../../navi/state'
import { isNumber, isString, isStringArray, KEYS, readJson, writeJson } from '../../navi/storage'
import type { TermKey } from '../../navi/timetable'
import type { Department } from '../../navi/types'
import { DEFAULT_VARIANT, VariantContext } from '../../navi/variant'
import { addedNotice } from '../../navi/views'
import AboutScreen from './AboutScreen'
import CourseScreen from './CourseScreen'
import DepartmentScreen from './DepartmentScreen'
import GroupScreen from './GroupScreen'
import NaviLayout from './NaviLayout'
import NaviShell from './NaviShell'
import SearchScreen from './SearchScreen'
import StudyEndScreen from './StudyEndScreen'
import StudyGate from './StudyGate'
import StudyStartScreen from './StudyStartScreen'
import TimetableScreen from './TimetableScreen'

const SESSION_ID_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
const SESSION_ID_LENGTH = 6
const MAX_ASSUMED_YEAR = 4

interface InitialParams {
  deptId: string | null
  assumedYear: number
  wait: FakeWaitMode
  studySurveyId: string | null
}

/** リンクの指定（?d= 学科、?t= 想定の学年、?wait= 偽の待ち方、?mode=study&s= 調査）を読み、端末に覚える */
function readInitialParams(search: string): InitialParams {
  const params = new URLSearchParams(search)
  const d = params.get('d')
  if (d !== null && FIXTURE_DEPARTMENTS.some((x) => x.id === d)) writeJson('local', KEYS.dept, d)
  const t = Number(params.get('t'))
  if (Number.isInteger(t) && t >= 1 && t <= MAX_ASSUMED_YEAR) writeJson('session', KEYS.assumedYear, t)
  const wait = params.get('wait')
  if (isFakeWaitMode(wait)) writeJson('session', KEYS.wait, wait)
  const storedWait = readJson('session', KEYS.wait, isString)
  const s = params.get('s')
  return {
    deptId: readJson('local', KEYS.dept, isString),
    assumedYear: readJson('session', KEYS.assumedYear, isNumber) ?? 1,
    wait: isFakeWaitMode(storedWait) ? storedWait : 'short',
    studySurveyId: params.get('mode') === 'study' && s !== null && s !== '' ? s : null,
  }
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

/** 旗と研究のログの文脈。いまは既定の旗（V00 相当）と、何も記録しない口 */
function NaviProviders({ children }: { children: ReactNode }) {
  return (
    <VariantContext.Provider value={DEFAULT_VARIANT}>
      <ResearchLogContext.Provider value={NOOP_RESEARCH_LOG}>{children}</ResearchLogContext.Provider>
    </VariantContext.Provider>
  )
}

export default function NaviApp() {
  const location = useLocation()
  const studyLink = useMatch('/navi/s/:token')
  const [initial] = useState(() => readInitialParams(location.search))
  const [deptId, setDeptId] = useState<string | null>(initial.deptId)
  const dept = FIXTURE_DEPARTMENTS.find((d) => d.id === deptId) ?? null

  // R6-1: このページの言語は日本語（index.html は既存のテスト画面と共有なので、ここで切り替えて戻す）
  useEffect(() => {
    const before = document.documentElement.lang
    document.documentElement.lang = 'ja'
    return () => {
      document.documentElement.lang = before
    }
  }, [])

  const chooseDept = useCallback((id: string) => {
    writeJson('local', KEYS.dept, id)
    setDeptId(id)
  }, [])

  // 調査のカードの URL は、学科えらびより先に調査の入口へ
  if (studyLink !== null) {
    return (
      <NaviProviders>
        <StudyGate />
      </NaviProviders>
    )
  }
  // 学科なしで開いたときは W7（学科えらび）から（UX 仕様 S1-d）
  if (dept === null) {
    return (
      <NaviProviders>
        <div className="navi-app">
          <title>学科えらび | コースナビ</title>
          <div className="sp">
            <header className="bar">
              <span className="brand">コースナビ</span>
            </header>
            <DepartmentScreen departments={FIXTURE_DEPARTMENTS} onChoose={chooseDept} />
          </div>
        </div>
      </NaviProviders>
    )
  }
  return (
    <NaviProviders>
      <NaviRoot dept={dept} initial={initial} chooseDept={chooseDept} />
    </NaviProviders>
  )
}

interface NaviRootProps {
  dept: Department
  initial: InitialParams
  chooseDept: (id: string) => void
}

/** 学科が決まったあとの状態と画面 */
function NaviRoot({ dept, initial, chooseDept }: NaviRootProps) {
  const location = useLocation()
  const isPc = useMediaQuery(PC_QUERY)
  const reducedMotion = useMediaQuery(REDUCED_MOTION_QUERY)
  const adapter = useMemo<AskAdapter>(() => createFakeAskAdapter(initial.wait), [initial.wait])
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
    (code: string) => {
      if (shortlist.includes(code)) {
        // 外すときは知らせを消し、読み上げだけで伝える（同じ＋がもう一度押せる。E1 5章）
        setShortlist(shortlist.filter((c) => c !== code))
        setToast(null)
        announce(`${courseName(code)}を候補から外しました。`)
        return
      }
      const next = [...shortlist, code]
      setShortlist(next)
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
    [announce, courseName, dept, focusTerm, shortlist],
  )

  const removeKeep = useCallback(
    (code: string) => {
      const index = shortlist.indexOf(code)
      if (index < 0) return
      setShortlist(shortlist.filter((c) => c !== code))
      toastSeq.current += 1
      setToast({ id: toastSeq.current, kind: 'removed', code, index })
      announce(`${courseName(code)}を候補から外しました。`)
    },
    [announce, courseName, shortlist],
  )

  const undoRemove = useCallback(
    (t: ToastState) => {
      if (t.kind !== 'removed') return
      setShortlist((list) => {
        if (list.includes(t.code)) return list
        const copy = [...list]
        copy.splice(Math.min(t.index, copy.length), 0, t.code)
        return copy
      })
      setToast((cur) => (cur?.id === t.id ? null : cur))
      announce(`${courseName(t.code)}を元に戻しました。`)
    },
    [announce, courseName],
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
    (interest: string, withGuardrail: boolean): string | null => {
      if (ask !== null && ask.status === 'waiting') return null
      const seq = (readJson('session', KEYS.askSeq, isNumber) ?? 0) + 1
      writeJson('session', KEYS.askSeq, seq)
      const localId = String(seq)
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
        .ask(composeQuestion(dept, interest, withGuardrail), control.signal)
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
    [adapter, ask, dept, setAskDraft, track],
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
        <NaviShell>
          <Routes>
            <Route element={<NaviLayout />}>
              <Route
                index
                element={
                  initial.studySurveyId !== null && location.key === 'default' ? (
                    <Navigate to={`/navi/study?s=${encodeURIComponent(initial.studySurveyId)}`} replace />
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
            <Route path="about" element={<AboutScreen />} />
            <Route path="departments" element={<DepartmentScreen departments={FIXTURE_DEPARTMENTS} onChoose={chooseDept} />} />
            <Route path="study" element={<StudyStartScreen />} />
            <Route path="study/end" element={<StudyEndScreen />} />
            <Route path="*" element={<Navigate to="/navi" replace />} />
          </Routes>
        </NaviShell>
      </NaviContext.Provider>
    </div>
  )
}
