import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { formatDuration } from '../../navi/hooks'
import { useNavi } from '../../navi/state'
import PageFrame from './PageFrame'

/** 調査の ID が無いリンクで開いたときの仮の値（モック用） */
const FALLBACK_SURVEY_ID = 'KU-2611'

/**
 * 調査の開始（W9。UX 仕様 8.1、C18・C19・C21）。
 * 前の候補や記録が端末に残っていれば、件数を出して消してよいかを確かめる。始めたあとは W9 を履歴に残さない。
 */
export default function StudyStartScreen() {
  const { shortlist, study, ask, startStudy } = useNavi()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const surveyId = params.get('s') ?? study?.surveyId ?? FALLBACK_SURVEY_ID
  /** 確かめる文（［始める］を押した時点の件数と使った時間）。null なら確認を出していない */
  const [leftoverSummary, setLeftoverSummary] = useState<string | null>(null)
  const leftover = shortlist.length > 0 || study !== null || ask !== null

  const begin = (mode: 'fresh' | 'continue') => {
    startStudy(surveyId, mode)
    navigate('/navi', { replace: true })
  }

  const onStart = () => {
    if (!leftover) {
      begin('fresh')
      return
    }
    const usedMs = study === null ? null : (study.endedAt ?? Date.now()) - study.startedAt
    setLeftoverSummary(
      [`候補 ${shortlist.length}件`, usedMs === null ? null : `使った時間 ${formatDuration(usedMs)}`]
        .filter((x) => x !== null)
        .join('、'),
    )
  }

  return (
    <PageFrame>
      <h1 className="title">研究のための試用版です</h1>
      <section className="sec">
        <p className="lead">数分間、ふだん履修を選ぶつもりで使ってください。</p>
        <p className="text">使いにくいところを見つけるのが目的です。うまく使えなくても、あなたのせいではありません。</p>
        <p className="text">名前や学籍番号は入力しないでください。</p>
        <p className="text">終わったら、画面の上の［使い終わった］を押してください。</p>
      </section>
      {leftoverSummary === null ? (
        <div className="page-acts">
          <button className="primary" type="button" onClick={onStart}>
            始める
          </button>
        </div>
      ) : (
        <section className="sec" aria-labelledby="study-confirm-h">
          <h2 className="sec-label" id="study-confirm-h">
            この端末に前の記録が残っています（{leftoverSummary}）
          </h2>
          <p className="text">次の人として始めるときは、消してから始めます。消すと元に戻せません。</p>
          <div className="page-acts">
            <button className="primary" type="button" onClick={() => begin('fresh')}>
              消して始める
            </button>
            <button className="text-btn" type="button" onClick={() => begin('continue')}>
              前の続きから使う
            </button>
          </div>
        </section>
      )}
    </PageFrame>
  )
}
