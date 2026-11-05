import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { FIXTURE_STUDY_CONFIG } from '../../navi/fixtureStudyConfig'
import { findCourse, findInterest } from '../../navi/graph'
import { formatDuration } from '../../navi/hooks'
import { useStudy } from '../../navi/research'
import { useNavi } from '../../navi/state'
import type { StudyRecord } from '../../navi/state'
import type { Course, Department } from '../../navi/types'
import PageFrame from './PageFrame'

interface RecordRow {
  label: string
  value: string
}

function recordRows(dept: Department, study: StudyRecord, kept: Course[], device: string, usedMs: number): RecordRow[] {
  const dirs = ['おすすめ', ...study.dirs.map((id) => findInterest(dept, id)?.label ?? id)]
  const onlyDefault = study.dirs.length === 0 && study.asked === 0
  return [
    { label: '調査', value: study.surveyId },
    { label: 'アプリ', value: FIXTURE_STUDY_CONFIG.appVersion },
    { label: 'データ', value: dept.dataVersion },
    { label: '端末', value: device },
    { label: '使った時間', value: formatDuration(usedMs) },
    { label: '候補', value: kept.length === 0 ? 'なし' : kept.map((c) => `${c.name}（${c.code}）`).join('、') },
    { label: '理由を見てから候補に入れた科目', value: String(study.keptAfterReason.filter((c) => kept.some((k) => k.code === c)).length) },
    { label: '詳細を開いた科目', value: String(study.detailOpened.length) },
    { label: '原文を開いた', value: `${study.originalOpened}回` },
    { label: '前後の科目をたどった', value: `${study.traversed}回` },
    { label: '興味関心', value: dirs.join('、') },
    { label: '自分の言葉で探した', value: `${study.asked}回` },
    { label: 'おすすめだけで終えた', value: onlyDefault ? 'はい' : 'いいえ' },
  ]
}

/** アンケートの URL に、セッション番号と集計値（数だけ）を入れる。名前・自由記述の文・科目名は入れない（UX 仕様 C22） */
function surveyHref(study: StudyRecord, kept: Course[]): string {
  const k = FIXTURE_STUDY_CONFIG.prefillKeys
  const q = new URLSearchParams({
    [k.session]: study.sessionId,
    [k.kept]: String(kept.length),
    [k.keptAfterReason]: String(study.keptAfterReason.length),
    [k.detailOpened]: String(study.detailOpened.length),
    [k.originalOpened]: String(study.originalOpened),
    [k.traversed]: String(study.traversed),
    [k.asked]: String(study.asked),
  })
  return `${FIXTURE_STUDY_CONFIG.surveyUrl}?${q.toString()}`
}

/** 調査の終了（W10。UX 仕様 8.7、C17・C21・C22）。カードの URL から始めた調査のセッション中は、調査の入口の終わりへ戻す */
export default function StudyEndScreen() {
  const { dept, isPc, study, shortlist } = useNavi()
  const [copyState, setCopyState] = useState<'idle' | 'done' | 'failed'>('idle')
  const research = useStudy()
  if (research !== null) return <Navigate to={research.gatePath} replace />

  if (study === null) {
    return (
      <PageFrame>
        <h1 className="title">調査モードではありません</h1>
        <p className="text">
          調査用のリンクから開いたときだけ、記録が出ます。<Link to="/navi">使う画面に戻る</Link>
        </p>
      </PageFrame>
    )
  }

  const kept = shortlist.map((code) => findCourse(dept, code)).filter((c): c is Course => c !== undefined)
  const usedMs = (study.endedAt ?? study.startedAt) - study.startedAt
  const rows = recordRows(dept, study, kept, isPc ? 'PC 幅' : 'スマホ幅', usedMs)
  const text = [`セッション番号 ${study.sessionId}`, ...rows.map((r) => `${r.label}: ${r.value}`)].join('\n')

  const copy = () => {
    navigator.clipboard
      .writeText(text)
      .then(() => setCopyState('done'))
      .catch((err: unknown) => {
        console.error('記録をコピーできませんでした', err)
        setCopyState('failed')
      })
  }

  return (
    <PageFrame>
      <h1 className="title">使い終わりました</h1>
      <p className="lead">
        セッション番号 <span className="sid">{study.sessionId}</span>
      </p>
      <p className="text">アンケートは、この番号が入った状態で開きます。個人を特定する情報は入っていません。</p>
      <div className="page-acts">
        <a className="primary" href={surveyHref(study, kept)} target="_blank" rel="noopener noreferrer">
          アンケートを開く
        </a>
        <button className="text-btn" type="button" onClick={copy}>
          記録をコピー
        </button>
      </div>
      <p className="src" role="status">
        {copyState === 'idle' && 'アンケートに番号が入らないときは、記録をコピーして貼ってください。'}
        {copyState === 'done' && 'コピーしました。アンケートの欄に貼ってください。'}
        {copyState === 'failed' && 'コピーできませんでした。この画面の記録を書き写してください。'}
      </p>
      <div className="record">
        <dl className="kv">
          {rows.map((r) => (
            <div key={r.label} className="kv-row">
              <dt>{r.label}</dt>
              <dd>{r.value}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="foot">
        <Link to="/navi">使う画面に戻る</Link>
      </p>
    </PageFrame>
  )
}
