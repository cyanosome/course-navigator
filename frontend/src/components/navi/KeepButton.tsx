import { useNavi } from '../../navi/state'
import Glyph from './Glyph'

interface KeepButtonProps {
  code: string
  /** 読み上げで、どの科目のボタンかを伝える */
  name: string
}

/**
 * [候補に入れる]。押すとその場で「候補に入れた」に変わり、もう一度押すと外れる（UX 仕様 C04）。
 * 元に戻すの表示は NaviApp がまとめて出す。
 */
export default function KeepButton({ code, name }: KeepButtonProps) {
  const { isKept, toggleKeep } = useNavi()
  const kept = isKept(code)
  return (
    <button
      className="btn btn--keep"
      type="button"
      aria-pressed={kept}
      aria-label={`${name}を${kept ? '候補から外す（いまは候補に入れた）' : '候補に入れる'}`}
      onClick={() => toggleKeep(code)}
    >
      <Glyph name={kept ? 'check' : 'plus'} />
      <span>{kept ? '候補に入れた' : '候補に入れる'}</span>
    </button>
  )
}
