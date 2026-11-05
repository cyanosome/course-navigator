/**
 * 「自分の言葉で探す」（W5）の送信と、回答の読み取り。
 *
 * 本物は POST /api/assist/ask（askAdapter.ts の createHttpAskAdapter）。開発ビルドで ?wait= を付けたときだけ、
 * 待ち時間を真似た偽のアダプタ（createFakeAskAdapter）で動く。見本の回答は本番の束に入れないよう、使うときに読み込む。
 */
import type { Department, McpAgentRunResult } from './types'

export interface AskAdapter {
  /** 送る文（composeQuestion で作ったもの）を受けて、回答を返す。signal で中断できる */
  ask(question: string, signal: AbortSignal): Promise<McpAgentRunResult>
}

/** 偽のアダプタの待ち方。URL の ?wait= で選ぶ（例 /navi?d=enechem&wait=long） */
export type FakeWaitMode = 'short' | 'long' | 'timeout' | 'error' | 'empty'

export const FAKE_WAIT_MODES: readonly FakeWaitMode[] = ['short', 'long', 'timeout', 'error', 'empty']

const SHORT_WAIT_MS = 4_000
/** 実測の上の端（1問 53〜93 秒。UX 仕様 T3）に近い値 */
const LONG_WAIT_MS = 95_000
const ERROR_WAIT_MS = 3_000

export function isFakeWaitMode(value: string | null): value is FakeWaitMode {
  return value !== null && (FAKE_WAIT_MODES as readonly string[]).includes(value)
}

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('中断しました', 'AbortError'))
      return
    }
    const timer = setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('中断しました', 'AbortError'))
      },
      { once: true },
    )
  })
}

export function createFakeAskAdapter(mode: FakeWaitMode): AskAdapter {
  return {
    async ask(_question, signal) {
      const started = Date.now()
      if (mode === 'timeout') {
        // 返らない。呼び出し側の上限（3分）で W6-3 になる
        await new Promise<never>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new DOMException('中断しました', 'AbortError')), {
            once: true,
          })
        })
      }
      if (mode === 'error') {
        await delay(ERROR_WAIT_MS, signal)
        throw new TypeError('Failed to fetch（モック: サーバーにつながらない状態を真似ています）')
      }
      await delay(mode === 'long' ? LONG_WAIT_MS : SHORT_WAIT_MS, signal)
      const { FIXTURE_ASK_RESULT } = await import('./fixtureAsk')
      const latency = Date.now() - started
      if (mode === 'empty') {
        return {
          ...FIXTURE_ASK_RESULT,
          answer: 'この学科の科目の中に、ご質問に合う科目を見つけられませんでした。',
          cited_codes: [],
          sources: [],
          unverified_codes: [],
          notes: [],
          latency_ms: latency,
        }
      }
      return { ...FIXTURE_ASK_RESULT, latency_ms: latency }
    },
  }
}

/** 範囲外の言葉（バックエンドの DECLINE_KEYWORDS と同じ語。UX 仕様 9.4 F4） */
const OUT_OF_SCOPE_WORDS = ['難しい', '簡単', '楽', '評判', '単位が取りやすい'] as const

export function findOutOfScopeWords(text: string): string[] {
  return OUT_OF_SCOPE_WORDS.filter((w) => text.includes(w))
}

/** 自由記述に学科名と依頼の形を付けて1文にする（UX 仕様 9.4 F5。C10 のガードレールを含む） */
export function composeQuestion(dept: Department, interest: string, withGuardrail: boolean): string {
  const base =
    `${dept.university} ${dept.faculty} ${dept.name}の学生です。` +
    `次の関心に関係する、この学科の科目を、先に取るものから順に3〜5科目挙げてください。関心:『${interest}』`
  if (!withGuardrail) return base
  return `${base}。難しさや単位の取りやすさにはデータが無いので答えず、それ以外の関心に合う科目を挙げてください`
}

/**
 * 回答本文を科目ごとの見出し（科目名 [コード]）で区切り、各科目の段落の最初の文を取り出す（UX 仕様 9.4 F6）。
 * 見出しが見つからない科目は結果に入れない（呼び出し側が「AIの説明の中で触れています」にする）。
 */
export function extractReasons(answer: string): Map<string, string> {
  const reasons = new Map<string, string>()
  const lines = answer.split(/\r?\n/)
  const heading = /^\s*(?:[#*\-\s]*)?(.+?)\s*\[([A-Za-z0-9-]+)\]\s*$/
  for (let i = 0; i < lines.length; i++) {
    const m = heading.exec(lines[i] ?? '')
    if (m === null) continue
    const code = m[2]
    if (code === undefined) continue
    const body: string[] = []
    for (let j = i + 1; j < lines.length; j++) {
      const line = lines[j] ?? ''
      if (heading.test(line)) break
      if (line.trim() === '') {
        if (body.length > 0) break
        continue
      }
      body.push(line.trim())
    }
    const paragraph = body.join('')
    const firstSentence = paragraph.split('。')[0]
    if (firstSentence !== undefined && firstSentence !== '') reasons.set(code, `${firstSentence}。`)
  }
  return reasons
}
