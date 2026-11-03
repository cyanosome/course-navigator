import { useLocation, useNavigate } from 'react-router-dom'
import Glyph from './Glyph'

/** [< 戻る]（スマホの W3・W13・W4 以外の画面。ブラウザの戻ると同じ。UX 仕様 5.2・5.4） */
export default function BackButton() {
  const navigate = useNavigate()
  const location = useLocation()
  // このアプリの中で来た画面なら1つ前へ。リンクから直接開いたときは、さがすへ
  const back = () => (location.key === 'default' ? navigate('/navi') : navigate(-1))
  return (
    <button className="btn btn--quiet back" type="button" onClick={back}>
      <Glyph name="back" />
      戻る
    </button>
  )
}
