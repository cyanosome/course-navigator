/**
 * 調査の段階の進め方（同意 → ブロック → 課題 → 質問票 → 終了）。状態は research.ts に持ち、サーバーは R1〜R7。
 * 段階: consent → blockIntro → taskIntro → task（画面で探す）→ taskQuestions → … → blockQuestions → blockEnd（R5）
 *       → 次のブロックの blockIntro … → finalQuestions → finishing（session_end と R7）→ done
 * 練習のブロック（0）では質問票を出さない。
 */
import { FORM_SERIAL_PATTERN } from './apiTypes'
import type { BlockStartOut, EventPayload, JsonValue, SessionOut } from './apiTypes'
import {
  currentTaskId,
  deviceInfo,
  flushEvents,
  getStudy,
  logApiError,
  logEvent,
  researchTransport,
  setStudy,
  StudyError,
  syncSeq,
  transportFor,
} from './research'
import type { StudyPhase, StudyState } from './research'
import { clearAppState } from './storage'
import { ACTIVE_QUESTIONNAIRE_SET, CONSENT, isPracticeBlock, QUESTIONNAIRE_SETS, QUESTIONNAIRE_VERSION } from './studyConfig'
import type { QuestionnaireSet } from './studyConfig'

export type QuestionScope = 'task' | 'block' | 'final'

/** 質問票の答え（尺度の ID → 項目の ID → 値。答えていない任意の項目は null） */
export type QuestionnaireAnswers = Record<string, Record<string, number | string | null>>

export function activeQuestionnaires(): QuestionnaireSet {
  return QUESTIONNAIRE_SETS[ACTIVE_QUESTIONNAIRE_SET]
}

function need(): StudyState {
  const study = getStudy()
  if (study === null) throw new StudyError(null, '調査のセッションがありません')
  return study
}

function blockNumbers(session: SessionOut): number[] {
  return session.blocks.map((b) => b.block).sort((a, b) => a - b)
}

function firstBlock(session: SessionOut): number {
  const first = blockNumbers(session)[0]
  if (first === undefined) throw new StudyError(null, 'ブロックの計画が空です')
  return first
}

/** サーバーの状態だけから段階を決める（このタブに前の状態が無いとき） */
function phaseFromServer(session: SessionOut): StudyPhase {
  if (!session.consent_recorded) return { kind: 'consent' }
  // ブロックの途中で状態を失ったときは、そのブロックの最初の課題からやり直す（どこまで答えたかはサーバーのログにある）
  if (session.current_block !== null && session.variant !== null) return { kind: 'taskIntro', block: session.current_block, taskIndex: 0 }
  const next = blockNumbers(session).find((b) => !session.completed_blocks.includes(b))
  if (next !== undefined) return { kind: 'blockIntro', block: next }
  // 全部のブロックを終えている。最後の質問票が無ければ R7 だけ（クライアントの session_end が無いので、サーバーが書く）
  return activeQuestionnaires().final.length > 0 ? { kind: 'finalQuestions' } : { kind: 'finishing' }
}

/**
 * 調査の入口を開いたとき。同じ入口の状態がこのタブにあれば R2 で確かめて続け、無ければトークンで R1 を呼ぶ
 * （同じトークンの2回目は、サーバーが前のセッションを返す）。
 */
export async function openStudy(token: string, gatePath: string): Promise<void> {
  const stored = getStudy()
  if (stored !== null && stored.gatePath === gatePath) {
    if (stored.phase.kind === 'done' || stored.phase.kind === 'declined') return
    try {
      const transport = await researchTransport(stored.transport)
      const session = await transport.currentSession(stored.session.session_id)
      syncSeq(session.session_id, session.last_seq)
      setStudy({ ...need(), session })
      return
    } catch (err) {
      if (!(err instanceof StudyError) || (err.status !== 401 && err.status !== 404)) {
        // 届かないだけなら、手元の状態で続ける（送れなかったイベントは列に残る）
        console.error('調査のセッションを確かめられませんでした。このタブの状態で続けます', err)
        return
      }
      console.error('このタブの調査のセッションがサーバーにありません。カードの URL から始め直します', err)
    }
  }
  const kind = transportFor(token)
  const transport = await researchTransport(kind)
  const session = await transport.startSession(token)
  if (stored === null || stored.session.session_id !== session.session_id) clearAppState()
  syncSeq(session.session_id, session.last_seq)
  const current = session.current_block === null ? null : (session.blocks.find((b) => b.block === session.current_block) ?? null)
  setStudy({
    session,
    gatePath,
    transport: kind,
    phase: phaseFromServer(session),
    plan: current,
    variant: session.variant,
    appliedBlock: null,
  })
  if (session.consent_recorded) {
    // 途中から始め直した（このタブに前の状態が無い）。seq は 1 から振り直すので、分析のために印を残す
    logEvent('client_error', { kind: 'resumed_without_local_state', current_block: session.current_block })
  }
}

