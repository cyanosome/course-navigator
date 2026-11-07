import { useCallback, useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiErrorMessage } from '../../navi/api'
import { useNaviData } from '../../navi/dataSource'
import { findCourse, findFrame, sequenceOf } from '../../navi/graph'
import type { CourseMapping, UnmappedCourse } from '../../navi/mapping'
import { useResearchLog, useSyllabusViewLog } from '../../navi/research'
import { courseHref, groupHref, useNavi } from '../../navi/state'
import type { Origin, PaneState, PcTab, TrailEntry } from '../../navi/state'
import { courseTermLabel, isRequired, slotLong } from '../../navi/timetable'
import type { AgentSource, Course } from '../../navi/types'
import { LOADING, useLoadable } from '../../navi/useLoadable'
import { useFlags } from '../../navi/variant'
import { clashText, detailWhy, isOtherTerm, leadText, WIDE_SPACE } from '../../navi/views'
import type { ListContext } from '../../navi/views'
import Accordion from './Accordion'
import BackLink from './BackLink'
import Crumbs from './Crumbs'
import Icon from './Icon'
import PlanCourseBody from './PlanCourseBody'

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

interface DetailNavProps {
  trail: TrailEntry[]
  current: string
  tab: PcTab
}

/** 詳細の上の道筋。PC はパンくず、スマホは上の帯の戻る（ここには出さない）、診断の変種は作る場所の上の戻る */
function DetailNav({ trail, current, tab }: DetailNavProps) {
  const { isPc } = useNavi()
  const flags = useFlags()
  if (flags.diagnose === 'quiz') return <BackLink entry={trail[trail.length - 1] ?? { label: 'さがす', href: '/navi' }} />
  return isPc ? <Crumbs trail={trail} current={current} tab={tab} /> : null
}

/** 詳細を開いた記録（syllabus_open）の from。来た場所の種類 */
const OPEN_FROM: Record<Origin['kind'], string> = {
  default: 'recommend',
  dir: 'interest',
  course: 'sequence',
  group: 'group',
  ask: 'ask',
  tt: 'timetable',
  plan: 'plan',
  refine: 'refine',
  status: 'status',
  none: 'search',
}

/**
 * 科目の詳細（W3。PC は中央の段）。詳細は API（D5）から取る。学科の科目に無い科目（検索・AI の結果）も同じ口で出す。
 * 読み込み中・見つからない・読み込めない・表示できない科目を出し分け、取れた科目は CourseBody で出す。
 */
export default function CourseDetail({ code, origin, trail, tab }: CourseDetailProps) {
  const { dept, ask } = useNavi()
  const flags = useFlags()
  const { loadCourse } = useNaviData()
  const titleId = useId()
  const [reload, setReload] = useState(0)
  const onRetry = useCallback(() => setReload((n) => n + 1), [])
  const fetchCourse = useCallback((signal: AbortSignal) => loadCourse(code, signal), [loadCourse, code])
  const load = useLoadable<CourseMapping>(`${code}#${reload}`, fetchCourse, '科目の詳細') ?? LOADING
  // 取れる前と取れないときは、学科の科目にあればその名前を出す
  const name = findCourse(dept, code)?.name

  if (load.status === 'loading') {
    return (
      <section className="detail" aria-labelledby={titleId} aria-busy="true">
        <DetailNav trail={trail} current={name ?? code} tab={tab} />
        <h1 className="title" id={titleId}>
          {name ?? '科目の詳細'}
        </h1>
        <p className="text" role="status">
          読み込んでいます
        </p>
      </section>
    )
  }

  if (load.status === 'failed') {
    if (load.error instanceof ApiError && load.error.status === 404) {
      const source = ask?.result?.sources.find((s) => s.code === code)
      if (source !== undefined) return <OutsideCourse source={source} trail={trail} tab={tab} />
      return (
        <section className="detail" aria-labelledby={titleId}>
          <DetailNav trail={trail} current={code} tab={tab} />
          <h1 className="title" id={titleId}>
            この科目は見つかりませんでした
          </h1>
          <p className="text">
            科目 {code} は、データにありません。<Link to="/navi">さがすに戻る</Link>
          </p>
        </section>
      )
    }
    return (
      <section className="detail" aria-labelledby={titleId}>
        <DetailNav trail={trail} current={name ?? code} tab={tab} />
        <h1 className="title" id={titleId}>
          科目の詳細を読み込めませんでした
        </h1>
        <p className="text" role="alert">
          {apiErrorMessage(load.error)}
        </p>
        <div className="page-acts">
          <button className="primary" type="button" onClick={onRetry}>
            もう一度読み込む
          </button>
        </div>
      </section>
    )
  }

  if (!load.value.ok) return <UnmappedDetail course={load.value} trail={trail} tab={tab} />
  // 診断の変種は、プランの中でのその科目を出す詳細（デザインのコンペの U-a）
  if (flags.diagnose === 'quiz') {
    return <PlanCourseBody course={load.value.course} origin={origin} from={OPEN_FROM[origin.kind]} back={trail[trail.length - 1] ?? { label: 'さがす', href: '/navi' }} />
  }
  return <CourseBody course={load.value.course} origin={origin} trail={trail} tab={tab} />
}

interface UnmappedDetailProps {
  course: UnmappedCourse
  trail: TrailEntry[]
  tab: PcTab
}

