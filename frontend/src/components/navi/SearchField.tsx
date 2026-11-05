import { useId, useRef, useState } from 'react'
import type { FocusEvent, FormEvent, KeyboardEvent, MouseEvent } from 'react'
import { composeQuestion, findOutOfScopeWords } from '../../navi/ask'
import { useResearchLog } from '../../navi/research'
import { useNavi } from '../../navi/state'
import { useFlags } from '../../navi/variant'
import Icon from './Icon'

interface SearchFieldProps {
  /** 注意と［探す］を出しているか（欄にカーソルがあるか、送っていない文が入っているあいだ） */
  open: boolean
  /** 欄（［探す］や案内のボタンを含む）にカーソルが入った・外へ出た */
  onFocusChange: (focused: boolean) => void
  /** キーワードで探した（空なら検索をやめる） */
  onSearch: (query: string) => void
  /** AI に送れたとき（端末内の番号） */
  onSent: (localId: string) => void
}

/** AI だけの欄（search=off）の注意 */
const AI_ONLY_NOTE =
  'AIが探して答えます（1分ほど）。入力した文は外部のAIサービスに送られます。名前や学籍番号は書かないでください。'
/** キーワード検索の欄に［AIに聞く］を足したとき（assistant=on）の注意 */
const AI_NOTE = '［AIに聞く］を押すと、入力した文が外部のAIサービスに送られます（答えまで1分ほど）。名前や学籍番号は書かないでください。'

const KEYWORD_PLACEHOLDER = '例：有機化学、環境'
const AI_PLACEHOLDER = '例：環境に関わる仕事がしたい'

type Problem = 'outOfScope' | 'busy' | 'empty' | null

/**
 * さがすの一覧のいちばん上の欄（入口の案 a）。旗で中身が変わる（ab-variants.md F01・F04）。
 * - search=kw: キーワード検索。Enter と［探す］で科目名・概要・到達目標を探す。assistant=on のときだけ、
 *   同じ文を AI に送る［AIに聞く］と外部に送る注意を足す（ほかの配置・文言は AI の有無で変えない。計画 4.1）。
 * - search=off: 今までのモックの形（Enter と［探す］で AI に送る。W5-1）。
 * 注意と［探す］は欄にカーソルが入った時点で欄のすぐ下に出す。［AIに聞く］は注意と一緒にしか出ないので、
 * 外部に送る前に注意は必ず見える（E1 7章 C12）。日本語の変換を確定する Enter では送らない（requirements.md R1-12）。
 * 入力した文は消さない（C11）。
 */
export default function SearchField({ open, onFocusChange, onSearch, onSent }: SearchFieldProps) {
  const { dept, askDraft, setAskDraft, askDraftUnsent, sendAsk } = useNavi()
  const flags = useFlags()
  const { log } = useResearchLog()
  const [problem, setProblem] = useState<Problem>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const noteId = useId()
  const keyword = flags.search !== 'off'
  const ai = flags.assistant === 'on'
  const note = !ai ? null : keyword ? AI_NOTE : AI_ONLY_NOTE

  const close = () => {
    setProblem(null)
    inputRef.current?.blur()
    onFocusChange(false)
  }

  const sendToAi = (withGuardrail: boolean) => {
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
    log('chat_send', { input: text, question: composeQuestion(dept, text, withGuardrail), guardrail: withGuardrail, ask_local_id: localId })
    close()
    onSent(localId)
  }

  const searchKeyword = () => {
    close()
    onSearch(askDraft.trim())
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // 変換中の Enter（isComposing、古い実装では keyCode 229）は送信にしない
    if (e.key === 'Enter' && (e.nativeEvent.isComposing || e.keyCode === 229)) e.preventDefault()
  }

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (keyword) searchKeyword()
    else sendToAi(false)
  }

  // 欄の中（［探す］や案内のボタン）へ移ったときは畳まない。外へ出たとき、送っていない文があれば畳まない（案内も残す）
  const onBlur = (e: FocusEvent<HTMLFormElement>) => {
    const next = e.relatedTarget
    if (next instanceof Node && e.currentTarget.contains(next)) return
    onFocusChange(false)
    if (!askDraftUnsent) setProblem(null)
  }

  // ボタンを押してもカーソルを欄に残す（押した瞬間に欄が空として畳まれ、押せなくなるのを防ぐ）
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
            <button className="text-btn" type="button" onClick={() => sendToAi(true)}>
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
        <span className="vh">{keyword ? '科目を探す（科目名や、授業で扱う言葉）' : '自分の言葉で探す（興味のあることや科目名）'}</span>
        <input
          ref={inputRef}
          type="text"
          value={askDraft}
          placeholder={keyword ? KEYWORD_PLACEHOLDER : AI_PLACEHOLDER}
          autoComplete="off"
          enterKeyHint="search"
          aria-describedby={note === null ? undefined : noteId}
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
        {note !== null && (
          <p className="sheet-note" id={noteId}>
            {note}
          </p>
        )}
        <div className="send-row">
          <button className="send" type="submit" onMouseDown={keepFocus}>
            探す
          </button>
          {keyword && ai && (
            <button className="send" type="button" onMouseDown={keepFocus} onClick={() => sendToAi(false)}>
              AIに聞く
            </button>
          )}
        </div>
        {message}
      </div>
    </form>
  )
}
