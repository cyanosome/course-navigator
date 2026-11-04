import type { ReactNode } from 'react'
import { PC_QUERY, useMediaQuery } from '../../navi/hooks'

interface PageFrameProps {
  children: ReactNode
}

/** メニューから行く画面（W7・W8）と調査の画面（W9・W10）の本文の枠。PC は中央に 640px で置き、その中だけ流す */
export default function PageFrame({ children }: PageFrameProps) {
  // 学科が決まる前（W7）にも使うので、共有の状態（useNavi）は使わない
  const isPc = useMediaQuery(PC_QUERY)
  const page = <main className="page">{children}</main>
  return isPc ? <div className="pc-page">{page}</div> : page
}