const MISSING_LABEL = { year: '学年', term: '学期' } as const

/** 学年か学期を読めない科目（時間割に置けないので、今の画面では出せない。扱いは T15 で決める） */
function UnmappedDetail({ course, trail, tab }: UnmappedDetailProps) {
  const titleId = useId()
  return (
    <section className="detail" aria-labelledby={titleId}>
      <DetailNav trail={trail} current={course.name} tab={tab} />
      <h1 className="title" id={titleId}>
        {course.name}
      </h1>
      <p className="text">
        シラバスの{course.missing.map((m) => MISSING_LABEL[m]).join('と')}を読めないため、表示できません。
        {course.syllabusUrl !== null && (
          <a href={course.syllabusUrl} target="_blank" rel="noopener noreferrer">
            シラバスの原文<span className="vh">（大学のサイトが新しいタブで開きます）</span>
          </a>
        )}
      </p>
    </section>
  )
}

interface CourseBodyProps {
  course: Course
  origin: Origin
  trail: TrailEntry[]
  tab: PcTab
}

/**
 * 取れた科目の詳細。E1 3章・4章: 科目名、5つの項目、［候補に入れる］、授業でやること、なぜ、
 * 開閉（取る順・授業計画・成績のつけ方と教科書）、原文。データが無い項目は行を残して理由を灰で書く（E1 8章）。
 * 旗 graph=off では「取る順」と、系統図から言う「なぜ」を出さない（AI の判断の「なぜ」は出す）。
 */
function CourseBody({ course, origin, trail, tab }: CourseBodyProps) {
  const { dept, ask, isKept, toggleKeep, track, shortlist, placement, focusTerm, assumedTerm } = useNavi()
  const flags = useFlags()
  const { log } = useResearchLog()
  const titleId = useId()
  useSyllabusViewLog(course.code, OPEN_FROM[origin.kind])
  // 旗も渡す（detailWhy は recommend=catalog・off のとき、おすすめの並びの説明を出さない）
  const ctx: ListContext = { dept, shortlist, focusTerm, assumedTerm, flags, placement }
  const kept = isKept(course.code)
  const required = isRequired(course)
  const why = detailWhy(ctx, course, origin, ask)
  const here = courseHref(course.code, origin)
  const ancestors = [...trail, { label: course.name, href: here }]
  const step = (label: string, href: string): PaneState => ({ trail: [...ancestors, { label, href }], tab })
  const seq = sequenceOf(dept, course)
  const frame = findFrame(dept, course.frameId)
  const lead = leadText(course)
  const showGraph = flags.graph === 'on'
  const showWhy = showGraph || why.ai
  const traverse = (to: Course, direction: 'before' | 'after') => {
    track({ type: 'traverse' })
    log('sequence_click', { from_syllabus_id: course.code, to_syllabus_id: to.code, direction })
  }

  return (
    <article className="detail" aria-labelledby={titleId}>
      <DetailNav trail={trail} current={course.name} tab={tab} />
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
          <button className="primary" type="button" aria-pressed={kept} onClick={() => toggleKeep(course.code, 'detail')}>
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

      {showWhy && (
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
      )}

      <div className="accs">
        {showGraph && (
          <Accordion
            label="取る順"
            hint={[seq.before.length > 0 ? `前に${seq.before.length}科目` : '', seq.after.length > 0 ? `後に${seq.after.length}科目` : '']
              .filter((x) => x !== '')
              .join(WIDE_SPACE) || '前後の科目なし'}
          >
            <ol className="seq">
              {seq.before.length > 0 && <li className="seq-h">先に取る</li>}
              {seq.before.map((c) => (
                <SeqItem key={c.code} course={c} from={course} step={step} onTraverse={() => traverse(c, 'before')} />
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
                <SeqItem key={c.code} course={c} from={course} step={step} onTraverse={() => traverse(c, 'after')} />
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
        )}
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
            onClick={() => {
              track({ type: 'original' })
              log('original_open', { syllabus_id: course.code })
            }}
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
  const { dept, shortlist, placement, focusTerm, assumedTerm } = useNavi()
  const ctx = { dept, shortlist, focusTerm, assumedTerm, placement }
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
  const { isKept, toggleKeep } = useNavi()
  // 診断の変種では、データに無い科目はプランに入れられない（詳細を読めないので学期が決まらない）
  const planMode = useFlags().diagnose === 'quiz'
  const titleId = useId()
  useSyllabusViewLog(source.code, 'ask')
  const kept = isKept(source.code)
  return (
    <article className="detail" aria-labelledby={titleId}>
      <DetailNav trail={trail} current={source.title} tab={tab} />
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
      {!planMode && (
        <button className="primary" type="button" aria-pressed={kept} onClick={() => toggleKeep(source.code, 'detail')}>
          <Icon name={kept ? 'check' : 'plus'} />
          <span>{kept ? '候補に入っています' : '候補に入れる'}</span>
        </button>
      )}
      <section className="sec">
        <h2 className="sec-label">授業でやること</h2>
        <p className={source.excerpt === '' ? 'lead is-missing' : 'lead'}>{source.excerpt === '' ? 'シラバスに記載なし' : source.excerpt}</p>
      </section>
      <p className="detail-foot">この科目は学科の履修系統図に載っていないので、時間割には入りません。原文へのリンクはまだありません。</p>
    </article>
  )
}

