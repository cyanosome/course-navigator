import { useId, useState } from 'react'
import '../../navi/study.css'
import { CONSENT, DRAFT_MARK } from '../../navi/studyConfig'
import { isFormSerial } from '../../navi/studyFlow'
import Icon from './Icon'

interface ConsentScreenProps {
  busy: boolean
  onAnswer: (agreed: boolean, formSerial: string) => void
}

/**
 * 同意（計画 4.2、Ibuki の PDF の②）。文は studyConfig.ts の CONSENT で、その版（consent_version）を R3 で残す。
 * 同意しないときも記録だけして、先へは進めない。同意書の番号（紙の同意書の通し番号）は、どちらのときも要る。
 */
export default function ConsentScreen({ busy, onAnswer }: ConsentScreenProps) {
  const serialId = useId()
  const [serial, setSerial] = useState('')
  const [serialProblem, setSerialProblem] = useState(false)
  const answer = (agreed: boolean) => {
    if (!isFormSerial(serial)) {
      setSerialProblem(true)
      return
    }
    onAnswer(agreed, serial)
  }
  return (
    <>
      <h1 className="title">
        {CONSENT.title}
        {CONSENT.draft && <span className="draft">{DRAFT_MARK}</span>}
      </h1>
      {CONSENT.sections.map((s) => (
        <section key={s.heading} className="sec">
          <h2 className="sec-label">{s.heading}</h2>
          <p className="text">{s.body}</p>
        </section>
      ))}
      <section className="sec">
        <label className="q-field" htmlFor={serialId}>
          {CONSENT.formSerialLabel}
        </label>
        <input
          id={serialId}
          className="q-input"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          aria-invalid={serialProblem}
          value={serial}
          onChange={(e) => {
            setSerial(e.target.value)
            setSerialProblem(false)
          }}
        />
        {serialProblem && (
          <p className="msg-line q-problem" role="alert">
            <span className="ic-wrap">
              <Icon name="warn" small />
            </span>
            <span>同意書の番号を、英数字で書いてください（16文字まで）。</span>
          </p>
        )}
      </section>
      <div className="page-acts">
        <button className="primary" type="button" disabled={busy} onClick={() => answer(true)}>
          同意して始める
        </button>
        <button className="text-btn" type="button" disabled={busy} onClick={() => answer(false)}>
          同意しない
        </button>
      </div>
      <p className="src">同意文の版 {CONSENT.version}</p>
    </>
  )
}
