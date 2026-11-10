/**
 * これは画面モック用の架空の見本データ（fixture）です。本物の AI の回答ではありません。
 *
 * 偽のアダプタ（ask.ts の createFakeAskAdapter）が返す McpAgentRunResult。
 * 質問の例は UX 仕様（docs/frontend/ux-spec.md）S2-B の「環境問題に関わる仕事に興味がある」。
 * 本文の書式は backend/src/agent/prompts/compose_answer.md の「科目名 [コード]」の見出しに合わせた。
 * 確認できなかった科目名1件（unverified_codes）は、W5-3 の「確認できなかった科目名が1件あります」を出すため。
 */
import type { PlanContextIn, PlanSuggestion, PlanSuggestions } from './apiTypes'
import { FIXTURE_DEPARTMENTS } from './fixtureDepartment'
import type { McpAgentRunResult } from './types'

export const FIXTURE_ASK_RESULT: McpAgentRunResult = {
  route: 'mcp',
  answer: [
    '環境問題に関わる仕事に近い科目を、系統図とシラバスから3つ挙げます（モックの回答です）。',
    '',
    '大気・水環境化学工学 [EC3101]',
    '大気や水の汚染を化学工学で扱う科目で、環境問題に関わる仕事に近い内容です（仮）。授業計画には水質の指標や排水処理のプロセスの回があります。',
    '',
    '入門エネルギー環境学 [EC1102]',
    'エネルギーと環境の問題を1年で広く見渡す科目で、学科の科目とのつながりを知る入口になります（仮）。',
    '',
    '化学プラント設計 [EC3102]',
    '排水や排ガスを処理する装置の設計を扱う科目で、環境の対策を形にする仕事に近い内容です（仮）。',
    '',
    '環境リスク評価論 [EC3999]',
    '環境への影響を見積もる考え方を扱う科目です（仮）。',
    '',
    '学修アドバイス: 1年の入門エネルギー環境学で全体を見渡してから、3年の2科目に進む順が考えられます。科目の中身はシラバスの原文で確かめてください。',
  ].join('\n'),
  cited_codes: ['EC3101', 'EC1102', 'EC3102', 'EC3999'],
  sources: [
    {
      code: 'EC3101',
      title: '大気・水環境化学工学',
      instructor: null,
      schedule: '春学期 木曜3限',
      credits: 2,
      excerpt: '（仮）大気と水の汚れがどう生まれ、どう取り除くかを、物質の収支と装置の設計の考え方で学ぶ。',
      origin: 'fixture:courses',
      url: null,
    },
    {
      code: 'EC1102',
      title: '入門エネルギー環境学',
      instructor: null,
      schedule: '春学期 金曜1限',
      credits: 2,
      excerpt: '（仮）エネルギーと環境の問題を広く見渡し、学科で学ぶ科目とのつながりを知る。',
      origin: 'fixture:courses',
      url: null,
    },
    {
      code: 'EC3102',
      title: '化学プラント設計',
      instructor: null,
      schedule: '秋学期 月曜4限',
      credits: 2,
      excerpt: '',
      origin: 'fixture:courses',
      url: null,
    },
  ],
  unverified_codes: ['EC3999'],
  notes: ['引用された科目コード EC3999 は、データベースで確認できませんでした（モックの注意）。'],
  tool_calls: [],
  node_sequence: [],
  model: 'mock',
  latency_ms: 0,
}

/** 移す組の見本: プランの科目のうち、見本の学科に同じ学期の同じ名前の別クラスがある最初のもの（外す案と入れる案の組） */
function fixtureMove(ctx: PlanContextIn, inPlan: ReadonlySet<string>): { remove: PlanSuggestion; add: PlanSuggestion } | null {
  const courses = FIXTURE_DEPARTMENTS.flatMap((d) => d.courses)
  for (const t of ctx.terms) {
    for (const id of t.syllabus_ids) {
      const from = courses.find((c) => c.code === id)
      if (from === undefined) continue
      const to = courses.find(
        (c) => c.code !== id && c.name === from.name && !inPlan.has(c.code) && (c.term === t.term || c.term === '通年'),
      )
      if (to === undefined) continue
      const where = (slots: string[]) => (slots.length === 0 ? '曜限なし' : slots.join('・'))
      return {
        remove: { syllabus_id: from.code, title: from.name, reason: `${where(from.slots)}のクラスを外す（見本）` },
        add: { syllabus_id: to.code, title: to.name, reason: `${where(to.slots)}の別クラスへ移す（見本）` },
      }
    }
  }
  return null
}

/**
 * プランの微修正の見本の提案（A1 の plan_suggestions の形。照合の後のつもり）。出典のうちプランに無い科目を「足す」、
 * プランの最後の科目を「外す」にし、DB に無い EC3999 と候補に無い EC3998 は照合で外したことにする。
 * プランの最初の科目は系統図の科目として、外す案を照合で外したことにする（locked）。
 * 見本の学科に同じ名前の別クラスがあるプランの科目は、そのクラスへ「移す」組（外す＋足す）にする
 */
export function fixturePlanSuggestions(ctx: PlanContextIn): PlanSuggestions {
  const codes = ctx.terms.flatMap((t) => t.syllabus_ids)
  const inPlan = new Set(codes)
  const move = fixtureMove(ctx, inPlan)
  const moved = move?.remove.syllabus_id
  const first = codes.at(0)
  const last = codes.at(-1)
  // 履修済み（plan_context の completed）の科目を足す案は、照合で外したことにする（completed）
  const completed = new Set(ctx.completed ?? [])
  const sources = FIXTURE_ASK_RESULT.sources.filter((s) => !inPlan.has(s.code))
  return {
    add: [
      ...sources
        .filter((s) => !completed.has(s.code))
        .map((s) => ({ syllabus_id: s.code, title: s.title, reason: '環境の対策に近い内容です（見本）' })),
      ...(move === null ? [] : [move.add]),
    ],
    remove: [
      ...(last === undefined || last === moved ? [] : [{ syllabus_id: last, title: null, reason: '頼みから遠い科目です（見本）' }]),
      ...(move === null ? [] : [move.remove]),
    ],
    dropped: [
      { action: 'add', syllabus_id: 'EC3999', reason: 'not_in_db' },
      { action: 'add', syllabus_id: 'EC3998', reason: 'not_candidate' },
      ...sources.filter((s) => completed.has(s.code)).map((s) => ({ action: 'add' as const, syllabus_id: s.code, reason: 'completed' as const })),
      ...(first === undefined || first === last || first === moved
        ? []
        : [{ action: 'remove' as const, syllabus_id: first, reason: 'locked' as const }]),
    ],
  }
}
