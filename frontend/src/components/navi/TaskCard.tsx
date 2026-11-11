import { useEffect, useId, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../../navi/study.css'
import { isAbortError } from '../../navi/api'
import { mappedCourseName, useNaviData } from '../../navi/dataSource'
import { planCodes, planPayload } from '../../navi/diagnose'
import { findCourse } from '../../navi/graph'
import { currentTaskId, useStudy } from '../../navi/research'
import { useNavi } from '../../navi/state'
import { checkpointPayload } from '../../navi/status'
import { blockLabel, CARD_TEXT, DRAFT_MARK, STUDY_CONTACT, TASKS } from '../../navi/studyConfig'
import type { PersonaCard, PickTaskDef, PlanTaskDef, TaskDef } from '../../navi/studyConfig'
import { continueAfterPlan, submitTask, submitTaskPayload } from '../../navi/studyFlow'
import { useDiagnose } from '../../navi/useDiagnose'
import { useCheckpoints } from '../../navi/useStatus'
import { WIDE_SPACE } from '../../navi/views'
import Icon from './Icon'

interface TaskBriefProps {
  taskId: string
  task: TaskDef | undefined
}

/** ペルソナの文と課題の文（調査の入口の課題の前の画面と、画面の上の課題の帯で同じものを出す） */
export function TaskBrief({ taskId, task }: TaskBriefProps) {
  if (task === undefined) {
    return <p className="text">課題「{taskId}」の文が設定にありません。{STUDY_CONTACT}</p>
  }
  if (task.kind !== 'pick') {
    return (
      <>
        <CardView card={task.card} />
        <p className="task-prompt">
          {task.prompt}
          {task.draft && <span className="draft">{DRAFT_MARK}</span>}
        </p>
      </>
    )
  }
  return (
    <>
      <p className="task-persona">
        {task.persona}
        {task.draft && <span className="draft">{DRAFT_MARK}</span>}
      </p>
      <p className="task-prompt">{task.prompt}</p>
    </>
  )
}

/** ペルソナのカード（事前登録 study1 の 3.2。人物・条件・守ること） */
function CardView({ card }: { card: PersonaCard }) {
  return (
    <div className="task-card" role="group" aria-label={'カード（' + card.name + '）'}>
      <p className="task-persona">
        {card.intro}
        {card.draft && <span className="draft">{DRAFT_MARK}</span>}
      </p>
      {card.traits.length > 0 && (
        <ul className="task-list">
          {card.traits.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      )}
      <p className="task-sub">{CARD_TEXT.conditionsTitle}</p>
      <ol className="task-list is-num">
        {card.conditions.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ol>
      {card.rules !== null && (
        <>
          <p className="task-sub">
            {CARD_TEXT.rulesTitle}
            {card.rules.draft && <span className="draft">{DRAFT_MARK}</span>}
          </p>
          <ul className="task-list">
            {card.rules.items.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
          <dl className="task-keep">
            {card.rules.keep.map((k) => (
              <div key={k.term}>
                <dt>{k.term}</dt>
                <dd>{k.names}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      <p className="task-sub">{CARD_TEXT.note}</p>
    </div>
  )
}

/**
 * 課題の帯（調査中、画面の上の帯の場所に出す）。診断の課題はカードと［これで出す］（PlanTaskBand）、
 * 前の調査の形の課題（pick）は PickTaskBand。
 */
export default function TaskCard() {
  const study = useStudy()
  if (study === null || study.phase.kind !== 'task' || study.plan === null) return null
  const taskId = currentTaskId(study) ?? ''
  const task = TASKS[taskId]
  const head = { block: study.phase.block, taskIndex: study.phase.taskIndex, count: study.plan.task_ids.length, gatePath: study.gatePath }
  if (task !== undefined && task.kind !== 'pick') return <PlanTaskBand key={taskId} taskId={taskId} task={task} {...head} />
  return <PickTaskBand key={taskId} taskId={taskId} task={task} {...head} />
}

interface BandProps<T> {
  taskId: string
  task: T
  block: number
  taskIndex: number
  count: number
  gatePath: string
}

/**
 * 診断の課題の帯。カードは閉じられる。課題 a（diagnose）はプランが出たら画面が記録し、同じ画面のまま課題 b へ続ける。
 * 課題 b と練習（fix）は［これで出す］で、最終プラン（学期ごとの syllabus_id）とチェックの一覧を task_submit に入れて
 * 調査の入口へ戻る（事前登録 study1 の 3.1・6.2）
 */
function PlanTaskBand({ taskId, task, block, taskIndex, count, gatePath }: BandProps<PlanTaskDef>) {
  const { working, plan, phase } = useDiagnose()
  const { checkpoints } = useCheckpoints()
  const navigate = useNavigate()
  const [cardOpen, setCardOpen] = useState(true)
  const [confirming, setConfirming] = useState(false)
  const cardId = useId()

  // 課題 a: プランが出た時点で記録して、課題 b へ（初期プランと、それを作った答えの版・指紋）
  const shown = task.kind === 'diagnose' && phase === 'plan' && plan !== null && working !== null
  useEffect(() => {
    if (!shown || plan === null || working === null) return
    continueAfterPlan(taskIndex, {
      plan: planPayload(working),
      course_count: planCodes(working).length,
      config_version: plan.config_version,
      answers_digest: plan.answers_digest,
    })
  }, [plan, shown, taskIndex, working])

  const submit = () => {
    if (working === null) return
    submitTaskPayload({
      plan: planPayload(working),
      course_count: planCodes(working).length,
      checkpoints: checkpoints.map(checkpointPayload),
      config_version: plan?.config_version ?? null,
      answers_digest: plan?.answers_digest ?? null,
    })
    navigate(gatePath)
  }

  return (
    <section className="task-band" aria-label="課題">
      <div className="task-head">
        <p className="task-label">
          {blockLabel(block)}
          {WIDE_SPACE}課題{taskIndex + 1}/{count}
        </p>
        <button className="band-btn" type="button" aria-expanded={cardOpen} aria-controls={cardId} onClick={() => setCardOpen((o) => !o)}>
          {cardOpen ? 'カードを閉じる' : 'カードを見る'}
        </button>
      </div>
      <div id={cardId} hidden={!cardOpen} className="task-brief">
        <TaskBrief taskId={taskId} task={task} />
      </div>
      {task.kind === 'fix' &&
        (working === null ? (
          <p className="task-sub">質問に答えてプランを出すと、ここから出せます。</p>
        ) : confirming ? (
          <div className="task-confirm">
            <p className="task-prompt">このプランで出しますか。出したあとは直せません。</p>
            <div className="page-acts">
              <button className="primary" type="button" onClick={submit}>
                出す
              </button>
              <button className="text-btn" type="button" onClick={() => setConfirming(false)}>
                戻る
              </button>
            </div>
          </div>
        ) : (
          <div className="page-acts task-acts">
            <button className="primary" type="button" onClick={() => setConfirming(true)}>
              これで出す
            </button>
          </div>
        ))}
    </section>
  )
}

/**
 * 前の調査の形の課題の帯。ペルソナと課題の文、［答える］で答えの欄を開く。
 * 答えは候補（＋で入れた科目）から選び、課題によって文も書く。送ると task_submit を記録して調査の入口へ戻る。
 */
function PickTaskBand({ taskId, task, block, taskIndex, count, gatePath }: BandProps<PickTaskDef | undefined>) {
  const { dept, shortlist } = useNavi()
  const { loadCourse, peekCourse } = useNaviData()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [text, setText] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [, setNamesLoaded] = useState(0)
  const formId = useId()

  // 学科の系統図に無い候補（検索・AI の結果から入れた科目）の名前は、科目の入れ物（D5 の詳細）から引く。
  // まだ取っていなければ取る。取れなければ科目コードのまま出す
  useEffect(() => {
    const missing = shortlist.filter((code) => findCourse(dept, code) === undefined && peekCourse(code) === undefined)
    if (missing.length === 0) return
    const control = new AbortController()
    void Promise.allSettled(missing.map((code) => loadCourse(code, control.signal))).then((results) => {
      if (control.signal.aborted) return
      results.forEach((r, i) => {
        if (r.status === 'rejected' && !isAbortError(r.reason)) console.error(`候補の科目名を取れませんでした（${missing[i]}）`, r.reason)
      })
      setNamesLoaded((n) => n + 1)
    })
    return () => control.abort()
  }, [dept, shortlist, loadCourse, peekCourse])

  const picks = task?.picks ?? 0
  const textAnswer = task?.text ?? null
  const chosen = selected.filter((code) => shortlist.includes(code))

  const nameOf = (code: string) => findCourse(dept, code)?.name ?? mappedCourseName(peekCourse(code)) ?? code

  const toggle = (code: string) => {
    setProblem(null)
    if (picks === 1) {
      setSelected([code])
      return
    }
    setSelected((cur) => (cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code]))
  }

  const send = (gaveUp: boolean) => {
    if (!gaveUp && chosen.length !== picks) {
      setProblem(`候補から${picks}つ選んでください。`)
      return
    }
    if (!gaveUp && textAnswer !== null && text.trim() === '') {
      setProblem(`${textAnswer.label}を書いてください。`)
      return
    }
    submitTask({
      selected: chosen,
      texts: { ...(textAnswer === null ? {} : { [textAnswer.id]: text.trim() }), ...(gaveUp ? { gave_up: 'true' } : {}) },
    })
    navigate(gatePath)
  }

  return (
    <section className="task-band" aria-label="課題">
      <div className="task-head">
        <p className="task-label">
          {blockLabel(block)}{WIDE_SPACE}課題{taskIndex + 1}/{count}
        </p>
        <button className="band-btn" type="button" aria-expanded={open} aria-controls={formId} onClick={() => setOpen((o) => !o)}>
          {open ? '答えを閉じる' : '答える'}
        </button>
      </div>
      <TaskBrief taskId={taskId} task={task} />
      <div id={formId} hidden={!open} className="task-answer">
        {picks > 0 && (
          <fieldset className="q-item">
            <legend className="q-legend">候補から{picks}つ選ぶ</legend>
            {shortlist.length === 0 ? (
              <p className="text">まだ候補がありません。科目の＋で候補に入れてください。</p>
            ) : (
              <ul className="pick-list">
                {shortlist.map((code) => (
                  <li key={code}>
                    <label>
                      <input
                        type={picks === 1 ? 'radio' : 'checkbox'}
                        name={`${formId}-pick`}
                        checked={chosen.includes(code)}
                        onChange={() => toggle(code)}
                      />
                      <span>{nameOf(code)}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </fieldset>
        )}
        {textAnswer !== null && (
          <label className="q-text">
            <span className="q-legend">{textAnswer.label}</span>
            <textarea
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                setProblem(null)
              }}
            />
          </label>
        )}
        {problem !== null && (
          <p className="msg-line q-problem" role="alert">
            <span className="ic-wrap">
              <Icon name="warn" small />
            </span>
            <span>{problem}</span>
          </p>
        )}
        <div className="page-acts">
          <button className="primary" type="button" onClick={() => send(false)}>
            答えを送る
          </button>
          <button className="text-btn" type="button" onClick={() => send(true)}>
            見つからないまま送る
          </button>
        </div>
      </div>
    </section>
  )
}
