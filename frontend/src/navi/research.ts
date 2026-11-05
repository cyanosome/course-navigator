/**
 * 研究のログ（ab-variants.md 7 章、api-contract.md 3.5）の口。
 * 画面は useResearchLog().log(種類, payload) を呼ぶだけにする。調査のセッションが無いときは何も記録しない
 * （トークンの無いアクセスは記録しない。計画 4.2）。
 * いまは何もしない版。セッションの開始・seq・まとめて送る・sendBeacon・送り直しは後の単位（W4）で入れる。
 */
import { createContext, useContext } from 'react'
import type { ClientEventType, EventPayload } from './apiTypes'

/** result_click の「どの一覧か」 */
export type ListSource = 'search' | 'recommend' | 'interest' | 'ask' | 'group' | 'similar'

/** shortlist_add・shortlist_remove の「どこから」 */
export type ShortlistFrom = ListSource | 'detail' | 'timetable' | 'undo' | 'unknown'

export interface ResearchLog {
  /** 調査のセッション中か */
  active: boolean
  /** イベントを1つ記録する。セッションが無ければ何もしない */
  log: (type: ClientEventType, payload?: EventPayload) => void
}

/** 調査でないときの口（何も記録しない） */
export const NOOP_RESEARCH_LOG: ResearchLog = {
  active: false,
  log: () => {},
}

export const ResearchLogContext = createContext<ResearchLog>(NOOP_RESEARCH_LOG)

export function useResearchLog(): ResearchLog {
  return useContext(ResearchLogContext)
}
