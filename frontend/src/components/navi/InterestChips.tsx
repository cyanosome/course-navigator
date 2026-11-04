import { useNavigate } from 'react-router-dom'
import { listHref, useNavi } from '../../navi/state'
import Icon from './Icon'

interface InterestChipsProps {
  /** 選んでいる興味関心（既定は default = おすすめ） */
  selected: string
}

/** 興味関心のチップ（E1 2章。375px で2行に折り返し、横スクロールにしない）。選んだものは緑の輪とチェック */
export default function InterestChips({ selected }: InterestChipsProps) {
  const { dept, track } = useNavi()
  const navigate = useNavigate()

  const choose = (id: string) => {
    if (id !== 'default') track({ type: 'dir', dirId: id })
    navigate(listHref(id))
  }

  return (
    <div className="chips" role="group" aria-label="興味関心">
      {dept.interests.map((d) => {
        const on = d.id === selected
        return (
          <button key={d.id} className="chip" type="button" aria-pressed={on} onClick={() => choose(d.id)}>
            {on && <Icon name="check" small />}
            {d.label}
          </button>
        )
      })}
    </div>
  )
}
