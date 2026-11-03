import { useId } from 'react'
import { Link } from 'react-router-dom'
import type { ProposalView } from '../../navi/views'
import EvidenceLabel from './EvidenceLabel'
import Glyph from './Glyph'
import KeepButton from './KeepButton'

interface ProposalCardProps {
  item: ProposalView
}

/** 提案カード（スマホ。W1・W2・W13・W5-3 で同じ形。UX 仕様 C05、DESIGN.md 6章） */
export function ProposalCard({ item }: ProposalCardProps) {
  const ai = item.evidence === 'ai'
  const nameId = useId()
  return (
    <article className={ai ? 'card card--ai' : 'card'} aria-labelledby={nameId}>
      <h3 className="card__name" id={nameId}>
        {item.name}
      </h3>
      <p className="card__meta">{item.meta}</p>
      <p className="card__why">
        <b>{item.whyLabel}</b> {item.why}
      </p>
      <p className="card__ev">
        <EvidenceLabel kind={item.evidence} />
        {item.aside !== undefined && <span className="note">{item.aside}</span>}
      </p>
      <div className="card__acts">
        <Link className="btn btn--ink" to={item.href} state={item.linkState} aria-label={`${item.name}の理由と出典`}>
          理由と出典
          <Glyph name="next" />
        </Link>
        <KeepButton code={item.code} name={item.name} />
      </div>
    </article>
  )
}

interface ProposalItemProps {
  item: ProposalView
  current: boolean
}

/** PC の左ペインの一覧の項目（DESIGN.md 6章 PC の左右ペイン） */
export function ProposalItem({ item, current }: ProposalItemProps) {
  const ai = item.evidence === 'ai'
  return (
    <li className={ai ? 'item item--ai' : 'item'} aria-current={current ? 'true' : undefined}>
      <h3 className="item__name">
        <Link to={item.href} state={item.linkState}>
          {item.name}
        </Link>
      </h3>
      <p className="item__why">
        {item.whyLabel} {item.why}
      </p>
      <p className="item__ev">
        <EvidenceLabel kind={item.evidence} />
        {item.aside !== undefined && <span className="note"> {item.aside}</span>}
      </p>
      <KeepButton code={item.code} name={item.name} />
    </li>
  )
}
