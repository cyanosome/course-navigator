/**
 * これは画面モック用の架空の見本データ（fixture）です。本物の AI の回答ではありません。
 *
 * 偽のアダプタ（ask.ts の createFakeAskAdapter）が返す McpAgentRunResult。
 * 質問の例は UX 仕様（docs/frontend/ux-spec.md）S2-B の「環境問題に関わる仕事に興味がある」。
 * 本文の書式は backend/src/agent/prompts/compose_answer.md の「科目名 [コード]」の見出しに合わせた。
 * 確認できなかった科目名1件（unverified_codes）は、W5-3 の「確認できなかった科目名が1件あります」を出すため。
 */
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
