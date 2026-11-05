import { useNavigate } from 'react-router-dom'
import { setKeywordQuery } from '../../navi/keyword'
import { useResearchLog } from '../../navi/research'
import { listHref, useNavi } from '../../navi/state'
import { useFlags } from '../../navi/variant'
import Icon from './Icon'

interface InterestChipsProps {
  /** 選んでいる興味関心（既定は default = おすすめ。キーワード検索の結果を出しているあいだは空 = どれも選ばない） */
  selected: string
  /** 隠したあとに戻すとき、開閉の中身と同じフェードで出す（動きを減らす設定では動かさない） */
  reveal?: boolean
}

/**
 * 興味関心のチップ（E1 2章。375px で2行に折り返し、横スクロールにしない）。選んだものは緑の輪とチェック。
 * 旗 graph=on のときだけ出す（呼ぶ側の SearchList）。おすすめを出さない変種（recommend=off）では、
 * 既定のチップは全科目の一覧へ戻るチップにする。チップを選ぶとキーワード検索の結果は閉じる。
 */
export default function InterestChips({ selected, reveal = false }: InterestChipsProps) {
  const { dept, track } = useNavi()
  const flags = useFlags()
  const { log } = useResearchLog()
  const navigate = useNavigate()

  const choose = (id: string, label: string) => {
    if (id !== 'default') {
      track({ type: 'dir', dirId: id })
      log('interest_select', { interest_id: id, label })
    }
    setKeywordQuery('')
    navigate(listHref(id))
  }

  return (
    <div className={reveal ? 'chips is-back' : 'chips'} role="group" aria-label="興味関心">
      {dept.interests.map((d) => {
        const on = d.id === selected
        const label = d.targets.length === 0 && flags.recommend === 'off' ? 'すべての科目' : d.label
        return (
          <button key={d.id} className="chip" type="button" aria-pressed={on} onClick={() => choose(d.id, label)}>
            {on && <Icon name="check" small />}
            {label}
          </button>
        )
      })}
    </div>
  )
}
