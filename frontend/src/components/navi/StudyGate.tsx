import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import '../../navi/study.css'
import { currentTaskId, useStudy } from '../../navi/research'
import type { StudyState } from '../../navi/research'
import { BLOCK_GUIDE, blockLabel, DRAFT_MARK, isPracticeBlock, TASKS } from '../../navi/studyConfig'
import {
  activeQuestionnaires,
  endBlock,
  finishStudy,
  openStudy,
  recordConsent,
  startBlock,
  startTask,
  studyErrorText,
  submitQuestionnaire,
} from '../../navi/studyFlow'
import BlockIntro from './BlockIntro'
import ConsentScreen from './ConsentScreen'
import Icon from './Icon'
import PageFrame from './PageFrame'
import QuestionnaireForm from './QuestionnaireForm'
import { TaskBrief } from './TaskCard'
import { WIDE_SPACE } from '../../navi/views'

interface StudyGateProps {
  /** カードの URL のトークン */
  token: string
  /** 課題を始めるとき、セッションの学科を選ぶ（NaviApp の学科の状態） */
  chooseDept: (id: string) => void
}

/** 入口を開いたときのセッションの開始（R1・R2）。開発の StrictMode で効果が2回走っても、1回だけ呼ぶ */
const opening = new Map<string, Promise<void>>()

function openOnce(token: string, gatePath: string): Promise<void> {
  const cached = opening.get(gatePath)
  if (cached !== undefined) return cached
  const promise = openStudy(token, gatePath).catch((err: unknown) => {
    opening.delete(gatePath)
    throw err
  })
  opening.set(gatePath, promise)
  return promise
}

type Open = { status: 'pending' } | { status: 'ready' } | { status: 'error'; text: string }

/**
 * 調査の入口（/navi/s/<トークン>）。カードの URL から開く。学科はセッションから決まるので、学科えらびより先に出す。
 * 同意 → 事前の質問 → ブロックの前の画面 → 課題の前の画面 →（画面で探して答える）→ 質問票 → … → おわり、を段階ごとに出す。
 * 課題のあいだだけ画面（/navi）へ移り、それ以外の段階で画面を開くと、ここへ戻す（NaviApp の NaviProviders）。
 */
export default function StudyGate({ token, chooseDept }: StudyGateProps) {
  const study = useStudy()
  const navigate = useNavigate()
  const gatePath = `/navi/s/${encodeURIComponent(token)}`
  const [open, setOpen] = useState<Open>({ status: 'pending' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    let live = true
    openOnce(token, gatePath)
      .then(() => {
        if (live) setOpen({ status: 'ready' })
      })
      .catch((err: unknown) => {
        console.error('調査のセッションを始められませんでした', err)
        if (live) setOpen({ status: 'error', text: studyErrorText(err) })
      })
    return () => {
      live = false
    }
  }, [token, gatePath, retry])

  const run = (action: () => Promise<void> | void) => {
    setBusy(true)
    setError(null)
    Promise.resolve()
      .then(action)
      .catch((err: unknown) => {
        console.error('調査の段階を進められませんでした', err)
        setError(studyErrorText(err))
      })
      .finally(() => setBusy(false))
  }

  // R5（ブロックの終了）と R7（終わり）は、押さずに進める。失敗したら［もう一度］を出す
  const phaseKind = study?.phase.kind
  const [autoTry, setAutoTry] = useState(0)
  useEffect(() => {
    if (open.status !== 'ready') return
    if (phaseKind !== 'blockEnd' && phaseKind !== 'finishing') return
    const action = phaseKind === 'blockEnd' ? endBlock : finishStudy
    let live = true
    action().catch((err: unknown) => {
      console.error('調査の段階を進められませんでした', err)
      if (live) setError(studyErrorText(err))
    })
    return () => {
      live = false
    }
  }, [open.status, phaseKind, autoTry])

  let body: ReactNode
  if (open.status === 'error') {
    body = (
      <Problem
        text={open.text}
        onRetry={() => {
          setOpen({ status: 'pending' })
          setRetry((n) => n + 1)
        }}
      />
    )
  } else if (open.status === 'pending' || study === null || study.gatePath !== gatePath) {
    body = (
      <p className="text" role="status">
        読み込んでいます。
      </p>
    )
  } else {
    body = (
      <PhaseView
        study={study}
        busy={busy}
        run={run}
        onEnterTask={() => {
          startTask()
          chooseDept(study.session.department_id)
          navigate('/navi')
        }}
        onBackToTask={() => navigate('/navi')}
      />
    )
  }

  return (
    <div className="navi-app">
      <title>調査 | コースナビ</title>
      <div className="sp">
        <header className="bar">
          <span className="brand">コースナビ</span>
        </header>
        <PageFrame>
          {body}
          {error !== null && open.status === 'ready' && (
            <Problem
              text={error}
              onRetry={
                phaseKind === 'blockEnd' || phaseKind === 'finishing'
                  ? () => {
                      setError(null)
                      setAutoTry((n) => n + 1)
                    }
                  : undefined
              }
            />
          )}
        </PageFrame>
      </div>
    </div>
  )
}

interface ProblemProps {
  text: string
  onRetry?: () => void
}

