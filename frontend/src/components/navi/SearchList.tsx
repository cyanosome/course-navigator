import { useId, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { directionStages, directionTargetsLabel, findDirection } from '../../navi/graph'
import { groupHref, useNavi } from '../../navi/state'
import type { Origin } from '../../navi/state'
import type { Course } from '../../navi/types'
import { defaultShortWhy, defaultViews, stageViews } from '../../navi/views'
import type { ProposalView } from '../../navi/views'
import AskBlock from './AskBlock'
import AskForm from './AskForm'
import DirectionChips from './DirectionChips'
import EvidenceLabel from './EvidenceLabel'
import Glyph from './Glyph'
import { ProposalCard, ProposalItem } from './ProposalCard'

interface SearchListProps {
  dirId: string
  variant: 'mobile' | 'pc'
  /** PC の右ペインに出している科目 */
  currentCode?: string
  /** PC の右ペインの科目（W6-1 の科目ごとの案内） */
  contextCourse?: Course
}

/** 方向のチップへ移る（[方向から探す]） */
function focusDirections(id: string) {
  const group = document.getElementById(id)
  group?.scrollIntoView({ block: 'start' })
  group?.querySelector('button')?.focus()
}

const FRAME_LINE_NOTE =
  '線は枠どうしを結んでいます。枠の中のどの科目が直接の前提かまでは、系統図に書かれていません。'

/**
 * さがす（W1 既定・W2 方向）の中身。スマホは画面の本体、PC は左ペイン（W11）。
 * 文言は UX 仕様 6.2 のワイヤーフレームのまま（W1 の前提の文は DESIGN.md S1 の直し）。
 */
export default function SearchList({ dirId, variant, currentCode, contextCourse }: SearchListProps) {
  const { dept, assumedYear, ask } = useNavi()
  const navigate = useNavigate()
  const [panelOpen, setPanelOpen] = useState(false)
  const dirsId = useId()
  const propsId = useId()
  const direction = findDirection(dept, dirId) ?? findDirection(dept, 'default')
  const isDefault = direction === undefined || direction.targets.length === 0
  const mobile = variant === 'mobile'

  const toDirections = () => {
    setPanelOpen(false)
    focusDirections(dirsId)
  }
  const onSent = (localId: string) => {
    setPanelOpen(false)
    if (mobile || currentCode === undefined) navigate(`/navi/ask/${encodeURIComponent(localId)}`)
  }
  const openPanel = () => {
    setPanelOpen(true)
    window.scrollTo({ top: 0 })
  }

  const list = (items: ProposalView[]) =>
    mobile ? (
      <ol className="cards">
        {items.map((v) => (
          <li key={v.code}>
            <ProposalCard item={v} />
          </li>
        ))}
      </ol>
    ) : (
      <ol className="items">
        {items.map((v) => (
          <ProposalItem key={v.code} item={v} current={v.code === currentCode} />
        ))}
      </ol>
    )

  const defaults = defaultViews(dept, assumedYear).map((v) =>
    mobile ? v : { ...v, why: defaultShortWhy(dept, findCourseOrThrow(dept.courses, v.code)) },
  )

  return (
    <>
      {mobile && panelOpen && (
        <AskForm variant="mobile" onSent={onSent} onClose={() => setPanelOpen(false)} onDirections={toDirections} />
      )}
      {!mobile && <AskForm variant="pc" onSent={onSent} onDirections={toDirections} course={contextCourse} />}

      {mobile && isDefault && (
        <section className="intro" aria-label="この画面の前提">
          <p className="note">想定: {assumedYear === 1 ? '1年の入学直後' : `${assumedYear}年の春`}</p>
          <p className="lead">
            方向が決まっていなくても使えます。まず、系統図で多くの方向につながる科目を出しています。好みはまだ使っていません。
          </p>
        </section>
      )}

      <section className={mobile ? 'dirs' : undefined} id={dirsId} aria-label="方向">
        <DirectionChips selected={direction?.id ?? 'default'} />
        {mobile && !panelOpen && (
          <button className="btn btn--ask" type="button" onClick={openPanel}>
            <span className="ev ev--ai" aria-hidden="true">
              <Glyph name="ai" />
              AI
            </span>
            自分の言葉で探す
          </button>
        )}
      </section>

      {ask !== null && (
        <AskBlock
          session={ask}
          variant={variant}
          currentCode={currentCode}
          onRephrase={() => (mobile ? setPanelOpen(true) : document.querySelector<HTMLInputElement>('.pane-list .input')?.focus())}
          onDirections={toDirections}
        />
      )}

      {isDefault || direction === undefined ? (
        <section className="props" aria-labelledby={propsId}>
          <h2 className="h-sec" id={propsId}>
            まず見ておきたい{defaults.length}科目
          </h2>
          <p className="note">（学科の誰にでも同じものを出しています）</p>
          {defaults.length === 0 ? (
            <p className="body-s">この想定の学年には、まず見ておきたい科目がありません。上の方向から選んでください。</p>
          ) : (
            list(defaults)
          )}
          <p className="note after">並び: 線がつながる方向の数が多い順</p>
          <p className="note">必修・選択の区分はまだ出せません（詳細のシラバス原文で確かめてください）</p>
        </section>
      ) : (
        <>
          <section className="dir-about" aria-labelledby={propsId}>
            <h2 className="h-sec" id={propsId}>
              {direction.label}
            </h2>
            <p className="body-s">{direction.description}</p>
            <p className="body-s">{directionTargetsLabel(dept, direction)}</p>
            <p className="note">使った情報: 学科、選んだ方向</p>
            <p className="note">
              取る順に、系統図の線をさかのぼって並べています。枠の中の並びは学期→系統図の記載順で、関係の強さの順ではありません。同じ枠の科目は、系統図の上では同じ関係です。
            </p>
          </section>
          <div className="stages">
            {directionStages(dept, direction).map((stage, si, all) => {
              const origin: Origin = { kind: 'dir', dirId: direction.id }
              return (
                <section key={stage.year} className="stage" aria-label={`${stage.year}年`}>
                  <div className="stage__head">
                    <h3 className="stage__year">{stage.year}年</h3>
                    <div className="stage__why">
                      <p>なぜ: {stage.why}</p>
                      <EvidenceLabel kind="route" />
                    </div>
                  </div>
                  {stage.frames.map((sf) => (
                    <div key={sf.frame.id} className="fgroup">
                      <h4 className="fgroup__name">枠: {sf.frame.name}</h4>
                      {sf.shown.length > 0 && list(stageViews(direction, sf))}
                      <Link className="all" to={groupHref(sf.frame.id, origin)}>
                        この枠の科目をすべて見る（{sf.total}科目）
                      </Link>
                    </div>
                  ))}
                  {si < all.length - 1 && <div className="stage__link" aria-hidden="true" />}
                </section>
              )
            })}
          </div>
          <p className="note route-note">{FRAME_LINE_NOTE}</p>
          <p className="note">必修・選択の区分はまだ出せません（詳細のシラバス原文で確かめてください）</p>
        </>
      )}
    </>
  )
}

function findCourseOrThrow(courses: Course[], code: string): Course {
  const c = courses.find((x) => x.code === code)
  if (c === undefined) throw new Error(`学科データに無い科目です: ${code}`)
  return c
}
