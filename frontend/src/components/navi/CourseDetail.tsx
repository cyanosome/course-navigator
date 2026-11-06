import { useId } from 'react'
import { Link } from 'react-router-dom'
import { findCourse, findFrame, sequenceOf } from '../../navi/graph'
import { courseHref, groupHref, useNavi } from '../../navi/state'
import type { Origin, PaneState, PcTab, TrailEntry } from '../../navi/state'
import { courseTermLabel, isRequired, slotLong } from '../../navi/timetable'
import type { AgentSource, Course } from '../../navi/types'
import { clashText, detailWhy, isOtherTerm, leadText, WIDE_SPACE } from '../../navi/views'
import type { ListContext } from '../../navi/views'
import Accordion from './Accordion'
import Crumbs from './Crumbs'
import Icon from './Icon'

interface CourseDetailProps {
  code: string
  origin: Origin
  /** この科目より前にたどった道筋（PC のパンくず。trail[0] は来た一覧） */
  trail: TrailEntry[]
  tab: PcTab
}

const UNUSED_INFO = '難しさ、評判、あなたの成績は使っていません。'
/** 375px の項目の表で、曜限の値に使える幅（2列の片方から見出し語と間を引いた幅）。超えたら1行を使う */
const SLOT_CELL_PX = 112
const VALUE_PX = 16
const NOTE_PX = 14
const HALF_WIDTH = 0.55

/** 曜限と横の灰の文字の幅の見積もり（半角は 0.55 字、全角は 1 字） */
function slotWidth(value: string, note: string): number {
  const em = (t: string) => Array.from(t).reduce((n, ch) => n + (ch.charCodeAt(0) < 0x80 ? HALF_WIDTH : 1), 0)
  return em(value) * VALUE_PX + (note === '' ? 0 : em(` ${note}`) * NOTE_PX)
}

/**
 * 科目の詳細（W3。PC は中央の段）。E1 3章・4章: 科目名、5つの項目、［候補に入れる］、授業でやること、なぜ、
 * 開閉（取る順・授業計画・成績のつけ方と教科書）、原文。データが無い項目は行を残して理由を灰で書く（E1 8章）。
 */
