import { useId, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { findOutOfScopeWords } from '../../navi/ask'
import { FIXTURE_SYLLABUS_BASE } from '../../navi/fixtureDepartment'
import { prevFrames } from '../../navi/graph'
import { groupHref, useNavi } from '../../navi/state'
import type { Course } from '../../navi/types'
import Glyph from './Glyph'

interface AskFormProps {
  variant: 'mobile' | 'pc'
  /** 送れたとき（端末内の番号） */
  onSent: (localId: string) => void
  /** [閉じる]・[方向から探す]（スマホは入力欄を閉じる） */
  onClose?: () => void
  /** [方向から探す] で方向のチップへ移る */
  onDirections: () => void
  /** 科目が決まっているとき（PC の右ペインの科目）。W6-1 の科目ごとの案内に使う */
  course?: Course
}

const PLACEHOLDER = '例: 環境問題に関わる仕事に興味がある'
const NOTE_PRIVATE = '名前や学籍番号は書かないでください。'
const NOTE_EXTERNAL = '入力した文は、回答を作るために外部のAIサービスに送られます。'

/**
 * 自由記述の入力（W5-1。PC は左ペインの上に常に出す。UX 仕様 5.3、C12）と、範囲外の言葉の案内（W6-1、C09〜C11）。
 * 日本語の変換を確定する Enter では送らない（requirements.md R1-12）。入力した文は消さない（C11）。
 */
export default function AskForm({ variant, onSent, onClose, onDirections, course }: AskFormProps) {
  const { dept, askDraft, setAskDraft, sendAsk } = useNavi()
  const [outOfScope, setOutOfScope] = useState(false)
  const [busy, setBusy] = useState(false)
  const [empty, setEmpty] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const inputId = useId()
  const noteId = useId()

  const submit = (withGuardrail: boolean) => {
    const text = askDraft.trim()
    if (text === '') {
      setEmpty(true)
      inputRef.current?.focus()
      return
    }
    setEmpty(false)
    if (!withGuardrail && findOutOfScopeWords(text).length > 0) {
      setOutOfScope(true)
      return
    }
    const localId = sendAsk(text, withGuardrail)
    if (localId === null) {
      setBusy(true)
      return
    }
    setBusy(false)
    setOutOfScope(false)
    onSent(localId)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // 変換中の Enter（isComposing、古い実装では keyCode 229）は送信にしない
    if (e.key === 'Enter' && (e.nativeEvent.isComposing || e.keyCode === 229)) e.preventDefault()
  }

  const rephrase = () => {
    setOutOfScope(false)
    inputRef.current?.focus()
  }

  const firstPrev = course === undefined ? undefined : prevFrames(dept, course.frameId)[0]

  const input = (
    <input
      ref={inputRef}
      className={outOfScope ? 'input input--error' : 'input'}
      id={inputId}
      type="text"
      value={askDraft}
      placeholder={PLACEHOLDER}
      autoComplete="off"
      autoFocus={variant === 'mobile'}
      aria-describedby={noteId}
      aria-invalid={outOfScope}
      onChange={(e) => {
        setAskDraft(e.target.value)
        if (outOfScope) setOutOfScope(false)
      }}
      onKeyDown={onKeyDown}
    />
  )

  const notice = outOfScope && (
    <div className="msg">
      <p className="msg__lead" role="status">
        <Glyph name="warn" />
        <span>
          <b>データがありません:</b> 難しさや単位の取りやすさのデータは持っていません。その部分には答えられません。
        </span>
      </p>
      <div className="msg__acts">
        <button className="btn btn--ink btn--wide" type="button" onClick={() => submit(true)}>
          このまま送る（ほかの部分で探す）
        </button>
        <button className="btn btn--wide" type="button" onClick={rephrase}>
          言葉を変える
        </button>
      </div>
      <p className="note">代わりに次のこともできます。</p>
      <div className="msg__acts">
        {course !== undefined && (
          <a className="btn btn--wide" href={`${FIXTURE_SYLLABUS_BASE}${course.code}`} target="_blank" rel="noopener noreferrer">
            シラバス原文で成績評価の方法を見る
            <Glyph name="external" />
          </a>
        )}
        {course !== undefined && firstPrev !== undefined && (
          <Link className="btn btn--wide" to={groupHref(firstPrev.id, { kind: 'course', code: course.code })}>
            先に取っておく枠を見る
          </Link>
        )}
        <button
          className="btn btn--wide"
          type="button"
          onClick={() => {
            setOutOfScope(false)
            onDirections()
          }}
        >
          方向から探す
        </button>
      </div>
    </div>
  )

  const status = (
    <>
      {busy && (
        <p className="note note--ink note--busy" role="status">
          前の質問の回答を待っています
        </p>
      )}
      {empty && (
        <p className="note note--ink note--busy" role="status">
          探したいことを書いてから[探す]を押してください。
        </p>
      )}
    </>
  )

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    submit(false)
  }

  if (variant === 'pc') {
    return (
      <form className="field" onSubmit={onSubmit}>
        <label className="label" htmlFor={inputId}>
          自分の言葉で探す
        </label>
        <div className="field__row">
          {input}
          <button className="btn btn--ink" type="submit">
            探す
          </button>
        </div>
        <p className="note" id={noteId}>
          {NOTE_PRIVATE}
          {NOTE_EXTERNAL}
        </p>
        {notice}
        {status}
      </form>
    )
  }

  return (
    <section className="ask-panel" aria-label="自分の言葉で探す">
      <form onSubmit={onSubmit}>
        <div className="field">
          <label className="h-sec" htmlFor={inputId}>
            自分の言葉で探す
          </label>
          {input}
          <p className="note" id={noteId}>
            {NOTE_PRIVATE}
            <br />
            {NOTE_EXTERNAL}
          </p>
        </div>
        {notice}
        {status}
        {!outOfScope && (
          <div className="ask-panel__acts">
            <button className="btn btn--ink" type="submit">
              探す
            </button>
            <button className="btn" type="button" onClick={onClose}>
              閉じる
            </button>
          </div>
        )}
      </form>
    </section>
  )
}
