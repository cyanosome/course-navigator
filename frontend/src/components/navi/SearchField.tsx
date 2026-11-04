import { useId, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { findOutOfScopeWords } from '../../navi/ask'
import { useNavi } from '../../navi/state'
import Icon from './Icon'

interface SearchFieldProps {
  /** スマホは上の帯の下に開く欄、PC は上の帯の中の欄（E1 4章・7章） */
  variant: 'sheet' | 'pc'
  /** 送れたとき（端末内の番号） */
  onSent: (localId: string) => void
}

const NOTE =
  'AIが探して答えます（1分ほど）。入力した文は外部のAIサービスに送られます。名前や学籍番号は書かないでください。'

type Problem = 'outOfScope' | 'busy' | 'empty' | null

/**
 * 自分の言葉で探す（W5-1）と、範囲外の言葉の案内（W6-1、UX 仕様 C09〜C11）。
 * 外部の AI に送る注意は、欄に入力を始めた時点で欄のすぐ下に出し、送る前に必ず見える（E1 7章 C12）。
 * 日本語の変換を確定する Enter では送らない（requirements.md R1-12）。入力した文は消さない（C11）。
 */
export default function SearchField({ variant, onSent }: SearchFieldProps) {
  const { askDraft, setAskDraft, sendAsk } = useNavi()
  const [problem, setProblem] = useState<Problem>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const noteId = useId()
  const pc = variant === 'pc'

  const submit = (withGuardrail: boolean) => {
    const text = askDraft.trim()
    if (text === '') {
      setProblem('empty')
      inputRef.current?.focus()
      return
    }
    if (!withGuardrail && findOutOfScopeWords(text).length > 0) {
      setProblem('outOfScope')
      return
    }
    const localId = sendAsk(text, withGuardrail)
    if (localId === null) {
      setProblem('busy')
      return
    }
    setProblem(null)
    inputRef.current?.blur()
    onSent(localId)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // 変換中の Enter（isComposing、古い実装では keyCode 229）は送信にしない
    if (e.key === 'Enter' && (e.nativeEvent.isComposing || e.keyCode === 229)) e.preventDefault()
  }

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    submit(false)
  }

  const message = problem !== null && (
    <div className="msg" role="status">
      {problem === 'outOfScope' && (
        <>
          <p className="msg-line">
            <span className="ic-wrap">
              <Icon name="warn" small />
            </span>
            <span>難しさや単位の取りやすさのデータは持っていません。その部分には答えられません。</span>
          </p>
          <div className="msg-acts">
            <button className="text-btn" type="button" onClick={() => submit(true)}>
              ほかの部分で探す
            </button>
            <button
              className="text-btn"
              type="button"
              onClick={() => {
                setProblem(null)
                inputRef.current?.focus()
              }}
            >
              言葉を変える
            </button>
          </div>
        </>
      )}
      {problem === 'busy' && <p className="msg-line">前の質問の回答を待っています。</p>}
      {problem === 'empty' && <p className="msg-line">探したいことを書いてから送ってください。</p>}
    </div>
  )

  return (
    <form className={pc ? 'pc-search' : undefined} onSubmit={onSubmit} role="search">
      <label className={problem === 'outOfScope' ? 'field is-error' : 'field'}>
        <Icon name="search" />
        <span className="vh">科目名や、興味のあること</span>
        <input
          ref={inputRef}
          type="text"
          value={askDraft}
          placeholder={pc ? '科目名や、興味のあることで探す' : '科目名や、興味のあること'}
          autoComplete="off"
          enterKeyHint="search"
          autoFocus={!pc}
          aria-describedby={noteId}
          aria-invalid={problem === 'outOfScope'}
          onChange={(e) => {
            setAskDraft(e.target.value)
            if (problem !== null) setProblem(null)
          }}
          onKeyDown={onKeyDown}
        />
      </label>
      <div className={pc ? `pop${problem !== null ? ' is-shown' : ''}` : undefined}>
        <p className="sheet-note" id={noteId}>
          {NOTE}
        </p>
        {message}
      </div>
    </form>
  )
}
