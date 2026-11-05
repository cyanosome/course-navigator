/**
 * 調査（/navi/s/<トークン>）の文と質問票の設定。文や項目を差し替えるときは、このファイルだけを直す。
 * - draft: true の文は〈仮〉。出どころの文が手元に無いか、まだ決まっていない。画面にも〈仮〉と出るので、確定したら外す。
 * - 質問票は2組を定義し、ACTIVE_QUESTIONNAIRE_SET で選ぶ（どちらにするかは Ibuki に確認中。2026-11-05）。
 *   ibuki_sus: Ibuki の評価の PDF（10/30）の SUS 10項目＋Q11・Q12＋自由記述を、画面（ブロック）ごとに。
 *   plan_seq_ueq: 計画 4.1 の SEQ と自信（課題ごと）、UEQ-S（画面ごと）、最後に画面1/2 の二択と理由。
 *   Q11・Q12・Q13・自由記述の文は「Ibuki の評価 PDF の要点」ノートの文（問いの形を言い切りにした）。それ以外は〈仮〉。
 */

interface ItemBase {
  id: string
  required: boolean
  draft: boolean
}

/** 段階で答える（1〜points） */
export interface LikertItem extends ItemBase {
  kind: 'likert'
  text: string
  points: number
  low: string
  high: string
}

/** 反対の語の組（UEQ-S。−3〜+3 の7段階） */
export interface PairItem extends ItemBase {
  kind: 'pair'
  left: string
  right: string
}

export interface ChoiceItem extends ItemBase {
  kind: 'choice'
  text: string
  options: readonly { value: string; label: string }[]
}

export interface TextItem extends ItemBase {
  kind: 'text'
  text: string
}

export type QuestionItem = LikertItem | PairItem | ChoiceItem | TextItem

/** 1つの尺度（ログの questionnaire_submit は尺度ごとに1件） */
export interface Questionnaire {
  id: string
  /** ログに残す尺度の名前 */
  scale: string
  /** 尺度の前に出す1文（無ければ null） */
  intro: string | null
  items: readonly QuestionItem[]
}

export interface QuestionnaireSet {
  id: QuestionnaireSetId
  /** 課題ごと（練習の課題では出さない） */
  task: readonly Questionnaire[]
  /** 画面（ブロック）ごと（練習では出さない） */
  block: readonly Questionnaire[]
  /** 全部の画面のあと */
  final: readonly Questionnaire[]
}

export type QuestionnaireSetId = 'ibuki_sus' | 'plan_seq_ueq'

/** ログに残す質問票の版（項目の文を変えたら上げる） */
export const QUESTIONNAIRE_VERSION = '2026-11-05-draft'

const AGREE_5 = { points: 5, low: '全くそう思わない', high: 'とてもそう思う' } as const

/** SUS（10項目）。日本語訳 SUS rev1 の文が手元に無いので、文は〈仮〉（評価対象は「このアプリ」） */
const SUS_TEXTS = [
  'このアプリを、これからもよく使いたい',
  'このアプリは、必要以上に複雑だった',
  'このアプリは、使いやすかった',
  'このアプリを使うには、詳しい人の助けが要る',
  'このアプリの機能は、よくまとまっていた',
  'このアプリには、ちぐはぐなところが多かった',
  'たいていの人は、このアプリの使い方をすぐ覚えると思う',
  'このアプリは、とても使いにくかった',
  'このアプリを、自信を持って使えた',
  'このアプリを使い始める前に、多くのことを覚える必要があった',
] as const

const SUS: Questionnaire = {
  id: 'sus',
  scale: 'SUS',
  intro: 'いま使った画面について、あてはまるものを選んでください。',
  items: SUS_TEXTS.map((text, i): LikertItem => ({ kind: 'likert', id: `sus${i + 1}`, text, ...AGREE_5, required: true, draft: true })),
}

