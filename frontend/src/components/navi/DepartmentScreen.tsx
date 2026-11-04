import { useNavigate } from 'react-router-dom'
import type { Department } from '../../navi/types'
import Icon from './Icon'
import PageFrame from './PageFrame'

interface DepartmentScreenProps {
  departments: Department[]
  onChoose: (id: string) => void
}

/**
 * 学科えらび（W7）。学科なしのリンクで開いたときと、メニューの「学科を変える」から来る。
 * 学科がまだ決まっていないときにも出すので、共有の状態（useNavi）を使わない。
 */
export default function DepartmentScreen({ departments, onChoose }: DepartmentScreenProps) {
  const navigate = useNavigate()
  return (
    <PageFrame>
      <h1 className="title">学科を選んでください</h1>
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
                <span className="sub">
                  {d.university} {d.faculty}
                </span>
                {d.name}
              </span>
              <Icon name="next" />
            </a>
          </li>
        ))}
      </ul>
      <p className="foot">一覧に無い学科は、まだデータがありません。</p>
    </PageFrame>
  )
}
