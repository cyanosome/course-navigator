import { useNavigate } from 'react-router-dom'
import { PC_QUERY, useMediaQuery } from '../../navi/hooks'
import type { Department } from '../../navi/types'
import Glyph from './Glyph'

interface DepartmentScreenProps {
  departments: Department[]
  onChoose: (id: string) => void
}

/**
 * 学科えらび（W7）。学科なしのリンクで開いたときと、見出しの学科名から来る。
 * 学科がまだ決まっていないときにも出すので、共有の状態（useNavi）を使わない。
 */
export default function DepartmentScreen({ departments, onChoose }: DepartmentScreenProps) {
  const navigate = useNavigate()
  const isPc = useMediaQuery(PC_QUERY)
  return (
    <main className={isPc ? 'p-page page' : 'm-main page'}>
      <h1>学科を選んでください</h1>
      <p className="note">（データがある学科だけを出しています）</p>
      <ul className="dept-list">
        {departments.map((d) => (
          <li key={d.id}>
            <a
              href={`/navi?d=${encodeURIComponent(d.id)}`}
              onClick={(e) => {
                e.preventDefault()
                onChoose(d.id)
                navigate('/navi')
              }}
            >
              <span>
                <span className="note">
                  {d.university} {d.faculty}
                </span>
                <br />
                <span className="body-s">{d.name}</span>
              </span>
              <Glyph name="next" />
            </a>
          </li>
        ))}
      </ul>
      <p className="note route-note">一覧に無い学科は、まだデータがありません。</p>
    </main>
  )
}
