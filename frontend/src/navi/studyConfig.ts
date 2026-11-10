/**
 * 調査（/navi/s/<トークン>）の文と質問票の設定。文や項目を差し替えるときは、このファイルだけを直す。
 * - draft: true の文は〈仮〉。出どころの文が手元に無いか、まだ決まっていない。画面にも〈仮〉と出るので、確定したら外す。
 * - 質問票は2組を定義し、ACTIVE_QUESTIONNAIRE_SET で選ぶ。Study 1（事前登録 2026-11-07 の 4.5）は ibuki_sus。
 *   ibuki_sus: Ibuki の評価の PDF（10/30）の SUS 10項目＋Q11・Q12＋自由記述を、画面（ブロック）ごとに。最後に画面1/2 の二択と理由。
 *   Q11 はペルソナの形に言い換えた文（事前登録 4.5）。同意の後、練習の前に事前の質問（学年・学部・前に見たか。事前登録 2.5）。
 *   plan_seq_ueq: 計画 4.1 の SEQ と自信（課題ごと）、UEQ-S（画面ごと）、最後に画面1/2 の二択と理由。
 *   Q11・Q12・Q13・自由記述の文は「Ibuki の評価 PDF の要点」ノートの文（問いの形を言い切りにした）。
 *   ibuki_sus で出るそれ以外の文（SUS・事前の質問・同意・練習の課題・守ること・ブロック2の案内）は、2026-11-10 にいまの文で確定した。
 *   〈仮〉が残るのは、Study 1 で使わない plan_seq_ueq の SEQ・自信・UEQ-S。
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
  /** 同意の後、最初のブロック（練習）の前に1回 */
  pre: readonly Questionnaire[]
  /** 課題ごと（練習の課題では出さない） */
  task: readonly Questionnaire[]
  /** 画面（ブロック）ごと（練習では出さない） */
  block: readonly Questionnaire[]
  /** 全部の画面のあと */
  final: readonly Questionnaire[]
}

export type QuestionnaireSetId = 'ibuki_sus' | 'plan_seq_ueq'

/** ログに残す質問票の版（項目の文を変えたら上げる） */
export const QUESTIONNAIRE_VERSION = '2026-11-10'

const AGREE_5 = { points: 5, low: '全くそう思わない', high: 'とてもそう思う' } as const

/** SUS（10項目）。日本語訳 SUS rev1 の文は手元に無く、この文で確定した（2026-11-10。評価対象は「このアプリ」） */
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
  items: SUS_TEXTS.map((text, i): LikertItem => ({ kind: 'likert', id: `sus${i + 1}`, text, ...AGREE_5, required: true, draft: false })),
}

/**
 * Q11・Q12（Ibuki の PDF の独自項目。検証済みの尺度ではない）と任意の自由記述。Q11 はペルソナの形に言い換えた
 * （事前登録 4.5。元の文は「見つけた科目は、探していた内容に合っていた」）
 */
const IBUKI_FIT: Questionnaire = {
  id: 'ibuki_q11_q12',
  scale: 'Q11-Q12',
  intro: null,
  items: [
    { kind: 'likert', id: 'q11', text: 'できたプランは、カードの人の希望に合っていた', ...AGREE_5, required: true, draft: false },
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
      draft: false,
    },
    { kind: 'text', id: 'reason', text: '選んだ理由', required: false, draft: false },
  ],
}

/**
 * 事前の質問（事前登録 2.5。学部は 5.5 の E6〈環境都市工学部の外の学生〉を分けるため、自学部かそれ以外の2つ）。
 * 学年の選択肢は事前登録に無く、この選択肢で確定した（2026-11-10）。ログは questionnaire_submit（scale は「事前の質問」、scope は pre、block は null）
 */
const BACKGROUND: Questionnaire = {
  id: 'background',
  scale: '事前の質問',
  intro: null,
  items: [
    {
      kind: 'choice',
      id: 'grade',
      text: '学年',
      options: [
        { value: '1', label: '1年' },
        { value: '2', label: '2年' },
        { value: '3', label: '3年' },
        { value: '4', label: '4年' },
        { value: 'other', label: 'それ以外' },
      ],
      required: true,
      draft: false,
    },
    {
      kind: 'choice',
      id: 'faculty',
      text: '学部',
      options: [
        { value: 'own', label: '環境都市工学部' },
        { value: 'other', label: 'それ以外' },
      ],
      required: true,
      draft: false,
    },
    {
      kind: 'choice',
      id: 'seen_before',
      text: 'このアプリを前に見たことがありますか',
      options: [
        { value: 'yes', label: 'ある' },
        { value: 'no', label: 'ない' },
      ],
      required: true,
      draft: false,
    },
  ],
}

