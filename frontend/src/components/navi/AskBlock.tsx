import { useEffect, useId, useState } from 'react'
import { formatClock, useElapsedSeconds } from '../../navi/hooks'
import { useNavi } from '../../navi/state'
import type { AskSession } from '../../navi/state'
import { askViews } from '../../navi/views'
import DirectionChips from './DirectionChips'
import EvidenceLabel from './EvidenceLabel'
import Glyph from './Glyph'
import { ProposalCard, ProposalItem } from './ProposalCard'

interface AskBlockProps {
  session: AskSession
  variant: 'mobile' | 'pc'
  /** PC の右ペインに出している科目（一覧の印に使う） */
  currentCode?: string
  /** [言葉を変える]・[言葉を変えて探す] で入力欄へ */
  onRephrase: () => void
  /** [方向から探す] で方向のチップへ */
  onDirections: () => void
}

/** 結果のカード3件分の高さを、送った時点で一覧の先頭に確保する（UX 仕様 C07） */
const HOLD_SLOTS = 3

/**
 * 自由記述の待ち（W5-2）・結果（W5-3）・失敗（W6-2〜W6-4）。一覧の先頭に出す。
 * PC の待ちの経過と[やめる]は見出しの下の1行（WaitLine）に出すので、ここでは出さない。
 */
export default function AskBlock({ session, variant, currentCode, onRephrase, onDirections }: AskBlockProps) {
  const { dept, cancelAsk, closeAsk, markAskSeen, sendAsk } = useNavi()
  const waiting = session.status === 'waiting'
  const seconds = useElapsedSeconds(session.startedAt, waiting)
  const [fullOpen, setFullOpen] = useState(false)
  const headingId = useId()
  const fullId = useId()

  // 一覧の中で結果を見たら、ほかの画面の「回答が届きました」を消す（UX 仕様 C08）
  useEffect(() => {
    if (!waiting) markAskSeen()
  }, [waiting, markAskSeen])

  if (waiting) {
    return (
      <section className="ask-block" aria-label="あなたの言葉からの提案（作っています）">
        <div className="ask-wait">
          <p className="body-s" role="status">
            「{session.interest}」から探しています。ふだん30秒〜1分半ほどかかります。
          </p>
          {variant === 'mobile' && (
            <div className="ask-wait__row">
              <p className="body-s">
                経過{' '}
                <span className="ask-wait__time" aria-hidden="true">
                  {formatClock(seconds)}
                </span>
              </p>
              <button className="btn" type="button" onClick={cancelAsk}>
                やめる
              </button>
            </div>
          )}
          <p className="note note--ink">待つあいだも、下の提案や候補を見られます。</p>
        </div>
        <div className="ask-hold" aria-hidden="true">
          {Array.from({ length: HOLD_SLOTS }, (_, i) => (
            <div key={i} className="ask-hold__slot" />
          ))}
        </div>
      </section>
    )
  }

  if (session.status === 'error' || session.status === 'timeout') {
    const timeout = session.status === 'timeout'
    return (
      <section className="ask-block" aria-label="あなたの言葉からの提案">
        <div className="msg">
          <p className="msg__lead" role="status">
            <Glyph name="warn" />
            <span>
              {timeout
                ? '3分たっても回答が届かないため、待つのをやめました。'
                : '回答を作れませんでした（サーバーにつながりません）。方向からの提案と候補は、このまま使えます。'}
            </span>
          </p>
          <div className="msg__acts msg__acts--row">
            <button className="btn btn--ink" type="button" onClick={() => sendAsk(session.interest, session.guardrail)}>
              もう一度送る
            </button>
            {timeout ? (
              <button
                className="btn"
                type="button"
                onClick={() => {
                  closeAsk()
                  onDirections()
                }}
              >
                方向から探す
              </button>
            ) : (
              <button className="btn" type="button" onClick={closeAsk}>
                閉じる
              </button>
            )}
          </div>
        </div>
      </section>
    )
  }

  if (session.status === 'empty') {
    return (
      <section className="ask-block" aria-label="あなたの言葉からの提案">
        <div className="msg">
          <p className="msg__lead" role="status">
            <Glyph name="warn" />
            <span>この言葉に合う科目は見つかりませんでした。方向から選ぶこともできます。</span>
          </p>
          <div className="msg__acts">
            <DirectionChips selected="" withoutDefault labelled={false} />
            <button
              className="btn"
              type="button"
              onClick={() => {
                closeAsk()
                onRephrase()
              }}
            >
              言葉を変えて探す
            </button>
          </div>
        </div>
      </section>
    )
  }

  const views = askViews(dept, session, 'search')
  const result = session.result
  const unverified = result?.unverified_codes.length ?? 0
  const paragraphs = (result?.answer ?? '').split(/\n{2,}/).filter((p) => p.trim() !== '')

  return (
    <section className="ask-block ask-result" aria-labelledby={headingId}>
      <h2 className="h-sec" id={headingId}>
        あなたの言葉からの提案 {views.length}件（AIが作成）
      </h2>
      <p className="note">使った情報: 学科、あなたの文</p>
      {variant === 'mobile' ? (
        <ol className="cards">
          {views.map((v) => (
            <li key={v.code}>
              <ProposalCard item={v} />
            </li>
          ))}
        </ol>
      ) : (
        <ol className="items">
          {views.map((v) => (
            <ProposalItem key={v.code} item={v} current={v.code === currentCode} />
          ))}
        </ol>
      )}
      <div className="ask-result__after">
        <button
          className="btn btn--quiet"
          type="button"
          aria-expanded={fullOpen}
          aria-controls={fullId}
          onClick={() => setFullOpen((o) => !o)}
        >
          {fullOpen ? 'AIの説明を閉じる' : 'AIの説明を全部読む'}
        </button>
        {fullOpen && (
          <div className="ai-full" id={fullId}>
            {paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
            {result !== null && result.notes.length > 0 && (
              <p>
                <b>システムからの注意:</b> {result.notes.join(' ')}
              </p>
            )}
            <EvidenceLabel kind="ai" />
            <p className="note">間違うことがあります。シラバスの原文で確かめてください。</p>
          </div>
        )}
        {unverified > 0 && <p className="note">確認できなかった科目名が{unverified}件あります（提案には入れていません）</p>}
        <button className="btn btn--quiet" type="button" onClick={closeAsk}>
          この結果を閉じる
        </button>
      </div>
    </section>
  )
}