/** Q11・Q12（Ibuki の PDF の独自項目。検証済みの尺度ではない）と任意の自由記述。ペルソナの形にするなら Q11 の言い換えが要る（要点ノート 6章） */
const IBUKI_FIT: Questionnaire = {
  id: 'ibuki_q11_q12',
  scale: 'Q11-Q12',
  intro: null,
  items: [
    { kind: 'likert', id: 'q11', text: '見つけた科目は、探していた内容に合っていた', ...AGREE_5, required: true, draft: false },
    { kind: 'likert', id: 'q12', text: '判断に要る情報は十分だった', ...AGREE_5, required: true, draft: false },
    { kind: 'text', id: 'free', text: '困った点、分かりにくかった点、足りない情報（任意）', required: false, draft: false },
  ],
}

/** Q13 は推薦の理由を画面に出す場合だけの候補（今の用紙に無い）。使うなら IBUKI_FIT の items に足す */
export const IBUKI_Q13: LikertItem = {
  kind: 'likert',
  id: 'q13',
  text: '示された科目が候補になった理由を理解できた',
  ...AGREE_5,
  required: true,
  draft: false,
}

const SEQ: Questionnaire = {
  id: 'seq',
  scale: 'SEQ',
  intro: null,
  items: [
    {
      kind: 'likert',
      id: 'seq',
      text: 'この課題は、難しかったですか、易しかったですか',
      points: 7,
      low: 'とても難しい',
      high: 'とても易しい',
      required: true,
      draft: true,
    },
  ],
}

const CONFIDENCE: Questionnaire = {
  id: 'confidence',
  scale: '自信',
  intro: null,
  items: [
    {
      kind: 'likert',
      id: 'confidence',
      text: 'いまの答えに、どのくらい自信がありますか',
      points: 7,
      low: '全く自信がない',
      high: 'とても自信がある',
      required: true,
      draft: true,
    },
  ],
}

/** UEQ-S の8組（実用 1〜4、快楽 5〜8）。日本語版 UEQ の語が手元に無いので〈仮〉 */
const UEQ_S_PAIRS = [
  ['邪魔になる', '役に立つ'],
  ['複雑', '簡単'],
  ['効率が悪い', '効率がよい'],
  ['分かりにくい', '分かりやすい'],
  ['退屈', 'おもしろい'],
  ['興味をひかない', '興味をひく'],
  ['ありきたり', '独創的'],
  ['古くさい', '新しい'],
] as const

const UEQ_S: Questionnaire = {
  id: 'ueq_s',
  scale: 'UEQ-S',
  intro: 'いま使った画面は、左と右のどちらに近いですか。',
  items: UEQ_S_PAIRS.map(([left, right], i): PairItem => ({ kind: 'pair', id: `ueq${i + 1}`, left, right, required: true, draft: true })),
}

const PREFERENCE: Questionnaire = {
  id: 'preference',
  scale: '二択',
  intro: null,
  items: [
    {
      kind: 'choice',
      id: 'prefer',
      text: '使うなら、画面1と画面2のどちらがよいですか',
      options: [
        { value: '1', label: '画面1' },
        { value: '2', label: '画面2' },
      ],
      required: true,
      draft: true,
    },
    { kind: 'text', id: 'reason', text: '選んだ理由', required: false, draft: true },
  ],
}

export const QUESTIONNAIRE_SETS: Record<QuestionnaireSetId, QuestionnaireSet> = {
  // ログの questionnaire_submit は尺度ごとに1件: ibuki_sus はブロックごとに2件（SUS、Q11・Q12＋自由記述）、
  // plan_seq_ueq はブロックごとに5件（課題ごとに SEQ と自信を2課題分、UEQ-S を1つ）と最後に二択1件
  ibuki_sus: { id: 'ibuki_sus', task: [], block: [SUS, IBUKI_FIT], final: [] },
  plan_seq_ueq: { id: 'plan_seq_ueq', task: [SEQ, CONFIDENCE], block: [UEQ_S], final: [PREFERENCE] },
}

/** いまの調査で使う質問票の組 */
export const ACTIVE_QUESTIONNAIRE_SET: QuestionnaireSetId = 'plan_seq_ueq'

/* ---------- 同意（計画 4.2、Ibuki の PDF の②: 任意・途中でやめられる・取得する情報・ログとの連結・保存・問い合わせ先） ---------- */

export interface ConsentSection {
  heading: string
  body: string
}

