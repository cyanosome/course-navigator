/**
 * これは画面モック用の架空の見本データ（fixture）です。本物の学科データではありません。
 *
 * - 科目名・枠の名前は UX 仕様（docs/frontend/ux-spec.md）6.2 のワイヤーフレームと、Claude Design に渡した
 *   依頼文の「例のデータ」から取った。そこに無い科目・枠・線（例: 数理・情報の基礎、分析・有機化学系）は、
 *   UX 仕様 3.7 の例（無機・基礎化学系は3方向、化学工学・エネルギー・基礎数理系は2方向に届く）と
 *   ワイヤーフレームの並びが成り立つように、このモックで仮に置いたもの。
 * - 科目コード・曜限・単位・授業計画・概要の文・枠の科目数はすべて仮。シラバスの本文は入れていない
 *   （学科データの同梱と著作権の方針は未決 U2）。
 * - 本物の学科1つ分は 21枠・70科目・25本の線（UX 仕様 要点4）。ここは画面に要る分だけの 13枠・41科目・16本。
 */
import type { Course, Department, PlanItem, Term } from './types'

interface CourseSeed {
  code: string
  name: string
  frameId: string
  year: number
  term: Term
  slot: string
  credits: number
  plan?: PlanItem[]
  planTotal?: number
  summary?: string
}

const DEFAULT_PLAN_TOTAL = 15

function course(seed: CourseSeed): Course {
  return {
    ...seed,
    plan: seed.plan ?? [],
    planTotal: seed.planTotal ?? DEFAULT_PLAN_TOTAL,
    summary: seed.summary ?? '',
  }
}

