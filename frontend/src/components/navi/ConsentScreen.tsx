import '../../navi/study.css'
import { CONSENT, DRAFT_MARK } from '../../navi/studyConfig'

interface ConsentScreenProps {
  busy: boolean
  onAnswer: (agreed: boolean) => void
}

/**
 * 同意（計画 4.2、Ibuki の PDF の②）。文は studyConfig.ts の CONSENT で、その版（consent_version）を R3 で残す。
 * 同意しないときも記録だけして、先へは進めない。リンクで配るので同意は画面だけで取り、番号の欄は無い
 * （記録の form_serial は studyFlow.ts が固定の値 ONLINE_FORM_SERIAL を送る）。
 */
export default function ConsentScreen({ busy, onAnswer }: ConsentScreenProps) {
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
        <p className="text">{CONSENT.agreeNote}</p>
      </section>
      <div className="page-acts">
        <button className="primary" type="button" disabled={busy} onClick={() => onAnswer(true)}>
          同意して始める
        </button>
        <button className="text-btn" type="button" disabled={busy} onClick={() => onAnswer(false)}>
          同意しない
        </button>
      </div>
      <p className="src">同意文の版 {CONSENT.version}</p>
    </>
  )
}
