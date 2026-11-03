import { useId } from 'react'
import { useNavigate } from 'react-router-dom'
import { useNavi } from '../../navi/state'

interface DirectionChipsProps {
  /** 選択中の方向（既定は default） */
  selected: string
  /** 既定（まず見ておきたい）を出さない（W6-4 の言い直し） */
  withoutDefault?: boolean
  /** 見出しを出す（W1・W2・W11） */
  labelled?: boolean
}

/** 方向のチップ（UX 仕様 3.8。5個を折り返して並べ、横スクロールにしない） */
export default function DirectionChips({ selected, withoutDefault = false, labelled = true }: DirectionChipsProps) {
  const { dept, track } = useNavi()
  const navigate = useNavigate()
  const labelId = useId()
  const directions = dept.directions.filter((d) => !withoutDefault || d.targets.length > 0)

  const choose = (id: string) => {
    if (id !== 'default') track({ type: 'dir', dirId: id })
    navigate(id === 'default' ? '/navi' : `/navi?dir=${encodeURIComponent(id)}`)
  }

  return (
    <>
      {labelled && (
        <h2 className="label" id={labelId}>
          方向（3年の科目のまとまり）
        </h2>
      )}
      <div className="chips" role="group" aria-labelledby={labelled ? labelId : undefined} aria-label={labelled ? undefined : '方向'}>
        {directions.map((d) => (
          <button
            key={d.id}
            className="chip"
            type="button"
            aria-pressed={d.id === selected}
            onClick={() => choose(d.id)}
          >
            {d.label}
          </button>
        ))}
      </div>
    </>
  )
}