export const FIXTURE_DEPARTMENT: Department = {
  id: 'enechem',
  university: '関西大学',
  faculty: '環境都市工学部',
  name: 'エネルギー環境・化学工学科',
  dataVersion: 'fixture-1103',
  syllabusYear: 2026,
  frames: [
    { id: 'g1a', year: 1, name: '化学工学・エネルギー・基礎数理系', common: false },
    { id: 'g1b', year: 1, name: '無機・基礎化学系', common: false },
    { id: 'g1c', year: 1, name: '数理・情報の基礎（共通教養）', common: true },
    { id: 'g2a', year: 2, name: 'ユニットオペレーション・反応工学・数理系', common: false },
    { id: 'g2b', year: 2, name: '物理化学系', common: false },
    { id: 'g2c', year: 2, name: '分析・有機化学系', common: false },
    { id: 'g2d', year: 2, name: '情報処理・統計系', common: false },
    { id: 'g3a', year: 3, name: '応用化学工学系', common: false },
    { id: 'g3b', year: 3, name: '材料・エネルギー系', common: false },
    { id: 'g3c', year: 3, name: '有機・触媒系', common: false },
    { id: 'g3d', year: 3, name: '安全・倫理・特別講義系', common: false },
    { id: 'g4a', year: 4, name: '特別研究I', common: false },
    { id: 'g4b', year: 4, name: '法規・知財・マネジメント', common: false },
  ],
  edges: [
    { from: 'g1a', to: 'g2a' },
    { from: 'g1a', to: 'g2b' },
    { from: 'g1b', to: 'g2b' },
    { from: 'g1b', to: 'g2c' },
    { from: 'g1c', to: 'g2c' },
    { from: 'g1c', to: 'g2d' },
    { from: 'g2a', to: 'g3a' },
    { from: 'g2b', to: 'g3a' },
    { from: 'g2b', to: 'g3b' },
    { from: 'g2c', to: 'g3b' },
    { from: 'g2c', to: 'g3c' },
    { from: 'g2d', to: 'g3d' },
    { from: 'g3a', to: 'g4a' },
    { from: 'g3b', to: 'g4a' },
    { from: 'g3c', to: 'g4a' },
    { from: 'g3d', to: 'g4b' },
  ],
  directions: [
    { id: 'default', label: 'まず見ておきたい', description: '系統図で多くの方向につながる枠の科目', targets: [] },
    { id: 'env', label: '環境とプロセス', description: '工場の装置や、水・空気をきれいにする仕組みを設計する', targets: ['g3a'] },
    { id: 'mat', label: '材料とエネルギー', description: '電池や新しい素材の性質を調べてつくる', targets: ['g3b'] },
    { id: 'org', label: '有機と触媒', description: '分子をつくる反応と、反応を速める触媒', targets: ['g3c'] },
    { id: 'soc', label: '技術と社会', description: '安全・倫理・法律・品質など、技術を仕事で使うときのこと', targets: ['g3d', 'g4b'] },
  ],
  courses: [
    // 1年 化学工学・エネルギー・基礎数理系
    course({
      code: 'EC1101', name: '化学工学量論及び演習', frameId: 'g1a', year: 1, term: '春', slot: '水2', credits: 2,
      plan: [
        { no: 1, title: '（仮）物質の量と単位' },
        { no: 3, title: '（仮）物質収支の立て方' },
        { no: 6, title: '（仮）反応をともなう物質収支' },
      ],
      summary: '（仮）化学のプロセスで、物質とエネルギーの出入りを数で追う考え方を、演習を通して身につける。',
    }),
    course({
      code: 'EC1102', name: '入門エネルギー環境学', frameId: 'g1a', year: 1, term: '春', slot: '金1', credits: 2,
      plan: [
        { no: 1, title: '（仮）エネルギーと環境の問題の見取り図' },
        { no: 5, title: '（仮）化石燃料と再生可能エネルギー' },
        { no: 9, title: '（仮）水と大気の汚れ' },
      ],
      summary: '（仮）エネルギーと環境の問題を広く見渡し、学科で学ぶ科目とのつながりを知る。',
    }),
    course({ code: 'EC1103', name: '化学工学概論', frameId: 'g1a', year: 1, term: '秋', slot: '水2', credits: 2 }),
    // 1年 無機・基礎化学系
    course({
      code: 'EC1201', name: '無機化学', frameId: 'g1b', year: 1, term: '春', slot: '月2', credits: 2,
      plan: [
        { no: 1, title: '（仮）原子の構造と周期表' },
        { no: 4, title: '（仮）化学結合のいろいろ' },
        { no: 8, title: '（仮）酸と塩基' },
      ],
      summary: '（仮）元素と化合物の性質を、原子の構造と結合の考え方から整理する。',
    }),
    course({ code: 'EC1202', name: '基礎有機化学', frameId: 'g1b', year: 1, term: '秋', slot: '月2', credits: 2 }),
    course({ code: 'EC1203', name: '基礎化学実験', frameId: 'g1b', year: 1, term: '秋', slot: '木3', credits: 2 }),
    // 1年 数理・情報の基礎（共通教養）
    course({
      code: 'GE1301', name: '数学を学ぶ（微分積分I・演習I）', frameId: 'g1c', year: 1, term: '春', slot: '火1', credits: 2,
      plan: [
        { no: 1, title: '（仮）関数と極限' },
        { no: 4, title: '（仮）微分の考え方' },
        { no: 9, title: '（仮）積分と面積' },
      ],
      summary: '（仮）変化の割合と積み重ねを式で扱う方法を、演習で手を動かして学ぶ。',
    }),
    course({ code: 'GE1302', name: '数学を学ぶ（線形代数I・演習I）', frameId: 'g1c', year: 1, term: '春', slot: '金2', credits: 2 }),
    course({ code: 'GE1303', name: '数学を学ぶ（微分積分II・演習II）', frameId: 'g1c', year: 1, term: '秋', slot: '火1', credits: 2 }),
    course({ code: 'GE1304', name: '数学を学ぶ（線形代数II・演習II）', frameId: 'g1c', year: 1, term: '秋', slot: '金2', credits: 2 }),
    course({ code: 'GE1305', name: '情報処理演習', frameId: 'g1c', year: 1, term: '春', slot: '水4', credits: 2 }),
    course({ code: 'GE1306', name: '物理学を学ぶ（力学）', frameId: 'g1c', year: 1, term: '春', slot: '月1', credits: 2 }),
    // 2年 ユニットオペレーション・反応工学・数理系
    course({
      code: 'EC2101', name: 'ユニットオペレーションI', frameId: 'g2a', year: 2, term: '春', slot: '火2', credits: 2,
      plan: [
        { no: 1, title: '（仮）単位操作とは何か' },
        { no: 4, title: '（仮）流れと圧力損失' },
        { no: 8, title: '（仮）熱の伝わり方と熱交換器' },
      ],
      summary: '（仮）化学工場の装置に共通する基本の操作を、流れと熱の移動から学ぶ。',
    }),
    course({ code: 'EC2102', name: 'ユニットオペレーションII', frameId: 'g2a', year: 2, term: '秋', slot: '火2', credits: 2 }),
    course({ code: 'EC2103', name: '反応工学', frameId: 'g2a', year: 2, term: '秋', slot: '木2', credits: 2 }),
    course({ code: 'EC2104', name: '移動現象論', frameId: 'g2a', year: 2, term: '秋', slot: '金3', credits: 2 }),
    course({ code: 'EC2105', name: '化学工学数学', frameId: 'g2a', year: 2, term: '秋', slot: '水1', credits: 2 }),
    // 2年 物理化学系
    course({
      code: 'EC2201', name: '物理化学I', frameId: 'g2b', year: 2, term: '春', slot: '月3', credits: 2,
      plan: [
        { no: 1, title: '（仮）気体の性質' },
        { no: 5, title: '（仮）熱力学の第一法則' },
        { no: 10, title: '（仮）化学平衡' },
      ],
      summary: '（仮）物質の状態と変化を、エネルギーの考え方で説明する方法を学ぶ。',
    }),
    course({ code: 'EC2202', name: '物理化学II', frameId: 'g2b', year: 2, term: '秋', slot: '月3', credits: 2 }),
    course({ code: 'EC2203', name: '物理化学演習', frameId: 'g2b', year: 2, term: '秋', slot: '木1', credits: 1 }),
    course({ code: 'EC2204', name: '化学熱力学', frameId: 'g2b', year: 2, term: '秋', slot: '火3', credits: 2 }),
    course({ code: 'EC2205', name: '電気化学', frameId: 'g2b', year: 2, term: '秋', slot: '金2', credits: 2 }),
    course({ code: 'EC2206', name: '量子化学', frameId: 'g2b', year: 2, term: '秋', slot: '水3', credits: 2 }),
    // 2年 分析・有機化学系
    course({ code: 'EC2301', name: '分析化学', frameId: 'g2c', year: 2, term: '春', slot: '水2', credits: 2 }),
    course({ code: 'EC2302', name: '有機化学I', frameId: 'g2c', year: 2, term: '春', slot: '木2', credits: 2 }),
    course({ code: 'EC2303', name: '有機化学II', frameId: 'g2c', year: 2, term: '秋', slot: '木2', credits: 2 }),
    // 2年 情報処理・統計系
    course({ code: 'EC2401', name: '応用統計学', frameId: 'g2d', year: 2, term: '春', slot: '金4', credits: 2 }),
    course({ code: 'EC2402', name: '情報処理応用', frameId: 'g2d', year: 2, term: '秋', slot: '金4', credits: 2 }),
    // 3年 応用化学工学系
    course({
      code: 'EC3101', name: '大気・水環境化学工学', frameId: 'g3a', year: 3, term: '春', slot: '木3', credits: 2,
      plan: [
        { no: 1, title: '（仮）大気環境と化学工学' },
        { no: 4, title: '（仮）水質の指標' },
        { no: 7, title: '（仮）排水処理のプロセス' },
      ],
      summary: '（仮）大気と水の汚れがどう生まれ、どう取り除くかを、物質の収支と装置の設計の考え方で学ぶ。',
    }),
    course({ code: 'EC3102', name: '化学プラント設計', frameId: 'g3a', year: 3, term: '秋', slot: '月4', credits: 2 }),
    course({ code: 'EC3103', name: '化学工学実験', frameId: 'g3a', year: 3, term: '秋', slot: '火3', credits: 2 }),
    course({ code: 'EC3104', name: 'プロセス制御', frameId: 'g3a', year: 3, term: '秋', slot: '水2', credits: 2 }),
    // 3年 材料・エネルギー系
    course({ code: 'EC3201', name: 'エネルギー材料工学', frameId: 'g3b', year: 3, term: '春', slot: '月3', credits: 2 }),
    course({ code: 'EC3202', name: '電池と燃料電池', frameId: 'g3b', year: 3, term: '秋', slot: '火2', credits: 2 }),
    course({ code: 'EC3203', name: '無機材料化学', frameId: 'g3b', year: 3, term: '秋', slot: '金1', credits: 2 }),
    // 3年 有機・触媒系
    course({ code: 'EC3301', name: '触媒化学', frameId: 'g3c', year: 3, term: '春', slot: '水3', credits: 2 }),
    course({ code: 'EC3302', name: '有機合成化学', frameId: 'g3c', year: 3, term: '秋', slot: '木1', credits: 2 }),
    course({ code: 'EC3303', name: '高分子化学', frameId: 'g3c', year: 3, term: '秋', slot: '月2', credits: 2 }),
    // 3年 安全・倫理・特別講義系
    course({ code: 'EC3401', name: '化学プロセス安全工学', frameId: 'g3d', year: 3, term: '春', slot: '金3', credits: 2 }),
    course({ code: 'EC3402', name: '技術者倫理', frameId: 'g3d', year: 3, term: '秋', slot: '火4', credits: 2 }),
    course({ code: 'EC3403', name: '特別講義（品質管理）', frameId: 'g3d', year: 3, term: '秋', slot: '集中', credits: 1 }),
    // 4年
    course({ code: 'EC4101', name: '特別研究I', frameId: 'g4a', year: 4, term: '通年', slot: '研究室で決める', credits: 4 }),
    course({ code: 'EC4201', name: '知的財産と技術マネジメント', frameId: 'g4b', year: 4, term: '春', slot: '水2', credits: 2 }),
    course({ code: 'EC4202', name: '化学関係法規', frameId: 'g4b', year: 4, term: '秋', slot: '木2', credits: 1 }),
  ],
}

/** データのある学科の一覧（W7）。モックでは1つだけ。 */
export const FIXTURE_DEPARTMENTS: Department[] = [FIXTURE_DEPARTMENT]

/**
 * 調査モードの設定（UX 仕様 S4 の「フロントの設定ファイル」に当たる）。
 * アンケートの URL は仮。example.com は説明用に予約されたドメインで、実在のアンケートではない。
 */
export const FIXTURE_STUDY_CONFIG = {
  appVersion: 'v0.3-mock',
  surveyUrl: 'https://example.com/survey',
  /** 事前入力の欄の名前（仮）。数だけを入れる（UX 仕様 C22） */
  prefillKeys: {
    session: 'session',
    kept: 'kept',
    keptAfterReason: 'kept_after_reason',
    detailOpened: 'detail_opened',
    originalOpened: 'original_opened',
    traversed: 'traversed',
    asked: 'asked',
  },
} as const

/** シラバス原文の URL（仮）。本物の detail_url は学科データ D2 から来る（UX 仕様 9.2）。 */
export const FIXTURE_SYLLABUS_BASE = 'https://example.com/syllabus/'