export interface ConsentText {
  /** ログ（consent_recorded）に残る版。study の --consent-version と同じ値にする。文が確定したら v1 に上げる */
  version: string
  draft: boolean
  title: string
  sections: readonly ConsentSection[]
  formSerialLabel: string
}

export const CONSENT: ConsentText = {
  version: 'v0-draft',
  draft: true,
  title: '研究への協力のお願い',
  sections: [
    { heading: '目的', body: '履修を選ぶアプリの使いやすさと、探し方の違いを調べる研究です。' },
    { heading: 'すること', body: '画面を2つ使って、課題を解きます。そのあと短い質問に答え、最後に少し話を聞かせてください。全部で40分ほどです。' },
    { heading: '参加は自由です', body: '参加しなくても、途中でやめても、不利益はありません。やめたいときは研究者に言ってください。' },
    {
      heading: '記録すること',
      body: 'アプリの操作（押したところ、検索した言葉、開いた科目、時刻）と、質問への答えを記録します。名前、学籍番号、実際の履修の記録は集めません。',
    },
    {
      heading: '記録と名前の結びつき',
      body: '記録は参加の番号で整理します。番号と名前の対応は紙の同意書にだけ書き、研究者が保管します。',
    },
    {
      heading: '保存',
      body: '記録は研究者の手元に保存し、2027年3月31日に消します。論文には人数や割合だけを載せ、あなたと分かる形では出しません。',
    },
    { heading: '問い合わせ先', body: '研究者の名前と連絡先' },
  ],
  formSerialLabel: '同意書の番号（研究者が書きます）',
}

/* ---------- 課題（ペルソナの文と課題の文。サーバーの BlockPlan.task_ids と同じ ID） ---------- */

export interface TaskTextAnswer {
  /** task_submit の payload の欄の名前（課題 a は reason、課題 b は grading） */
  id: string
  label: string
}

export interface TaskDef {
  /** 「あなたは〇〇な1年生です」（その人になったつもりで探してもらう） */
  persona: string
  prompt: string
  /** 候補から選ぶ科目の数 */
  picks: number
  /** 文で答える欄（無ければ null） */
  text: TaskTextAnswer | null
  draft: boolean
}

const REASON: TaskTextAnswer = { id: 'reason', label: '選んだ理由' }
const GRADING: TaskTextAnswer = { id: 'grading', label: '成績のつけ方' }

export const TASKS: Record<string, TaskDef> = {
  practice: {
    persona: 'あなたは、この学科の1年生です。',
    prompt: '練習です。気になった科目を1つ候補に入れて、答えてください。',
    picks: 1,
    text: null,
    draft: true,
  },
  'P1-a': {
    persona: 'あなたは、3年で材料やエネルギーの分野に進みたいと考えている1年生です。',
    prompt: '1年の春に取れて、月曜に授業が無い科目を2つ選んでください。選んだ理由も書いてください。',
    picks: 2,
    text: REASON,
    draft: true,
  },
  'P1-b': {
    persona: 'あなたは、環境の測り方に関心がある1年生です。',
    prompt: '授業で「分析」を扱う2年の科目を1つ探して、成績のつけ方を答えてください。',
    picks: 1,
    text: GRADING,
    draft: true,
  },
  'P2-a': {
    persona: 'あなたは、3年で有機化学や触媒の分野に進みたいと考えている1年生です。',
    prompt: '1年の春に取れて、金曜に授業が無い科目を2つ選んでください。選んだ理由も書いてください。',
    picks: 2,
    text: REASON,
    draft: true,
  },
  'P2-b': {
    persona: 'あなたは、プログラミングに関心がある1年生です。',
    prompt: '授業で「データ」を扱う2年の科目を1つ探して、成績のつけ方を答えてください。',
    picks: 1,
    text: GRADING,
    draft: true,
  },
}

/** 参加者には条件を伏せ、ブロックの順で「画面1／画面2」とだけ呼ぶ（計画 4.1） */
export function blockLabel(block: number): string {
  return block === 0 ? '練習' : `画面${block}`
}

/** 練習のブロック（質問票を出さない） */
export function isPracticeBlock(block: number): boolean {
  return block === 0
}

/** 〈仮〉の印 */
export const DRAFT_MARK = '〈仮〉'
