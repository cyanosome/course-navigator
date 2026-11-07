import { useId, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import '../../navi/study.css'
import { DRAFT_MARK } from '../../navi/studyConfig'
import type { Questionnaire, QuestionItem } from '../../navi/studyConfig'
import type { QuestionnaireAnswers } from '../../navi/studyFlow'
import Icon from './Icon'

interface QuestionnaireFormProps {
  questionnaires: readonly Questionnaire[]
  submitLabel: string
  busy: boolean
  onSubmit: (answers: QuestionnaireAnswers) => void
}

type Value = number | string | null

/** UEQ-S の組の値（左の語に近い −3 から右の語に近い +3） */
const PAIR_VALUES = [-3, -2, -1, 0, 1, 2, 3] as const

function key(q: Questionnaire, item: QuestionItem): string {
  return `${q.id}.${item.id}`
}

function isAnswered(value: Value | undefined): boolean {
  return value !== undefined && value !== null && value !== ''
}

/**
 * 質問票（studyConfig.ts の尺度を並べる）。答えていない必須の問いがあれば送らず、件数と印を出して最初の問いへ移る。
 * 〈仮〉の文には印を付ける。
 */
export default function QuestionnaireForm({ questionnaires, submitLabel, busy, onSubmit }: QuestionnaireFormProps) {
  const formId = useId()
  const [values, setValues] = useState<Record<string, Value>>({})
  const [missing, setMissing] = useState<string[]>([])
  const formRef = useRef<HTMLFormElement>(null)

  const set = (k: string, v: Value) => {
    setValues((cur) => ({ ...cur, [k]: v }))
    setMissing((cur) => cur.filter((m) => m !== k))
  }

  const submit = () => {
    const lacking = questionnaires.flatMap((q) => q.items.filter((it) => it.required && !isAnswered(values[key(q, it)])).map((it) => key(q, it)))
    if (lacking.length > 0) {
      setMissing(lacking)
      formRef.current?.querySelector<HTMLElement>(`[data-q="${lacking[0]}"]`)?.focus()
      return
    }
    const answers: QuestionnaireAnswers = {}
    for (const q of questionnaires) {
      answers[q.id] = Object.fromEntries(
        q.items.map((it) => {
          const v = values[key(q, it)]
          return [it.id, typeof v === 'string' ? v.trim() || null : (v ?? null)]
        }),
      )
    }
    onSubmit(answers)
  }

  const item = (q: Questionnaire, it: QuestionItem) => {
    const k = key(q, it)
    const name = `${formId}-${k}`
    const lacking = missing.includes(k)
    const mark = it.draft && <span className="draft">{DRAFT_MARK}</span>
    const note = lacking && <span className="q-missing">答えていません</span>
    if (it.kind === 'text') {
      return (
        <label key={k} className="q-text q-item" data-q={k} tabIndex={-1}>
          <span className="q-legend">
            {it.text}
            {mark}
          </span>
          <textarea value={typeof values[k] === 'string' ? values[k] : ''} onChange={(e) => set(k, e.target.value)} />
          {note}
        </label>
      )
    }
    if (it.kind === 'choice') {
      return (
        <fieldset key={k} className="q-item" data-q={k} tabIndex={-1} aria-invalid={lacking}>
          <legend className="q-legend">
            {it.text}
            {mark}
          </legend>
          {note}
          <ul className="pick-list">
            {it.options.map((o) => (
              <li key={o.value}>
                <label>
                  <input type="radio" name={name} checked={values[k] === o.value} onChange={() => set(k, o.value)} />
                  <span>{o.label}</span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )
    }
    if (it.kind === 'pair') {
      return (
        <fieldset key={k} className="q-item" data-q={k} tabIndex={-1} aria-invalid={lacking}>
          <legend className="q-legend">
            {it.left}／{it.right}
            {mark}
          </legend>
          {note}
          <div className="q-scale" style={{ '--n': PAIR_VALUES.length } as CSSProperties}>
            {PAIR_VALUES.map((v) => (
              <label key={v} className="q-opt">
                <input type="radio" name={name} checked={values[k] === v} onChange={() => set(k, v)} />
                <span className="vh">{v < 0 ? `${it.left}に近い ${-v}` : v > 0 ? `${it.right}に近い ${v}` : 'どちらでもない'}</span>
              </label>
            ))}
          </div>
          <div className="q-ends" aria-hidden="true">
            <span>{it.left}</span>
            <span>{it.right}</span>
          </div>
        </fieldset>
      )
    }
    const points = Array.from({ length: it.points }, (_, i) => i + 1)
    return (
      <fieldset key={k} className="q-item" data-q={k} tabIndex={-1} aria-invalid={lacking}>
        <legend className="q-legend">
          {it.text}
          {mark}
        </legend>
        {note}
        <div className="q-scale" style={{ '--n': it.points } as CSSProperties}>
          {points.map((v) => (
            <label key={v} className="q-opt">
              <input type="radio" name={name} checked={values[k] === v} onChange={() => set(k, v)} />
              <span>{v}</span>
            </label>
          ))}
        </div>
        <div className="q-ends">
          <span>1 {it.low}</span>
          <span>
            {it.points} {it.high}
          </span>
        </div>
      </fieldset>
    )
  }

  return (
    <form
      ref={formRef}
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      {questionnaires.map((q) => (
        <section key={q.id} className="q-sec" aria-label={q.scale}>
          {q.intro !== null && <p className="text">{q.intro}</p>}
          {q.items.map((it) => item(q, it))}
        </section>
      ))}
      {missing.length > 0 && (
        <p className="msg-line q-problem" role="alert">
          <span className="ic-wrap">
            <Icon name="warn" small />
          </span>
          <span>答えていない問いが{missing.length}つあります。</span>
        </p>
      )}
      <div className="page-acts">
        <button className="primary" type="submit" disabled={busy}>
          {submitLabel}
        </button>
      </div>
    </form>
  )
}
