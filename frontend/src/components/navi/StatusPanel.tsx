import { useEffect, useId, useRef, useState } from 'react'
import '../../navi/diagnose.css'
import '../../navi/study.css'
import { useResearchLog } from '../../navi/research'
import { useNavi } from '../../navi/state'
import { CHECK_DAYS, CHECK_PERIODS, checkpointLabel, checkpointPayload, resultsPayload } from '../../navi/status'
import type { CheckDay, CheckKind, CheckResult, CheckStatus, CourseStatus } from '../../navi/status'
import { termLabel } from '../../navi/timetable'
import { useCheckpoints, useCourseStatus } from '../../navi/useStatus'
import type { NewCheckpoint, StatusTarget } from '../../navi/useStatus'
import { useFlags } from '../../navi/variant'
import Accordion from './Accordion'
import Icon from './Icon'

interface StatusPanelProps {
  target: StatusTarget
  heading: string
  /** 外側の余白（時間割の段は block、ページの中は sec） */
  frame: 'block' | 'sec'
}

const STATUS_LABEL: Record<CheckStatus, string> = { met: '満たす', unmet: '満たさない', unknown: '判定できない' }
/** 原因の科目の名前は3つまで出し、残りは数にする */
const NAMES_SHOWN = 3

/**
 * 履修状況（合計と学期ごとの単位）とチェックの一覧（仮の置き方。見た目はデザインのコンペで差し替える）。
 * 判定は navi/status.ts の純関数、一覧と足し外しは navi/useStatus.ts。どの変種でも同じものを出す。
 * 開いたときに1回、status_open（チェックの一覧と結果）を記録する。
 */
export default function StatusPanel({ target, heading, frame }: StatusPanelProps) {
  const { status, results } = useCourseStatus(target)
  const { checkpoints, remove } = useCheckpoints()
  const { dept } = useNavi()
  const { log } = useResearchLog()
  const headingId = useId()

  const logged = useRef(false)
  useEffect(() => {
    if (logged.current) return
    logged.current = true
    log('status_open', {
      target: target.kind,
      checkpoints: checkpoints.map(checkpointPayload),
      results: resultsPayload(results),
      total_credits: status.totalCredits,
    })
  }, [checkpoints, log, results, status.totalCredits, target.kind])

  const met = results.filter((r) => r.status === 'met').length
  return (
    <section className={`${frame} chk`} aria-labelledby={headingId}>
      <h2 className="block-h" id={headingId}>
        {heading}
        <span className="chk-count">
          {met}/{results.length}
          <span className="vh">を満たす</span>
        </span>
      </h2>
      <p className="chk-total">
        合計 <span className="num">{status.totalCredits}</span>単位
        {status.terms.length > 0 && `（${status.terms.map((t) => `${termLabel(t.term)} ${t.credits}`).join('・')}）`}
        {status.unknownCredits > 0 && ` 単位の分からない科目 ${status.unknownCredits}`}
      </p>
      <ul className="chk-list">
        {results.map((r) => {
          const cp = checkpoints.find((c) => c.id === r.id)
          const label = cp === undefined ? r.id : checkpointLabel(cp, dept)
          return (
            <li key={r.id} className={`chk-item is-${r.status}`}>
              <span className="chk-mark" aria-hidden="true">
                {r.status === 'met' ? <Icon name="check" small /> : r.status === 'unmet' ? <Icon name="warn" small /> : '？'}
              </span>
              <span className="chk-body">
                <span>
                  {label}
                  <span className="vh">: {STATUS_LABEL[r.status]}</span>
                </span>
                <span className="chk-reason">
                  {r.status === 'unknown' && '判定できません。'}
                  {r.reason}
                  {courseNames(r, status)}
                </span>
              </span>
              <button className="text-btn" type="button" onClick={() => remove(r.id)} aria-label={`「${label}」を外す`}>
                外す
              </button>
            </li>
          )
        })}
      </ul>
      <Accordion label="チェックを足す" hint="">
        <CheckpointForm />
      </Accordion>
    </section>
  )
}

/** 原因の科目の名前（理由の文に名前が入っていないチェックだけ） */
function courseNames(r: CheckResult, status: CourseStatus): string {
  if (r.codes.length === 0 || r.kind === 'prerequisite' || r.kind === 'required') return ''
  const names = r.codes.map((code) => status.courses.find((c) => c.code === code)?.name ?? code)
  const shown = names.slice(0, NAMES_SHOWN).join('、')
  return names.length > NAMES_SHOWN ? `（${shown}ほか${names.length - NAMES_SHOWN}）` : `（${shown}）`
}