function Problem({ text, onRetry }: ProblemProps) {
  return (
    <div className="msg">
      <p className="msg-line" role="alert">
        <span className="ic-wrap">
          <Icon name="warn" small />
        </span>
        <span>{text}</span>
      </p>
      {onRetry !== undefined && (
        <div className="msg-acts">
          <button className="text-btn" type="button" onClick={onRetry}>
            もう一度
          </button>
        </div>
      )}
    </div>
  )
}

interface PhaseViewProps {
  study: StudyState
  busy: boolean
  run: (action: () => Promise<void> | void) => void
  onEnterTask: () => void
  onBackToTask: () => void
}

/** 段階ごとの画面 */
function PhaseView({ study, busy, run, onEnterTask, onBackToTask }: PhaseViewProps) {
  const { phase, session } = study
  const set = activeQuestionnaires()
  const taskCount = study.plan?.task_ids.length ?? 0
  const numbers = session.blocks.map((b) => b.block)
  const firstBlock = Math.min(...numbers)
  const firstMain = Math.min(...numbers.filter((b) => !isPracticeBlock(b)))

  switch (phase.kind) {
    case 'consent':
      return <ConsentScreen busy={busy} onAnswer={(agreed, serial) => run(() => recordConsent(agreed, serial))} />
    case 'declined':
      return (
        <>
          <h1 className="title">ここで終わりです</h1>
          <p className="lead">お時間をいただき、ありがとうございました。</p>
        </>
      )
    case 'preQuestions':
      return (
        <>
          <h1 className="title">はじめに</h1>
          <QuestionnaireForm
            key="pre"
            questionnaires={set.pre}
            submitLabel="次へ"
            busy={busy}
            onSubmit={(answers) => run(() => submitQuestionnaire('pre', answers))}
          />
        </>
      )
    case 'blockIntro':
      return (
        <BlockIntro
          block={phase.block}
          first={phase.block === firstBlock}
          changed={phase.block !== firstBlock && phase.block !== firstMain}
          busy={busy}
          onStart={() => run(startBlock)}
        />
      )
    case 'taskIntro': {
      const taskId = study.plan?.task_ids[phase.taskIndex] ?? ''
      const task = TASKS[taskId]
      // ブロック2の初めに画面の案内（事前登録 study1 の 2.5）。AI の欄の段落は、AI の欄がある画面のときだけ
      const guide = !isPracticeBlock(phase.block) && phase.block !== firstMain && phase.taskIndex === 0
      return (
        <>
          <h1 className="title">
            {blockLabel(phase.block)}{WIDE_SPACE}課題{phase.taskIndex + 1}/{taskCount}
          </h1>
          {guide && (
            <section className="sec" aria-label="画面の案内">
              <p className="lead">
                {BLOCK_GUIDE.common}
                {BLOCK_GUIDE.draft && <span className="draft">{DRAFT_MARK}</span>}
              </p>
              {study.variant?.flags.assistant === 'on' && <p className="lead">{BLOCK_GUIDE.ai}</p>}
            </section>
          )}
          <section className="sec">
            <TaskBrief taskId={taskId} task={task} />
            <p className="text">
              {task === undefined || task.kind === 'pick'
                ? 'その人になったつもりで、画面を使って探してください。答えは、画面の上の［答える］から送ります。'
                : task.kind === 'diagnose'
                  ? 'プランが出たら、同じ画面のまま次の課題に進みます。'
                  : '出すときは、画面の上の［これで出す］を押します。'}
            </p>
          </section>
          <div className="page-acts">
            <button className="primary" type="button" onClick={onEnterTask}>
              始める
            </button>
          </div>
        </>
      )
    }
    case 'task':
      return (
        <>
          <h1 className="title">課題の途中です</h1>
          <div className="page-acts">
            <button className="primary" type="button" onClick={onBackToTask}>
              画面に戻る
            </button>
          </div>
        </>
      )
    case 'taskQuestions':
      return (
        <>
          <h1 className="title">
            {blockLabel(phase.block)}{WIDE_SPACE}課題{phase.taskIndex + 1}について
          </h1>
          <QuestionnaireForm
            key={currentTaskId(study) ?? phase.taskIndex}
            questionnaires={set.task}
            submitLabel="次へ"
            busy={busy}
            onSubmit={(answers) => run(() => submitQuestionnaire('task', answers))}
          />
        </>
      )
    case 'blockQuestions':
      return (
        <>
          <h1 className="title">{blockLabel(phase.block)}について</h1>
          <QuestionnaireForm
            key={`block-${phase.block}`}
            questionnaires={set.block}
            submitLabel="次へ"
            busy={busy}
            onSubmit={(answers) => run(() => submitQuestionnaire('block', answers))}
          />
        </>
      )
    case 'finalQuestions':
      return (
        <>
          <h1 className="title">最後の質問</h1>
          <QuestionnaireForm
            key="final"
            questionnaires={set.final}
            submitLabel="送る"
            busy={busy}
            onSubmit={(answers) => run(() => submitQuestionnaire('final', answers))}
          />
        </>
      )
    case 'blockEnd':
    case 'finishing':
      return (
        <p className="text" role="status">
          記録を送っています。
        </p>
      )
    case 'done':
      return (
        <>
          <h1 className="title">おわりです</h1>
          <p className="lead">ご協力ありがとうございました。このあと、少し話を聞かせてください。</p>
        </>
      )
  }
}