export default function CourseDetail({ code, origin, trail, tab }: CourseDetailProps) {
  const { dept, ask, isPc, isKept, toggleKeep, track, shortlist, focusTerm, assumedTerm } = useNavi()
  const titleId = useId()
  const course = findCourse(dept, code)

  if (course === undefined) {
    const source = ask?.result?.sources.find((s) => s.code === code)
    if (source !== undefined) return <OutsideCourse source={source} trail={trail} tab={tab} />
    return (
      <section className="detail" aria-labelledby={titleId}>
        {isPc && <Crumbs trail={trail} current={code} tab={tab} />}
        <h1 className="title" id={titleId}>
          この科目は見つかりませんでした
        </h1>
        <p className="text">
          科目コード {code} は、この学科のデータにありません。<Link to="/navi">さがすに戻る</Link>
        </p>
      </section>
    )
  }

  const ctx = { dept, shortlist, focusTerm, assumedTerm }
  const kept = isKept(course.code)
  const required = isRequired(course)
  const why = detailWhy(ctx, course, origin, ask)
  const here = courseHref(course.code, origin)
  const ancestors = [...trail, { label: course.name, href: here }]
  const step = (label: string, href: string): PaneState => ({ trail: [...ancestors, { label, href }], tab })
  const seq = sequenceOf(dept, course)
  const frame = findFrame(dept, course.frameId)
  const lead = leadText(course)

  return (
    <article className="detail" aria-labelledby={titleId}>
      {isPc && <Crumbs trail={trail} current={course.name} tab={tab} />}
      <h1 className="title" id={titleId}>
        {course.name}
        {course.faculty !== null && <span className="fac"> {course.faculty}</span>}
      </h1>
      <dl className="facts">
        <div className={slotWidth(slotLong(course), fitText(ctx, course, kept)) > SLOT_CELL_PX ? 'wide' : undefined}>
          <dt>曜限</dt>
          <dd>
            {slotLong(course)} <SlotFit course={course} kept={kept} />
          </dd>
        </div>
        <div>
          <dt>単位</dt>
          <dd>{course.credits ?? <span className="note">記載なし</span>}</dd>
        </div>
        <div>
          <dt>対象</dt>
          <dd>
            {course.yearRange ?? `${course.year}年`} {course.term === '通年' ? '通年' : `${course.term}学期`}
          </dd>
        </div>
        <div>
          <dt>区分</dt>
          <dd>{course.kind ?? <span className="note">準備中</span>}</dd>
        </div>
        <div className="wide">
          <dt>担当</dt>
          <dd>
            {course.teacher.status === 'known' ? (
              course.teacher.name
            ) : (
              <span className="note">{course.teacher.status === 'notInSyllabus' ? 'シラバスに記載なし' : '準備中'}</span>
            )}
          </dd>
        </div>
      </dl>
      {course.faculty !== null && <p className="facts-note">卒業の単位に数えられるかは、学部の決まりで変わります。</p>}

      {required ? (
        <p className="primary-note">学科の必修なので、時間割に入れてあります。</p>
      ) : (
        <>
          <button className="primary" type="button" aria-pressed={kept} onClick={() => toggleKeep(course.code)}>
            <Icon name={kept ? 'check' : 'plus'} />
            <span>{kept ? '候補に入っています' : '候補に入れる'}</span>
          </button>
          {kept && <p className="primary-note">もう一度押すと外します</p>}
        </>
      )}

      <section className="sec">
        <h2 className="sec-label">授業でやること</h2>
        <p className={lead.missing ? 'lead is-missing' : 'lead'}>{lead.text}</p>
        {!lead.missing && <p className="src">{dept.syllabusYear}年度シラバスより</p>}
      </section>

      <section className="sec">
        <h2 className="sec-label">
          <Icon name="why" small />
          なぜ
        </h2>
        <p className="text">{why.text}</p>
        <p className="src">
          {why.source}
          {why.ai && ' 間違うことがあります。シラバスの原文で確かめてください。'}
        </p>
      </section>

      <div className="accs">
        <Accordion
          label="取る順"
          hint={[seq.before.length > 0 ? `前に${seq.before.length}科目` : '', seq.after.length > 0 ? `後に${seq.after.length}科目` : '']
            .filter((x) => x !== '')
            .join(WIDE_SPACE) || '前後の科目なし'}
        >
          <ol className="seq">
            {seq.before.length > 0 && <li className="seq-h">先に取る</li>}
            {seq.before.map((c) => (
              <SeqItem key={c.code} course={c} from={course} step={step} onTraverse={() => track({ type: 'traverse' })} />
            ))}
            <li className="seq-h">この科目</li>
            <li>
              <div className="seq-item is-here">
                <span className="seq-name">{course.name}</span>
                <span className="seq-meta">
                  {courseTermLabel(course)} {course.slots.join('・')}
                </span>
                <span />
              </div>
            </li>
            {seq.after.length > 0 && <li className="seq-h">あとに続く</li>}
            {seq.after.map((c) => (
              <SeqItem key={c.code} course={c} from={course} step={step} onTraverse={() => track({ type: 'traverse' })} />
            ))}
          </ol>
          {frame !== undefined && seq.same.length > 0 && (
            <Link
              className="seq-group"
              to={groupHref(frame.id, { kind: 'course', code: course.code })}
              state={step(frame.name, groupHref(frame.id, { kind: 'course', code: course.code }))}
              onClick={() => track({ type: 'traverse' })}
            >
              <span>同じまとまりの科目（{frame.name}、ほかに{seq.same.length}科目）</span>
              <Icon name="next" small />
            </Link>
          )}
          <p className="seq-note">
            {frame === undefined
              ? 'この科目は学科の履修系統図に載っていません。'
              : '系統図の線は科目のまとまりどうしを結ぶもので、直接の前提とは限りません。'}
          </p>
        </Accordion>
        <Accordion label="授業計画" hint={course.plan.length > 0 ? `${course.plan.length}回` : '記載なし'}>
          {course.plan.length > 0 ? (
            <ol className="plan">
              {course.plan.map((t, i) => (
                <li key={i}>
                  <span className="no">第{i + 1}回</span>
                  <span>{t}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="seq-note">シラバスに授業計画が書かれていません。</p>
          )}
        </Accordion>
        <Accordion label="成績のつけ方と教科書" hint={course.grading === null && course.textbook === null ? '記載なし' : ''}>
          <dl className="kv">
            <dt>成績</dt>
            <dd className={course.grading === null ? 'is-missing' : undefined}>{course.grading ?? '記載なし'}</dd>
            <dt>教科書</dt>
            <dd className={course.textbook === null ? 'is-missing' : undefined}>{course.textbook ?? '記載なし'}</dd>
          </dl>
        </Accordion>
        {course.syllabusUrl !== null && (
          <a
            className="acc-link"
            href={course.syllabusUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => track({ type: 'original' })}
          >
            <span>
              シラバスの原文<span className="vh">（大学のサイトが新しいタブで開きます）</span>
            </span>
            <Icon name="ext" />
          </a>
        )}
      </div>
      <p className="detail-foot">{UNUSED_INFO}</p>
    </article>
  )
}

interface SlotFitProps {
  course: Course
  kept: boolean
}

/**
 * 曜限の横の「空き」「○○と重なる」。いま見ている時間割の学期と違う学期の科目は、学期を添える
 * （例 木3 3年春は空き）。オーナーの追加の指示（2026-11-04）: どの学期の話かを、文字を増やしすぎずに書く。
 */
function SlotFit({ course, kept }: SlotFitProps) {
  const { dept, shortlist, focusTerm, assumedTerm } = useNavi()
  const ctx = { dept, shortlist, focusTerm, assumedTerm }
  const text = fitText(ctx, course, kept)
  if (text === '') return null
  return <span className={clashText(ctx, course) !== null ? 'note is-clash' : 'note'}>{text}</span>
}

/** 曜限の横の灰の文字（無ければ空） */
function fitText(ctx: ListContext, course: Course, kept: boolean): string {
  if (course.slots.length === 0 || isRequired(course)) return ''
  const clash = clashText(ctx, course)
  if (clash !== null) return clash
  if (kept) return ''
  const prefix = isOtherTerm(course, ctx.focusTerm) ? `${courseTermLabel(course)}は` : ''
  return `${prefix}空き`
}

interface SeqItemProps {
  course: Course
  from: Course
  step: (label: string, href: string) => PaneState
  onTraverse: () => void
}

function SeqItem({ course, from, step, onTraverse }: SeqItemProps) {
  const href = courseHref(course.code, { kind: 'course', code: from.code })
  return (
    <li>
      <Link className="seq-item" to={href} state={step(course.name, href)} onClick={onTraverse}>
        <span className="seq-name">{course.name}</span>
        <span className="seq-meta">
          {courseTermLabel(course)} {course.slots.join('・')}
        </span>
        <Icon name="next" small />
      </Link>
    </li>
  )
}

interface OutsideCourseProps {
  source: AgentSource
  trail: TrailEntry[]
  tab: PcTab
}

/** 自由記述の結果から来た、学科データに無い科目（UX 仕様 W3 の注。sources の項目だけで作る） */
function OutsideCourse({ source, trail, tab }: OutsideCourseProps) {
  const { isPc, isKept, toggleKeep } = useNavi()
  const titleId = useId()
  const kept = isKept(source.code)
  return (
    <article className="detail" aria-labelledby={titleId}>
      {isPc && <Crumbs trail={trail} current={source.title} tab={tab} />}
      <h1 className="title" id={titleId}>
        {source.title}
      </h1>
      <dl className="facts">
        <div className="wide">
          <dt>曜限</dt>
          <dd>{source.schedule ?? <span className="note">記載なし</span>}</dd>
        </div>
        <div>
          <dt>単位</dt>
          <dd>{source.credits ?? <span className="note">記載なし</span>}</dd>
        </div>
        <div className="wide">
          <dt>担当</dt>
          <dd>{source.instructor ?? <span className="note">準備中</span>}</dd>
        </div>
      </dl>
      <button className="primary" type="button" aria-pressed={kept} onClick={() => toggleKeep(source.code)}>
        <Icon name={kept ? 'check' : 'plus'} />
        <span>{kept ? '候補に入っています' : '候補に入れる'}</span>
      </button>
      <section className="sec">
        <h2 className="sec-label">授業でやること</h2>
        <p className={source.excerpt === '' ? 'lead is-missing' : 'lead'}>{source.excerpt === '' ? 'シラバスに記載なし' : source.excerpt}</p>
      </section>
      <p className="detail-foot">この科目は学科の履修系統図に載っていないので、時間割には入りません。原文へのリンクはまだありません。</p>
    </article>
  )
}