const KIND_LABEL: Record<CheckKind, string> = {
  credits: '単位の合計',
  free_slot: '空ける曜日',
  group_count: 'まとまりの科目の数',
  prerequisite: '前のまとまりの抜け',
  no_overlap: '曜限の重なり',
  required: '必修',
}

const DEFAULT_GROUP_MIN = 2

function toNumber(text: string): number | null {
  if (text.trim() === '') return null
  const n = Number(text)
  return Number.isFinite(n) && n >= 0 ? n : null
}

/** チェックを足す欄（数を決めるものは数を入れる。数の無いものは、もう一覧にあれば足せない） */
function CheckpointForm() {
  const { checkpoints, add } = useCheckpoints()
  const { dept } = useNavi()
  const flags = useFlags()
  const formId = useId()
  const kinds = (Object.keys(KIND_LABEL) as CheckKind[]).filter((k) => k !== 'required' || flags.requirements === 'shown')
  const [kind, setKind] = useState<CheckKind>('credits')
  const [per, setPer] = useState<'term' | 'total'>('term')
  const [min, setMin] = useState('')
  const [max, setMax] = useState('')
  const [day, setDay] = useState<CheckDay>('月')
  const [period, setPeriod] = useState('')
  const [group, setGroup] = useState(dept.frames[0]?.id ?? '')
  const [groupMin, setGroupMin] = useState(String(DEFAULT_GROUP_MIN))

  const draft = ((): NewCheckpoint | null => {
    switch (kind) {
      case 'credits': {
        const lo = toNumber(min)
        const hi = toNumber(max)
        if (lo === null && hi === null) return null
        if (lo !== null && hi !== null && lo > hi) return null
        return { kind, per, min: lo, max: hi }
      }
      case 'free_slot':
        return { kind, days: [day], periods: period === '' ? [] : [Number(period)] }
      case 'group_count': {
        const n = toNumber(groupMin)
        return group === '' || n === null || n < 1 ? null : { kind, groups: [group], min: Math.floor(n) }
      }
      default:
        return checkpoints.some((c) => c.kind === kind) ? null : { kind }
    }
  })()

  const id = (name: string) => `${formId}-${name}`
  return (
    <form
      className="chk-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (draft !== null) add(draft)
      }}
    >
      <label className="q-field" htmlFor={id('kind')}>
        種類
      </label>
      <select className="q-input" id={id('kind')} value={kind} onChange={(e) => setKind(e.target.value as CheckKind)}>
        {kinds.map((k) => (
          <option key={k} value={k}>
            {KIND_LABEL[k]}
          </option>
        ))}
      </select>
      {kind === 'credits' && (
        <div className="chk-fields">
          <label className="q-field">
            どこで
            <select className="q-input" value={per} onChange={(e) => setPer(e.target.value === 'total' ? 'total' : 'term')}>
              <option value="term">各学期</option>
              <option value="total">全体</option>
            </select>
          </label>
          <label className="q-field">
            以上
            <input className="q-input" inputMode="numeric" value={min} onChange={(e) => setMin(e.target.value)} />
          </label>
          <label className="q-field">
            まで
            <input className="q-input" inputMode="numeric" value={max} onChange={(e) => setMax(e.target.value)} />
          </label>
        </div>
      )}
      {kind === 'free_slot' && (
        <div className="chk-fields">
          <label className="q-field">
            曜日
            <select className="q-input" value={day} onChange={(e) => setDay(e.target.value as CheckDay)}>
              {CHECK_DAYS.map((d) => (
                <option key={d} value={d}>
                  {d}曜
                </option>
              ))}
            </select>
          </label>
          <label className="q-field">
            時限
            <select className="q-input" value={period} onChange={(e) => setPeriod(e.target.value)}>
              <option value="">1日</option>
              {CHECK_PERIODS.map((p) => (
                <option key={p} value={String(p)}>
                  {p}限
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {kind === 'group_count' && (
        <div className="chk-fields">
          <label className="q-field">
            まとまり
            <select className="q-input" value={group} onChange={(e) => setGroup(e.target.value)}>
              {dept.frames.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.year}年 {f.name}
                </option>
              ))}
            </select>
          </label>
          <label className="q-field">
            いくつ以上
            <input className="q-input" inputMode="numeric" value={groupMin} onChange={(e) => setGroupMin(e.target.value)} />
          </label>
        </div>
      )}
      <div className="page-acts">
        <button className="primary" type="submit" disabled={draft === null}>
          足す
        </button>
      </div>
    </form>
  )
}