export const QUESTIONNAIRE_SETS: Record<QuestionnaireSetId, QuestionnaireSet> = {
  // ログの questionnaire_submit は尺度ごとに1件: ibuki_sus は同意の後に事前の質問1件、ブロックごとに2件（SUS、Q11・Q12＋
  // 自由記述）、最後に二択1件。plan_seq_ueq はブロックごとに5件（課題ごとに SEQ と自信を2課題分、UEQ-S を1つ）と最後に二択1件
  ibuki_sus: { id: 'ibuki_sus', pre: [BACKGROUND], task: [], block: [SUS, IBUKI_FIT], final: [PREFERENCE] },
  plan_seq_ueq: { id: 'plan_seq_ueq', pre: [], task: [SEQ, CONFIDENCE], block: [UEQ_S], final: [PREFERENCE] },
}

/** いまの調査で使う質問票の組 */
export const ACTIVE_QUESTIONNAIRE_SET: QuestionnaireSetId = 'ibuki_sus'

/* ---------- 同意（計画 4.2、Ibuki の PDF の②: 任意・途中でやめられる・取得する情報・ログとの連結・保存・問い合わせ先） ---------- */

export interface ConsentSection {
  heading: string
  body: string
}

export interface ConsentText {
  /** ログ（consent_recorded）に残る版。study の --consent-version と同じ値にする（変えると同意を記録できない） */
  version: string
  draft: boolean
  title: string
  sections: readonly ConsentSection[]
  formSerialLabel: string
}

export const CONSENT: ConsentText = {
  version: 'v1-diag-ab-202611',
  draft: false,
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
    { heading: '問い合わせ先', body: '研究者の連絡先は、紙の同意書に書いてあります。' },
  ],
  formSerialLabel: '同意書の番号（研究者が書きます）',
}

/* ---------- 課題（ペルソナのカードと課題の文。サーバーの BlockPlan.task_ids と同じ ID） ---------- */

export interface TaskTextAnswer {
  /** task_submit の payload の欄の名前（課題 a は reason、課題 b は grading） */
  id: string
  label: string
}

/** 科目を候補から選んで答える課題（前の調査の形。今の TASKS には無い） */
export interface PickTaskDef {
  kind: 'pick'
  /** 「あなたは〇〇な1年生です」（その人になったつもりで探してもらう） */
  persona: string
  prompt: string
  /** 候補から選ぶ科目の数 */
  picks: number
  /** 文で答える欄（無ければ null） */
  text: TaskTextAnswer | null
  draft: boolean
}

/** カードの裏の「守ること」 */
export interface CardRules {
  items: readonly string[]
  /** 学期ごとの、入れておく系統図の科目 */
  keep: readonly { term: string; names: string }[]
  draft: boolean
}

/** ペルソナのカード（事前登録 study1 の 3.2） */
export interface PersonaCard {
  /** カードの名前（例 A さん） */
  name: string
  intro: string
  traits: readonly string[]
  /** 条件（出す前に全部を満たす） */
  conditions: readonly string[]
  /** 守ること（カードの裏。練習のカードには無い） */
  rules: CardRules | null
  draft: boolean
}

/**
 * 診断の課題（事前登録 study1 の 3.1）。diagnose（課題 a）: 診断に答えてプランを出す。プランが出たら画面が task_submit を
 * 記録し、同じ画面のまま次の課題に続ける。fix（課題 b・練習）: プランを直して［これで出す］で出す
 */
export interface PlanTaskDef {
  kind: 'diagnose' | 'fix'
  card: PersonaCard
  prompt: string
  draft: boolean
}

export type TaskDef = PickTaskDef | PlanTaskDef

/** カードの条件の見出しと、カードの下に添える1文（事前登録 3.1・3.2: アプリで確かめてから出す、目安10分） */
export const CARD_TEXT = {
  conditionsTitle: '条件（出す前に全部を満たしてください）',
  rulesTitle: '守ること',
  note: 'アプリで確かめてから出してください（目安10分）',
} as const

/** 守ること（両セット共通。事前登録 3.1 の K5・K6。カードの裏の文は事前登録に無く、この文で確定した。2026-11-10） */
const RULES: CardRules = {
  items: ['下の科目を、1年春・1年秋とも全部入れておく（同じ名前の別のクラスへ移すのはよい）', '同じ学期の同じ曜限に2つ入れない'],
  keep: [
    {
      term: '1年春',
      names:
        '化学工学量論及び演習、入門エネルギー環境学、物理を学ぶ（力学１）、基礎からの情報処理、線形代数１、情報処理演習、化学を学ぶ（基礎化学）、フレッシュマンゼミナール',
    },
    { term: '1年秋', names: 'プロセス量論及び演習、無機化学、線形代数２、入門化学結合論、化学実験、物理学実験' },
  ],
  draft: false,
}

