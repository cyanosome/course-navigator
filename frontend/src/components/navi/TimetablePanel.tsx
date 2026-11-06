import { Link } from 'react-router-dom'
import { findCourse } from '../../navi/graph'
import { courseHref, listHref, TIMETABLE_HREF, useNavi } from '../../navi/state'
import {
  ALL_TERMS,
  courseTermLabel,
  gradProgress,
  inTerm,
  isOnGrid,
  isRequired,
  placedInTerm,
  slotMap,
  termCredits,
  termIndex,
  termLabel,
  totalPlacedCredits,
  unknownCreditCount,
} from '../../navi/timetable'
import type { Course } from '../../navi/types'
import Accordion from './Accordion'
import Icon from './Icon'
import TimetableGrid from './TimetableGrid'

/**
 * 時間割（W4。PC は W12 の左の段）。E1 4章・5章: 「＜ 1年春 ＞」と「13単位 上限 24」、凡例、表、重なりの知らせ、
 * 曜限なし、開閉2つ（卒業に要る単位・ほかの学期の候補）、注意書き。外したときは［元に戻す］を5秒出す（NaviApp）。
 */
export default function TimetablePanel() {
  const { dept, shortlist, focusTerm, setFocusTerm, removeKeep, isPc, lastDir } = useNavi()
  const index = termIndex(focusTerm)
  const prev = ALL_TERMS[index - 1]
  const next = ALL_TERMS[index + 1]
  const placed = placedInTerm(dept, shortlist, focusTerm)
  const clashes = [...slotMap(placed).entries()].filter(([, cs]) => cs.length > 1)
  const noSlot = placed.filter((c) => !isOnGrid(c))
  const picked = shortlist.map((code) => findCourse(dept, code)).filter((c): c is Course => c !== undefined && !isRequired(c))
  const pickedHere = picked.filter((c) => inTerm(c, focusTerm))
  const elsewhere = picked.filter((c) => !inTerm(c, focusTerm))
  const outside = shortlist.filter((code) => findCourse(dept, code) === undefined)
  const credits = termCredits(dept, shortlist, focusTerm)
  const unknown = unknownCreditCount(dept, shortlist, focusTerm)
  const req = dept.requirements
  const progress = gradProgress(dept, shortlist)
  const total = totalPlacedCredits(dept, shortlist)
  const Heading = isPc ? 'h2' : 'h1'

  const nameLink = (c: Course) => {
    const href = courseHref(c.code, { kind: 'tt' })
    return (
      <Link to={href} state={{ trail: [{ label: '時間割', href: TIMETABLE_HREF }, { label: c.name, href }], tab: 'tt' }}>
        {c.name}
      </Link>
    )
  }
  const removeButton = (c: Course) => (
    <button className="text-btn" type="button" onClick={() => removeKeep(c.code)} aria-label={`${c.name}を外す`}>
      外す
    </button>
  )

  return (
    <>
      <div className="term">
        <div className="term-nav">
          <button
            className="icon-btn"
            type="button"
            aria-label={prev === undefined ? '前の学期' : `前の学期（${termLabel(prev)}）`}
            disabled={prev === undefined}
            onClick={() => prev !== undefined && setFocusTerm(prev)}
          >
            <Icon name="back" />
          </button>
          <Heading className="term-label" aria-live="polite">
            {termLabel(focusTerm)}
          </Heading>
          <button
            className="icon-btn"
            type="button"
            aria-label={next === undefined ? '次の学期' : `次の学期（${termLabel(next)}）`}
            disabled={next === undefined}
            onClick={() => next !== undefined && setFocusTerm(next)}
          >
            <Icon name="next" />
          </button>
        </div>
        <p className="term-sum">
          <span>
            <span className="num">{credits}</span>単位
          </span>
          {req !== null && <span>上限 {req.termCap}</span>}
          {unknown > 0 && <span>単位の分からない科目 {unknown}</span>}
        </p>
      </div>
      <ul className="legend" aria-hidden="true">
        <li>
          <i className="sw req" />
          必修
        </li>
        <li>
          <i className="sw cand" />
          候補
        </li>
        {clashes.length > 0 && (
          <li>
            <i className="sw clash" />
            重なり
          </li>
        )}
      </ul>
      <TimetableGrid term={focusTerm} tab="tt" />

      {pickedHere.length === 0 && (
        <p className="tt-empty">
          この学期の候補はまだありません。<Link to={listHref(lastDir)}>さがす</Link>で＋を押すと、ここに入ります。
        </p>
      )}

      {clashes.map(([slot, cs]) => (
        <section key={slot} className="block" aria-labelledby={`clash-${slot}`}>
          <h2 className="block-h is-clash" id={`clash-${slot}`}>
            <Icon name="warn" small />
            {slot}が重なっています。片方を外してください
          </h2>
          <ul className="lines">
            {cs.map((c) => (
              <li key={c.code}>
                {nameLink(c)}
                <span className="meta">{isRequired(c) ? '必修' : creditsText(c)}</span>
                {isRequired(c) ? <span /> : removeButton(c)}
              </li>
            ))}
          </ul>
        </section>
      ))}

      {noSlot.length > 0 && (
        <section className="block" aria-labelledby="tt-noslot">
          <h2 className="block-h" id="tt-noslot">
            曜限なし
          </h2>
          <ul className="lines">
            {noSlot.map((c) => (
              <li key={c.code}>
                {nameLink(c)}
                <span className="meta">
                  {c.slotNote ?? ''} {isRequired(c) ? '必修' : creditsText(c)}
                </span>
                {isRequired(c) ? <span /> : removeButton(c)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {outside.length > 0 && (
        <section className="block" aria-labelledby="tt-outside">
          <h2 className="block-h" id="tt-outside">
            学科のデータに無い候補（時間割に入りません）
          </h2>
          <ul className="lines">
            {outside.map((code) => (
              <li key={code}>
                <span>{code}</span>
                <span className="meta" />
                <button className="text-btn" type="button" onClick={() => removeKeep(code)} aria-label={`${code}を外す`}>
                  外す
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="tt-accs accs">
        <Accordion label="卒業に要る単位" hint={req === null ? 'まだ入っていません' : `${total} / ${req.total}`}>
          {req === null || progress === null ? (
            <p className="seq-note">学科の卒業要件はまだ入っていません。</p>
          ) : (
            <>
              <div className="grad">
                <span className="h">区分</span>
                <span className="h r">入れた単位</span>
                <span className="h r">卒業に要る</span>
                {progress.map((g) => (
                  <GradRow key={g.category} label={g.category} placed={g.placed} need={g.need} />
                ))}
                <GradRow label="合計" placed={total} need={req.total} />
              </div>
              <p className="src">全学期の必修と候補を足しています。卒業に要る単位と上限は見本の数です。</p>
            </>
          )}
        </Accordion>
        <Accordion label="ほかの学期の候補" hint={`${elsewhere.length}件`}>
          <ul className="lines">
            {elsewhere.length === 0 ? (
              <li>
                <span className="meta">まだありません</span>
              </li>
            ) : (
              elsewhere.map((c) => (
                <li key={c.code}>
                  {nameLink(c)}
                  <span className="meta">
                    {courseTermLabel(c)} {c.slots.join('・')}
                  </span>
                  {removeButton(c)}
                </li>
              ))
            )}
          </ul>
        </Accordion>
      </div>
      <p className="foot">候補は履修登録ではありません。この端末のブラウザにだけ保存されます。</p>
    </>
  )
}

function creditsText(c: Course): string {
  return c.credits === null ? '単位は記載なし' : `${c.credits}単位`
}

interface GradRowProps {
  label: string
  placed: number
  need: number
}

function GradRow({ label, placed, need }: GradRowProps) {
  return (
    <>
      <span>{label}</span>
      <span className="r">{placed}</span>
      <span className="r">{need}</span>
    </>
  )
}
