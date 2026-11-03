import { useId } from 'react'
import { Link } from 'react-router-dom'
import { FIXTURE_SYLLABUS_BASE } from '../../navi/fixtureDepartment'
import { coursesInFrame, findCourse, findFrame, frameLabel, nextFrames, prevFrames, SHOWN_PER_GROUP, termLabel } from '../../navi/graph'
import { courseHref, groupHref, useNavi } from '../../navi/state'
import type { Origin, PaneState, PcTab, TrailEntry } from '../../navi/state'
import type { AgentSource, Course, Frame } from '../../navi/types'
import { detailWhy } from '../../navi/views'
import Crumbs from './Crumbs'
import EvidenceLabel from './EvidenceLabel'
import Glyph from './Glyph'
import KeepButton from './KeepButton'

interface CourseDetailProps {
  code: string
  origin: Origin
  /** PC の右ペインの道筋（スマホは[< 戻る]を使うので空） */
  trail: TrailEntry[]
  tab: PcTab
}

const UNUSED_INFO = '難しさ、単位の取りやすさ、評判、時間割の重なり、あなたの成績'

/** 科目の詳細（W3。PC は右ペイン）。DESIGN.md 6章「詳細（W3）の見出しと出典」 */
export default function CourseDetail({ code, origin, trail, tab }: CourseDetailProps) {
  const { dept, ask, track } = useNavi()
  const titleId = useId()
  const course = findCourse(dept, code)

  if (course === undefined) {
    const source = ask?.result?.sources.find((s) => s.code === code)
    if (source !== undefined) return <OutsideCourse source={source} titleId={titleId} trail={trail} tab={tab} />
    return (
      <section aria-labelledby={titleId}>
        <h1 className="d-title" id={titleId}>
          この科目は見つかりませんでした
        </h1>
        <p className="body-s">
          科目コード {code} は、この学科のデータにありません。<Link to="/navi">さがすに戻る</Link>
        </p>
      </section>
    )
  }

  const frame = findFrame(dept, course.frameId)
  const why = detailWhy(dept, course, origin, ask)
  const here: Origin = { kind: 'course', code: course.code }
  const step = (label: string, href: string): PaneState => ({ trail: [...trail, { label, href }], tab })
  const remaining = course.planTotal - course.plan.length

  return (
    <article aria-labelledby={titleId}>
      <Crumbs trail={trail} tab={tab} />
      <div className="d-cols">
        <div>
          <h1 className="d-title" id={titleId}>
            {course.name}
          </h1>
          <div className="d-meta">
            <dl>
              <div>
                <dt>開講</dt>
                <dd>{termLabel(course)}</dd>
              </div>
              <div>
                <dt>曜限</dt>
                <dd>{course.slot}</dd>
              </div>
              <div>
                <dt>単位</dt>
                <dd>{course.credits}単位</dd>
              </div>
              <div>
                <dt>担当</dt>
                <dd>（シラバスの表記）</dd>
              </div>
              <div>
                <dt>区分</dt>
                <dd>シラバスで確かめてください</dd>
              </div>
            </dl>
          </div>
          <div className="d-act">
            <KeepButton code={course.code} name={course.name} />
            <p className="note">もう一度押すと外れます。候補は履修登録ではありません。</p>
          </div>

          <section className="d-sec" aria-labelledby={`${titleId}-why`}>
            <h2 className="h-sec" id={`${titleId}-why`}>
              なぜ出てきたか
            </h2>
            {why.ai !== null && (
              <div className="why-ai">
                <p>
                  <b>AIの説明より:</b> {why.ai}
                </p>
                <EvidenceLabel kind="ai" />
                <p className="note">間違うことがあります。下のシラバスの抜粋と照らしてください。</p>
              </div>
            )}
            <div className="why-route">
              <p>{why.route}</p>
              <EvidenceLabel kind="route" />
            </div>
          </section>

          <section className="d-sec" aria-labelledby={`${titleId}-syl`}>
            <h2 className="h-sec" id={`${titleId}-syl`}>
              シラバスより（{dept.syllabusYear}年度）
              <EvidenceLabel kind="syllabus" />
            </h2>
            <div className="quote">
              {course.plan.length > 0 ? (
                <>
                  <h3>授業で扱うこと（授業計画から{course.plan.length}回分）</h3>
                  <ol className="plan">
                    {course.plan.map((p) => (
                      <li key={p.no}>
                        <span>第{p.no}回</span>
                        <span>{p.title}</span>
                      </li>
                    ))}
                    {remaining > 0 && (
                      <li>
                        <span />
                        <span className="note">… ほか{remaining}回</span>
                      </li>
                    )}
                  </ol>
                </>
              ) : (
                <p className="body-s">このモックには、この科目の授業計画の抜粋を入れていません。原文で確かめてください。</p>
              )}
              {course.summary !== '' && (
                <>
                  <h3>概要（抜粋）</h3>
                  <p className="excerpt">「{course.summary}」</p>
                </>
              )}
              <a
                className="btn"
                href={`${FIXTURE_SYLLABUS_BASE}${course.code}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => track({ type: 'original' })}
              >
                シラバス原文を開く（大学のサイト）
                <Glyph name="external" />
              </a>
            </div>
          </section>
        </div>

        <div>
          <section className="d-sec" aria-labelledby={`${titleId}-route`}>
            <h2 className="h-sec" id={`${titleId}-route`}>
              系統図での位置
              <EvidenceLabel kind="route" />
            </h2>
            <ol className="route">
              <li className="route__stop">
                <p className="route__kind">先に取っておく枠（前提）</p>
                <FrameList
                  frames={prevFrames(dept, course.frameId)}
                  exclude={course.code}
                  origin={here}
                  step={step}
                  onTraverse={() => track({ type: 'traverse' })}
                  none="系統図では、この科目の枠に線が入ってくる枠はありません。"
                />
              </li>
              <li className="route__stop route__stop--here">
                <p className="route__kind">この科目の枠</p>
                {frame !== undefined && (
                  <FrameList
                    frames={[frame]}
                    exclude={course.code}
                    origin={here}
                    step={step}
                    onTraverse={() => track({ type: 'traverse' })}
                    suffix="（同じ枠の科目）"
                    none=""
                  />
                )}
              </li>
              <li className="route__stop">
                <p className="route__kind">つながる先の枠</p>
                <FrameList
                  frames={nextFrames(dept, course.frameId)}
                  exclude={course.code}
                  origin={here}
                  step={step}
                  onTraverse={() => track({ type: 'traverse' })}
                  none="系統図では、この科目の枠から線が出ていく枠はありません。"
                />
              </li>
            </ol>
            <p className="note route-note">
              線は枠どうしを結んでいます。枠の中のどの科目が直接の前提かまでは、系統図に書かれていません。枠の中の並びは学期→系統図の記載順で、関係の強さの順ではありません。
            </p>
          </section>
        </div>
      </div>

      <section className="unused" aria-labelledby={`${titleId}-unused`}>
        <h2 className="label" id={`${titleId}-unused`}>
          この画面で使っていない情報
        </h2>
        <p>{UNUSED_INFO}</p>
      </section>
    </article>
  )
}

interface FrameListProps {
  frames: Frame[]
  exclude: string
  origin: Origin
  step: (label: string, href: string) => PaneState
  onTraverse: () => void
  suffix?: string
  none: string
}

/** 前後の枠の行（枠ごとに科目を3件まで。UX 仕様 C01、DESIGN.md F3） */
function FrameList({ frames, exclude, origin, step, onTraverse, suffix = '', none }: FrameListProps) {
  const { dept } = useNavi()
  if (frames.length === 0) return none === '' ? null : <p className="note frame__none">{none}</p>
  return (
    <>
      {frames.map((f) => {
        const all = coursesInFrame(dept, f.id)
        const shown = all.filter((c) => c.code !== exclude).slice(0, SHOWN_PER_GROUP)
        const gHref = groupHref(f.id, origin)
        const gLabel = `${frameLabel(f)}の枠`
        return (
          <div key={f.id} className="frame">
            <p className="frame__name">
              {frameLabel(f)}
              {suffix}
            </p>
            {shown.length > 0 && (
              <ul>
                {shown.map((c: Course) => {
                  const href = courseHref(c.code, origin)
                  return (
                    <li key={c.code}>
                      <span>{c.name}</span> <span className="term">{termLabel(c)}</span>
                      <Link className="link" to={href} state={step(c.name, href)} onClick={onTraverse} aria-label={`${c.name}の理由と出典`}>
                        理由と出典
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
            <Link className="all" to={gHref} state={step(gLabel, gHref)} onClick={onTraverse}>
              この枠の科目をすべて見る（{all.length}科目）
            </Link>
          </div>
        )
      })}
    </>
  )
}

interface OutsideCourseProps {
  source: AgentSource
  titleId: string
  trail: TrailEntry[]
  tab: PcTab
}

/** 自由記述の結果から来た、学科データに無い科目（UX 仕様 W3 の注。sources の項目だけで作る） */
function OutsideCourse({ source, titleId, trail, tab }: OutsideCourseProps) {
  const meta = [source.schedule, source.credits === null ? null : `${source.credits}単位`].filter((x) => x !== null).join('・')
  return (
    <article aria-labelledby={titleId}>
      <Crumbs trail={trail} tab={tab} />
      <h1 className="d-title" id={titleId}>
        {source.title}
      </h1>
      <p className="d-meta">{meta}</p>
      <div className="d-act">
        <KeepButton code={source.code} name={source.title} />
      </div>
      <p className="body-s d-sec">この科目は学科の履修系統図に載っていません。</p>
      {source.excerpt !== '' && (
        <section className="d-sec">
          <h2 className="h-sec">
            シラバスより
            <EvidenceLabel kind="syllabus" />
          </h2>
          <div className="quote">
            <p className="excerpt">「{source.excerpt}」</p>
          </div>
        </section>
      )}
      <p className="note d-sec">原文リンクはまだありません。</p>
    </article>
  )
}
