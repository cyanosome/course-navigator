import { useNavi } from '../../navi/state'
import TimetablePanel from './TimetablePanel'

/** 時間割の画面（/navi/timetable）。スマホは W4、PC は左の段に時間割（NaviLayout）を出し、中央はマスを押すまで案内だけ（W12） */
export default function TimetableScreen() {
  const { isPc } = useNavi()
  if (isPc) return <p className="hint">表のマスか科目名を押すと、ここに科目の詳細が出ます。</p>
  return (
    <main>
      <TimetablePanel />
    </main>
  )
}
