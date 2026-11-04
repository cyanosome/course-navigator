import { useId, useRef, useState } from 'react'
import type { FocusEvent, FormEvent, KeyboardEvent, MouseEvent } from 'react'
import { findOutOfScopeWords } from '../../navi/ask'
import { useNavi } from '../../navi/state'
import Icon from './Icon'

interface SearchFieldProps {
  /** 注意と［探す］を出しているか（欄にカーソルがあるか、送っていない文が入っているあいだ） */
  open: boolean
  /** 欄（［探す］や案内のボタンを含む）にカーソルが入った・外へ出た */
  onFocusChange: (focused: boolean) => void
  /** 送れたとき（端末内の番号） */
  onSent: (localId: string) => void
}

const NOTE =
  'AIが探して答えます（1分ほど）。入力した文は外部のAIサービスに送られます。名前や学籍番号は書かないでください。'

const PLACEHOLDER = '例：環境に関わる仕事がしたい'

type Problem = 'outOfScope' | 'busy' | 'empty' | null

/**
 * 自分の言葉で探す（W5-1）と、範囲外の言葉の案内（W6-1、UX 仕様 C09〜C11）。さがすの一覧のいちばん上に、いつも出す（入口の案 a）。
 * 外部の AI に送る注意と［探す］は、欄にカーソルが入った時点で欄のすぐ下に出す。［探す］は注意と一緒にしか出ないので、
 * Enter で送るときも注意は送る前に必ず見える（E1 7章 C12）。送っていない文が無いまま欄の外へ出たら畳む。
 * 日本語の変換を確定する Enter では送らない（requirements.md R1-12）。入力した文は消さない（C11）。
 */
export default function SearchField({ open, onFocusChange, onSent }: SearchFieldProps) {
  const { askDraft, setAskDraft, askDraftUnsent, sendAsk } = useNavi()
  const [problem, setProblem] = useState<Problem>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const noteId = useId()

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
    onFocusChange(false)
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

  // 欄の中（［探す］や案内のボタン）へ移ったときは畳まない。外へ出たとき、送っていない文があれば畳まない（案内も残す）
  const onBlur = (e: FocusEvent<HTMLFormElement>) => {
    const next = e.relatedTarget
    if (next instanceof Node && e.currentTarget.contains(next)) return
    onFocusChange(false)
    if (!askDraftUnsent) setProblem(null)
  }

  // ［探す］を押してもカーソルを欄に残す（押した瞬間に欄が空として畳まれ、押せなくなるのを防ぐ）
  const keepFocus = (e: MouseEvent<HTMLButtonElement>) => e.preventDefault()

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
    <form className="ask-top" onSubmit={onSubmit} onFocus={() => onFocusChange(true)} onBlur={onBlur} role="search">
      <label className={problem === 'outOfScope' ? 'field is-error' : 'field'}>
        <Icon name="search" />
        <span className="vh">自分の言葉で探す（興味のあることや科目名）</span>
        <input
          ref={inputRef}
          type="text"
          value={askDraft}
          placeholder={PLACEHOLDER}
          autoComplete="off"
          enterKeyHint="search"
          aria-describedby={noteId}
          aria-invalid={problem === 'outOfScope'}
          onChange={(e) => {
            setAskDraft(e.target.value)
            if (problem !== null) setProblem(null)
          }}
          onKeyDown={onKeyDown}
        />
      </label>
      {/* 畳んでいるあいだも注意は読み上げの説明として残す（hidden でも aria-describedby からは読める） */}
      <div hidden={!open}>
        <p className="sheet-note" id={noteId}>
          {NOTE}
        </p>
        <div className="send-row">
          <button className="send" type="submit" onMouseDown={keepFocus}>
            探す
          </button>
        </div>
        {message}
      </div>
    </form>
  )
}