/** 同意書の番号の形（英数字とハイフン、1〜16 文字）。合わなければ R3 を呼ばない */
export function isFormSerial(text: string): boolean {
  return FORM_SERIAL_PATTERN.test(text.trim())
}

/** 同意（R3）。同意しなければ記録だけして先へ進めない */
export async function recordConsent(agreed: boolean, formSerial: string): Promise<void> {
  const study = need()
  const transport = await researchTransport(study.transport)
  try {
    await transport.recordConsent(study.session.session_id, {
      consent_version: CONSENT.version,
      form_serial: formSerial.trim(),
      agreed,
    })
  } catch (err) {
    logApiError('consent', err)
    throw err
  }
  const now = need()
  if (!agreed) {
    setStudy({ ...now, phase: { kind: 'declined' } })
    return
  }
  setStudy({
    ...now,
    session: { ...now.session, consent_recorded: true, consent_version: CONSENT.version },
    phase: { kind: 'blockIntro', block: firstBlock(now.session) },
  })
}

/** ブロックの開始（R4）。旗と課題の計画を受け取る */
export async function startBlock(): Promise<void> {
  const study = need()
  if (study.phase.kind !== 'blockIntro') return
  const { block } = study.phase
  const transport = await researchTransport(study.transport)
  let out: BlockStartOut
  try {
    out = await transport.startBlock(study.session.session_id, block)
  } catch (err) {
    logApiError('block_start', err)
    throw err
  }
  const now = need()
  setStudy({
    ...now,
    session: { ...now.session, current_block: block, variant: out.variant },
    plan: out.plan,
    variant: out.variant,
    phase: out.plan.task_ids.length === 0 ? afterTasks(block) : { kind: 'taskIntro', block, taskIndex: 0 },
  })
}

/** 課題を始める（入口から画面へ）。課題ごとに画面の状態を消し、task_start を記録する */
export function startTask(): void {
  const study = need()
  if (study.phase.kind !== 'taskIntro') return
  const { block, taskIndex } = study.phase
  clearAppState()
  const next: StudyState = { ...study, phase: { kind: 'task', block, taskIndex } }
  setStudy(next)
  logEvent('task_start', { block, task_index: taskIndex }, currentTaskId(next))
}

/** 課題の答え（task_submit）。選んだ科目と、文の答え */
export interface TaskAnswer {
  selected: string[]
  /** 欄の名前（reason・grading）→ 文 */
  texts: Record<string, string>
}

export function submitTask(answer: TaskAnswer): void {
  const study = need()
  if (study.phase.kind !== 'task') return
  const { block, taskIndex } = study.phase
  const texts: Record<string, JsonValue> = answer.texts
  logEvent('task_submit', { block, task_index: taskIndex, selected: answer.selected, ...texts }, currentTaskId(study))
  const asks = !isPracticeBlock(block) && activeQuestionnaires().task.length > 0
  setStudy({ ...study, phase: asks ? { kind: 'taskQuestions', block, taskIndex } : afterTask(study, block, taskIndex) })
}

function afterTask(study: StudyState, block: number, taskIndex: number): StudyPhase {
  const count = study.plan?.task_ids.length ?? 0
  if (taskIndex + 1 < count) return { kind: 'taskIntro', block, taskIndex: taskIndex + 1 }
  return afterTasks(block)
}

function afterTasks(block: number): StudyPhase {
  if (!isPracticeBlock(block) && activeQuestionnaires().block.length > 0) return { kind: 'blockQuestions', block }
  return { kind: 'blockEnd', block }
}

function enterFinishing(study: StudyState): StudyState {
  const next: StudyState = { ...study, phase: { kind: 'finishing' }, plan: null, variant: null }
  setStudy(next)
  logEvent('session_end', { reason: 'completed', ...deviceInfo() }, null)
  return next
}

