import { useLocation, useParams, useSearchParams } from 'react-router-dom'
import { findFrame, frameLabel } from '../../navi/graph'
import { groupHref, parseOrigin, readPaneState, useNavi } from '../../navi/state'
import BackButton from './BackButton'
import GroupDetail from './GroupDetail'
import Panes from './Panes'

/** 枠の科目の画面（/navi/group/<枠ID>?from=…）。スマホは別の画面、PC は右ペイン */
export default function GroupScreen() {
  const { dept, isPc } = useNavi()
  const { frameId = '' } = useParams()
  const [params] = useSearchParams()
  const location = useLocation()
  const origin = parseOrigin(params.get('from'))
  const pane = readPaneState(location.state)
  const frame = findFrame(dept, frameId)
  const tab = pane?.tab ?? (origin.kind === 'shortlist' ? 'shortlist' : 'search')
  const trail = pane?.trail ?? [{ label: frame === undefined ? frameId : `${frameLabel(frame)}の枠`, href: groupHref(frameId, origin) }]

  if (!isPc) {
    return (
      <main className="m-main">
        <BackButton />
        <GroupDetail frameId={frameId} origin={origin} trail={[]} tab={tab} />
      </main>
    )
  }

  const rootCode = /\/navi\/course\/([^?]+)/.exec(trail[0]?.href ?? '')?.[1]
  return (
    <Panes tab={tab} currentCode={rootCode === undefined ? undefined : decodeURIComponent(rootCode)}>
      <GroupDetail frameId={frameId} origin={origin} trail={trail} tab={tab} />
    </Panes>
  )
}
