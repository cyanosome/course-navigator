import { useEffect, useId, useState } from 'react'
import type { EventPayload } from '../../navi/apiTypes'
import { extractReasons } from '../../navi/ask'
import { findCourse } from '../../navi/graph'
import { formatClock, useElapsedSeconds } from '../../navi/hooks'
import { useResearchLog } from '../../navi/research'
import { useNavi } from '../../navi/state'
import type { AskSession, Origin } from '../../navi/state'
import { useFlags } from '../../navi/variant'
import { AI_WHY_FALLBACK, rootEntry, rowView, sourceRowView } from '../../navi/views'
import CourseRow from './CourseRow'
import Icon from './Icon'

interface AskResultsProps {
  session: AskSession
  /** PC の中央に出している科目 */
  currentCode?: string
}

/**
 * 自分の言葉で探した結果（W5-2 待ち・W5-3 結果・W6-2〜W6-4 失敗）。一覧の先頭に出す。
 * 行は一覧と同じ形で、なぜは AI の説明から取り、「（AIの判断）」を灰の文字で添える（E1 7章）。
 * 骨組みの読み込み表示は入れていない（E1 10章の「実装のときに入れる予定」のうち、今回入れなかったもの）。
 * 旗 assistant=on のときだけ出す（呼ぶ側の SearchList）。行は AI の出典カードで、押すと result_click と citation_click を記録する。
 */
export default function AskResults({ session, currentCode }: AskResultsProps) {
  const { dept, shortlist, placement, focusTerm, assumedTerm, cancelAsk, closeAsk, markAskSeen, sendAsk } = useNavi()
  const flags = useFlags()
  const { log } = useResearchLog()
  const waiting = session.status === 'waiting'
  const seconds = useElapsedSeconds(session.startedAt, waiting)
  const [fullOpen, setFullOpen] = useState(false)
  const fullId = useId()

  // 一覧の中で結果を見たら、ほかの画面の「回答が届きました」を消す（UX 仕様 C08）
  useEffect(() => {
    if (!waiting) markAskSeen()
  }, [waiting, markAskSeen])

  const label = `「${session.interest}」から`
  /** どの回答の出典カードか（A1 の応答の request_id。本物の口に替わるまでは無い） */
  const answerRef = (): EventPayload => {
    const result = session.result
    const requestId = result !== null && 'request_id' in result ? result.request_id : null
    return { ask_local_id: session.localId, request_id: typeof requestId === 'string' ? requestId : null }
  }
  // chat_send（retry: true）は sendAsk が記録する
  const resend = () => {
    sendAsk(session.interest, session.guardrail, { retry: true })
  }

  if (waiting) {
    return (
      <section className="ask" aria-label="自分の言葉で探した結果（作っています）">
        <div className="ask-wait">
          <p role="status">{label}探しています。ふだん30秒〜1分半ほどかかります。</p>
          <div className="ask-wait-row">
            <span className="clock">
              経過 <span aria-hidden="true">{formatClock(seconds)}</span>
            </span>
            <button className="text-btn" type="button" onClick={cancelAsk}>
              やめる
            </button>
          </div>
        </div>
      </section>
    )
  }

  if (session.status === 'error' || session.status === 'timeout' || session.status === 'empty') {
    // 系統図を出さない変種（graph=off）には興味関心が無いので、その案内を言わない
    const graph = flags.graph === 'on'
    const text =
      session.status === 'timeout'
        ? '3分たっても回答が届かないため、待つのをやめました。'
        : session.status === 'error'
          ? `回答を作れませんでした（サーバーにつながりません）。${graph ? '興味関心からの一覧' : '下の一覧'}と時間割は、このまま使えます。`
          : `この言葉に合う科目は見つかりませんでした。${graph ? '上の興味関心から選ぶこともできます。' : ''}`
    return (
      <section className="ask" aria-label="自分の言葉で探した結果">
        <div className="msg">
          <p className="msg-line" role="status">
            <span className="ic-wrap">
              <Icon name="warn" small />
            </span>
            <span>{text}</span>
          </p>
        </div>
        <div className="ask-acts">
          {session.status !== 'empty' && (
            <button className="text-btn" type="button" onClick={resend}>
              もう一度送る
            </button>
          )}
          <button className="text-btn" type="button" onClick={closeAsk}>
            閉じる
          </button>
        </div>
      </section>
    )
  }

  const result = session.result
  if (result === null) return null
  const origin: Origin = { kind: 'ask', localId: session.localId }
  const root = rootEntry(dept, origin)
  const reasons = extractReasons(result.answer)
  const ctx = { dept, shortlist, focusTerm, assumedTerm, placement }
  const rows = result.sources.map((s) => {
    const why = reasons.get(s.code) ?? AI_WHY_FALLBACK
    const course = findCourse(dept, s.code)
    return course === undefined ? sourceRowView(s, origin, why) : rowView(ctx, course, origin, why, 'AIの判断')
  })
  const unverified = result.unverified_codes.length
  const paragraphs = result.answer.split(/\n{2,}/).filter((p) => p.trim() !== '')

  return (
    <section className="ask" aria-label="自分の言葉で探した結果">
      <h2 className="group-label">{label}</h2>
      <ul className="list">
        {rows.map((r, i) => (
          <CourseRow
            key={r.code}
            row={r}
            current={r.code === currentCode}
            linkState={{ trail: [root, { label: r.name, href: r.href }], tab: 'search' }}
            onOpen={() => {
              log('result_click', { syllabus_id: r.code, rank: i + 1, list: 'ask' })
              log('citation_click', { syllabus_id: r.code, rank: i + 1, ...answerRef() })
            }}
          />
        ))}
      </ul>
      <div className={fullOpen ? 'more is-open' : 'more'}>
        <button
          className="more-btn"
          type="button"
          aria-expanded={fullOpen}
          aria-controls={fullId}
          onClick={() => {
            if (!fullOpen) log('ai_full_open', answerRef())
            setFullOpen((o) => !o)
          }}
        >
          <span>{fullOpen ? 'AIの説明を閉じる' : 'AIの説明を全部読む'}</span>
          <Icon name="down" />
        </button>
        <div className="acc-body" id={fullId}>
          {fullOpen && (
            <div className="ask-full">
              {paragraphs.map((p, i) => (
                <p key={i}>{p}</p>
              ))}
              {result.notes.length > 0 && <p className="src">{result.notes.join(' ')}</p>}
              <p className="src">AIの説明は間違うことがあります。シラバスの原文で確かめてください。</p>
            </div>
          )}
        </div>
      </div>
      {unverified > 0 && <p className="foot">確かめられなかった科目名が{unverified}件あり、一覧に入れていません。</p>}
      <div className="ask-acts">
        <button className="text-btn" type="button" onClick={closeAsk}>
          この結果を閉じる
        </button>
      </div>
    </section>
  )
}