/** 質問票の答え（尺度ごとに questionnaire_submit を1件） */
export function submitQuestionnaire(scope: QuestionScope, answers: QuestionnaireAnswers): void {
  const study = need()
  const { phase } = study
  const expected = scope === 'task' ? 'taskQuestions' : scope === 'block' ? 'blockQuestions' : 'finalQuestions'
  if (phase.kind !== expected) return
  const block = 'block' in phase ? phase.block : null
  const taskId = scope === 'task' ? currentTaskId(study) : null
  const set = activeQuestionnaires()
  for (const q of set[scope]) {
    const payload: EventPayload = {
      set: set.id,
      questionnaire: q.id,
      scale: q.scale,
      scope,
      block,
      version: QUESTIONNAIRE_VERSION,
      values: answers[q.id] ?? {},
    }
    logEvent('questionnaire_submit', payload, taskId)
  }
  if (phase.kind === 'taskQuestions') setStudy({ ...study, phase: afterTask(study, phase.block, phase.taskIndex) })
  else if (phase.kind === 'blockQuestions') setStudy({ ...study, phase: { kind: 'blockEnd', block: phase.block } })
  else enterFinishing(study)
}

/** 同じ送信を重ねない（開発の StrictMode で効果が2回走る、押し直しなど） */
let ending: Promise<void> | null = null
let finishing: Promise<void> | null = null

/**
 * ブロックの終了（R5）と次の段階。列に残ったイベント（そのブロックの最後の task_submit・質問票）を送り切ってから
 * R5 を呼ぶ（サーバーは受け取った時点のブロックをイベントに付けるので、R5 の後に届くとブロックの外の扱いになる）
 */
export function endBlock(): Promise<void> {
  if (ending === null) {
    ending = endBlockOnce().finally(() => {
      ending = null
    })
  }
  return ending
}

async function endBlockOnce(): Promise<void> {
  const study = need()
  if (study.phase.kind !== 'blockEnd') return
  const { block } = study.phase
  const sent = await flushEvents()
  if (!sent) throw new StudyError(null, '記録を送り切れませんでした')
  const transport = await researchTransport(study.transport)
  try {
    await transport.endBlock(study.session.session_id, block)
  } catch (err) {
    logApiError('block_end', err)
    throw err
  }
  const now = need()
  const next = blockNumbers(now.session).find((b) => b > block)
  const cleared: StudyState = { ...now, session: { ...now.session, variant: null }, plan: null, variant: null }
  if (next !== undefined) {
    setStudy({ ...cleared, phase: { kind: 'blockIntro', block: next } })
    return
  }
  if (activeQuestionnaires().final.length > 0) {
    setStudy({ ...cleared, phase: { kind: 'finalQuestions' } })
    return
  }
  enterFinishing(cleared)
}

/** 終わり: 残りのイベントを送り切ってから R7（サーバーがクッキーを消すので、その後は送れない） */
export function finishStudy(): Promise<void> {
  if (finishing === null) {
    finishing = finishOnce().finally(() => {
      finishing = null
    })
  }
  return finishing
}

async function finishOnce(): Promise<void> {
  const study = need()
  if (study.phase.kind !== 'finishing') return
  const sent = await flushEvents()
  if (!sent) throw new StudyError(null, '記録を送り切れませんでした')
  const transport = await researchTransport(study.transport)
  await transport.endSession(study.session.session_id)
  setStudy({ ...need(), phase: { kind: 'done' } })
}

/** 画面に出す失敗の文（api-contract.md 5.3 の書き分け） */
export function studyErrorText(err: unknown): string {
  if (err instanceof StudyError) {
    if (err.status === null) return 'サーバーにつながりません。研究者に知らせてください。'
    if (err.status === 401 || err.status === 404) return 'このカードの URL は使えません。研究者に知らせてください。'
    if (err.status === 409) return 'いまは進めません（サーバーの準備か順番が合っていません）。研究者に知らせてください。'
    if (err.status === 503) return 'データベースにつながりません。研究者に知らせてください。'
    if (err.status === 504) return '時間内に返りませんでした。研究者に知らせてください。'
    return 'サーバーのエラーです。研究者に知らせてください。'
  }
  return '思わぬエラーが起きました。研究者に知らせてください。'
}