const CARD_A: PersonaCard = {
  name: 'A さん',
  intro: 'あなたは、エネルギー環境・化学工学科の1年生の A さんです。1年春から3年秋までの履修のプランを作ります。',
  traits: [
    '電池や新しい材料でエネルギーを扱うことに興味があります',
    '実験で手を動かす授業が好きです',
    '高校の数学に少し不安があります',
    '専門のほかに、天気・災害・宇宙・生き物の授業をのぞいてみたいです',
    '月曜は一日アルバイトがあります',
  ],
  conditions: [
    '3年春・3年秋で、材料・エネルギー系の科目を4つすべて入れる',
    '1年春・1年秋とも、月曜には授業を入れない',
    '1年春・1年秋とも、1学期の単位を16以上18以下にする',
    '先輩に言われたので、1年秋に「物理を学ぶ（電磁気学１）」を入れる（クラスはどれでもよい）',
  ],
  rules: RULES,
  draft: false,
}

const CARD_B: PersonaCard = {
  name: 'B さん',
  intro: 'あなたは、エネルギー環境・化学工学科の1年生の B さんです。1年春から3年秋までの履修のプランを作ります。',
  traits: [
    '薬や樹脂のもとになる物質を、反応でつくることに興味があります',
    '話し合いや発表をする授業が好きです',
    '高校の化学に少し不安があります',
    '専門のほかに、歴史・文化・芸術の授業をのぞいてみたいです',
    '火曜の3限から5限は、毎週通院があります',
  ],
  conditions: [
    '3年春・3年秋で、有機・触媒系の科目を3つすべて入れる',
    '1年春・1年秋とも、火曜の3限・4限・5限には授業を入れない',
    '1年春・1年秋とも、1学期の単位を16以上18以下にする',
    '先輩に言われたので、1年秋に「基礎からの数学２」を入れる',
  ],
  rules: RULES,
  draft: false,
}

const CARD_C: PersonaCard = {
  name: 'C さん',
  intro:
    '工場の装置や生産の流れを設計することに興味があり、計算やプログラムで考える授業が好きです。不安な科目は特にありません。データ・AI・統計の授業をのぞいてみたいです。',
  traits: [],
  conditions: ['1年春の木曜2限は空ける（部活のミーティング）', '1年春は20単位以下にする'],
  rules: null,
  draft: false,
}

/** 課題 a・b の文（事前登録 3.1 の文を、参加者に向けた形にした） */
const PROMPT_A = 'カードの人になって診断に答え、プランを出してください。'
const PROMPT_B = '出たプランを、カードの条件をすべて満たすように直して出してください。答え直してもかまいません。'

export const TASKS: Record<string, TaskDef> = {
  // 練習は1つの課題で、診断からプランを出して直して出すまで（事前登録に文が無く、この文で確定した。2026-11-10）
  practice: {
    kind: 'fix',
    card: CARD_C,
    prompt: '練習です。カードの人になって診断に答えてプランを出し、条件を満たすように直して出してください。',
    draft: false,
  },
  'P1-a': { kind: 'diagnose', card: CARD_A, prompt: PROMPT_A, draft: false },
  'P1-b': { kind: 'fix', card: CARD_A, prompt: PROMPT_B, draft: false },
  'P2-a': { kind: 'diagnose', card: CARD_B, prompt: PROMPT_A, draft: false },
  'P2-b': { kind: 'fix', card: CARD_B, prompt: PROMPT_B, draft: false },
}

/**
 * ブロック2の初めの画面の案内（事前登録 2.5。V31 を2番目に受ける人は AI の欄を練習しないので、その手当て）。
 * 文は両条件で同じにし、AI の欄がある画面（assistant=on）のときだけ ai の段落を足す。文は事前登録に無く、この文で確定した（2026-11-10）
 */
export const BLOCK_GUIDE = {
  common:
    'この画面でも、カードの人になって診断に答えてプランを出し、条件に合うように直して出します。単位・時間割・チェックは、右の列（スマホは上の帯）で確かめられます。',
  ai: 'この画面には AI の欄があります。プランの下の「AIに直しを頼む」で直したいことを書いて送ると、外す科目と入れる科目の案が出ます。案は1行ずつ選んで入れられます。さがすの欄からも AI に聞けます。',
  draft: false,
} as const

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
