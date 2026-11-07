/**
 * これは画面モック用の架空の見本データ（fixture）です。本物の学科データではありません。
 *
 * - 科目名・まとまりの名前の一部は UX 仕様（docs/frontend/ux-spec.md）6.2 のワイヤーフレームと、
 *   画面の改訂案 E1（2026-11-04）の見本から取った。まとまりと線は、E1 の見本の並び（無機化学が3分野、
 *   物理学を学ぶ（力学）と入門エネルギー環境学が2分野、情報リテラシーが技術と社会につながる）が
 *   成り立つように、このモックで仮に置いたもの。
 * - 担当教員名・区分（必修・選択）・対象学年・曜限・単位・授業でやること・授業計画・成績のつけ方・教科書は、
 *   すべて架空の見本。実在の教員・授業とは関係ない。
 * - 他学部の科目「環境と法（法学部）」、必修の「英語I（リーディング）」、「情報リテラシー」も架空の見本。
 * - 卒業に要る単位（合計 124、区分ごとの数）と学期の上限 24 単位は架空の数。画面にも「見本の数」と書く。
 * - データが無いときの見せ方（E1 8章）を確かめるため、一部の科目は項目を欠かせてある
 *   （担当が「シラバスに記載なし」「準備中」、区分が準備中、単位が記載なし、曜限が随時・集中講義・研究室で決める、
 *   授業でやることが無く授業計画で代える、どちらも無い、原文の URL が無い、2コマの科目）。
 */
import type { Course, Department, GradCategory, Kind, TeacherInfo, Term } from './types'

/** シラバス原文の URL（仮）。example.com は説明用に予約されたドメインで、実在のページではない */
export const FIXTURE_SYLLABUS_BASE = 'https://example.com/syllabus/'

interface CourseSeed {
  code: string
  name: string
  short?: string
  frameId: string | null
  faculty?: string
  year: number
  yearRange?: string
  term: Term
  slots: string[]
  slotNote?: string
  credits: number | null
  kind: Kind | null
  grad: GradCategory | null
  /** 文字列なら担当の名前。無いときは 'none'（シラバスに記載なし）か省略（準備中） */
  teacher?: string | 'none'
  learn?: string
  summary?: string
  plan?: string[]
  grading?: string
  textbook?: string
  /** false なら原文の URL が無い */
  url?: false
}

function teacherOf(t: string | undefined): TeacherInfo {
  if (t === undefined) return { status: 'notDelivered' }
  if (t === 'none') return { status: 'notInSyllabus' }
  return { status: 'known', name: t }
}

function course(seed: CourseSeed): Course {
  return {
    code: seed.code,
    name: seed.name,
    short: seed.short ?? null,
    frameId: seed.frameId,
    faculty: seed.faculty ?? null,
    year: seed.year,
    yearRange: seed.yearRange ?? null,
    term: seed.term,
    slots: seed.slots,
    slotNote: seed.slotNote ?? null,
    credits: seed.credits,
    kind: seed.kind,
    grad: seed.grad,
    teacher: teacherOf(seed.teacher),
    learn: seed.learn ?? '',
    summary: seed.summary ?? '',
    plan: seed.plan ?? [],
    grading: seed.grading ?? null,
    textbook: seed.textbook ?? null,
    syllabusUrl: seed.url === false ? null : `${FIXTURE_SYLLABUS_BASE}${seed.code}`,
  }
}

const TEXTBOOK_HANDOUT = '指定なし（毎回資料を配る）'

export const FIXTURE_DEPARTMENT: Department = {
  id: 'enechem',
  university: '関西大学',
  faculty: '環境都市工学部',
  name: 'エネルギー環境・化学工学科',
  dataVersion: 'fixture-1104',
  syllabusYear: 2026,
  frames: [
    { id: 'g1a', year: 1, name: '化学工学・エネルギー・基礎数理系', plain: '化学工学の入門', common: false },
    { id: 'g1b', year: 1, name: '無機・基礎化学系', plain: '基礎化学', common: false },
    { id: 'g1c', year: 1, name: '数理の基礎（共通教養）', plain: '数学', common: true },
    { id: 'g1d', year: 1, name: '物理の基礎（共通教養）', plain: '物理', common: true },
    { id: 'g1e', year: 1, name: '情報の基礎（共通教養）', plain: '情報', common: true },
    { id: 'g2a', year: 2, name: 'ユニットオペレーション・反応工学・数理系', plain: '装置の科目', common: false },
    { id: 'g2b', year: 2, name: '物理化学系', plain: '物理化学', common: false },
    { id: 'g2c', year: 2, name: '分析・有機化学系', plain: '分析・有機', common: false },
    { id: 'g2d', year: 2, name: '情報処理・統計系', plain: '情報処理', common: false },
    { id: 'g3a', year: 3, name: '応用化学工学系', plain: '環境とプロセス', common: false },
    { id: 'g3b', year: 3, name: '材料・エネルギー系', plain: '材料とエネルギー', common: false },
    { id: 'g3c', year: 3, name: '有機・触媒系', plain: '有機と触媒', common: false },
    { id: 'g3d', year: 3, name: '安全・倫理・特別講義系', plain: '技術と社会', common: false },
    { id: 'g4a', year: 4, name: '特別研究I', plain: '特別研究', common: false },
    { id: 'g4b', year: 4, name: '法規・知財・マネジメント', plain: '法規と知財', common: false },
  ],
  edges: [
    { from: 'g1a', to: 'g2a' },
    { from: 'g1a', to: 'g2b' },
    { from: 'g1b', to: 'g2b' },
    { from: 'g1b', to: 'g2c' },
    { from: 'g1c', to: 'g2a' },
    { from: 'g1c', to: 'g2d' },
    { from: 'g1d', to: 'g2a' },
    { from: 'g1d', to: 'g2b' },
    { from: 'g1e', to: 'g2d' },
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
  interests: [
    { id: 'default', label: 'おすすめ', targets: [], extras: [] },
    { id: 'env', label: '環境とプロセス', targets: ['g3a'], extras: [] },
    { id: 'org', label: '有機と触媒', targets: ['g3c'], extras: [] },
    { id: 'mat', label: '材料とエネルギー', targets: ['g3b'], extras: [] },
    {
      id: 'soc',
      label: '技術と社会',
      targets: ['g3d', 'g4b'],
      extras: [{ code: 'LW1501', why: '環境の法律を学べる他学部の科目', source: 'シラバス' }],
    },
  ],
  requirements: {
    total: 124,
    termCap: 24,
    sample: true,
    needs: [
      { category: '必修', need: 40 },
      { category: '選択', need: 64 },
      { category: '教養', need: 20 },
    ],
  },
  // 並びは系統図の記載順（おすすめの並びで、つながる分野の数が同じときに使う）
  courses: [
    /* ---------- 1年春 ---------- */
    course({
      code: 'EC1201', name: '無機化学', frameId: 'g1b', year: 1, term: '春', slots: ['月2'], credits: 2,
      kind: '選択', grad: '選択', teacher: '大森 理沙',
      learn: '原子の構造、化学結合、酸と塩基',
      summary: '元素と化合物の性質を、原子の構造と結合の考え方から整理する。',
      plan: ['原子の構造と周期表', '電子の配置', 'イオン結合と共有結合', '化学結合のいろいろ', '分子の形', '結晶の構造', '酸と塩基の考え方', '酸と塩基の反応', '酸化と還元', '典型元素の化合物', '遷移元素と錯体', '金属の性質', '身近な無機材料', '演習', 'まとめと試験'],
      grading: '期末試験 70%、小テスト 30%', textbook: TEXTBOOK_HANDOUT,
    }),
    course({
      code: 'GE1306', name: '物理学を学ぶ（力学）', short: '力学', frameId: 'g1d', year: 1, term: '春', slots: ['月2'], credits: 2,
      kind: '選択', grad: '教養', teacher: '高瀬 陽介',
      learn: '運動の法則とエネルギーの保存',
      summary: '物の運動を、力とエネルギーの考え方で式に表して説明する。',
      grading: '期末試験 80%、演習の提出 20%',
    }),
    // 同じ名前の別クラス（AI の微修正の「移す」の見本。系統図には載せない）
    course({
      code: 'GE1316', name: '物理学を学ぶ（力学）', short: '力学', frameId: null, year: 1, term: '春', slots: ['木2'], credits: 2,
      kind: '選択', grad: '教養', teacher: '高瀬 陽介',
      learn: '運動の法則とエネルギーの保存',
      summary: '物の運動を、力とエネルギーの考え方で式に表して説明する（木曜のクラス）。',
    }),
    course({
      code: 'EC1102', name: '入門エネルギー環境学', short: 'エネ環', frameId: 'g1a', year: 1, term: '春', slots: ['金1'], credits: 2,
      kind: '選択', grad: '選択', teacher: '片桐 恵',
      learn: 'エネルギーと環境の問題の全体像',
      summary: 'エネルギーと環境の問題を広く見渡し、学科で学ぶ科目とのつながりを知る。',
      plan: ['エネルギーと環境の問題の見取り図', '化石燃料', '再生可能エネルギー', '水と大気の汚れ', '学科の科目とのつながり'],
    }),
    course({
      code: 'GE1307', name: '情報リテラシー', short: '情報', frameId: 'g1e', year: 1, yearRange: '1〜4年', term: '春', slots: [],
      slotNote: 'オンデマンド', credits: 2, kind: '選択', grad: '教養', teacher: '高瀬 陽介',
      learn: '表計算と文書づくりの基本',
    }),
    course({
      code: 'LW1501', name: '環境と法', frameId: null, faculty: '法学部', year: 1, yearRange: '1〜4年', term: '春', slots: ['木4'],
      credits: 2, kind: '他学部', grad: '教養', teacher: '石動 早紀',
      learn: '公害の歴史と環境法のしくみ',
      summary: '公害の歴史をたどり、環境を守る法律がどう作られ、どう使われているかを学ぶ。',
    }),
    course({
      code: 'GE1301', name: '数学を学ぶ（微分積分I・演習I）', short: '微積I', frameId: 'g1c', year: 1, term: '春', slots: ['火1'], credits: 2,
      kind: '必修', grad: '必修', teacher: '野々村 修',
      learn: '関数の極限、微分と積分の計算',
    }),
    course({
      code: 'EC1101', name: '化学工学量論及び演習', short: '量論', frameId: 'g1a', year: 1, term: '春', slots: ['水2'], credits: 2,
      kind: '必修', grad: '必修', teacher: '片桐 恵',
      learn: '物質とエネルギーの出入りを数で追う',
    }),
    course({
      code: 'LA1101', name: '英語I（リーディング）', short: '英語I', frameId: null, year: 1, term: '春', slots: ['木1'], credits: 1,
      kind: '必修', grad: '必修', teacher: '三輪 千尋',
      learn: '英文を速く正確に読む練習',
    }),

    /* ---------- 1年秋 ---------- */
    course({
      code: 'EC1103', name: '化学工学概論', short: '概論', frameId: 'g1a', year: 1, term: '秋', slots: ['水2'], credits: 2,
      kind: '選択', grad: '選択', teacher: '片桐 恵',
      learn: '化学工場のしくみと化学工学の考え方',
    }),
    course({
      // 担当が「準備中」（元データにはあるが、まだ届いていない）
      code: 'EC1202', name: '基礎有機化学', short: '基礎有機', frameId: 'g1b', year: 1, term: '秋', slots: ['月2'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '有機化合物の構造と名前',
    }),
    course({
      // 2コマの科目（両方のマスに入れる）
      code: 'EC1203', name: '基礎化学実験', short: '化学実験', frameId: 'g1b', year: 1, term: '秋', slots: ['木3', '木4'], credits: 2,
      kind: '選択', grad: '選択', teacher: '大森 理沙',
      learn: '化学実験の基本の操作',
    }),
    course({
      code: 'GE1303', name: '数学を学ぶ（微分積分II・演習II）', short: '微積II', frameId: 'g1c', year: 1, term: '秋', slots: ['火1'], credits: 2,
      kind: '必修', grad: '必修', teacher: '野々村 修',
      learn: '多変数の微分と重積分',
    }),
    course({
      // 単位が「記載なし」（興味関心「技術と社会」の一覧に出る）
      code: 'GE1302', name: '数学を学ぶ（線形代数I・演習I）', short: '線形I', frameId: 'g1c', year: 1, term: '秋', slots: ['金2'], credits: null,
      kind: '選択', grad: '教養', teacher: '野々村 修',
      learn: '行列とベクトルの計算',
    }),
    course({
      // 区分が「準備中」（コードの意味がまだ決まっていない）
      code: 'GE1305', name: '情報処理演習', short: '情報処理', frameId: 'g1e', year: 1, term: '秋', slots: ['水4'], credits: 2,
      kind: null, grad: '教養', teacher: '高瀬 陽介',
      learn: 'プログラムで計算とグラフを作る',
    }),

    /* ---------- 2年 ---------- */
    course({
      code: 'EC2101', name: 'ユニットオペレーションI', short: 'ユニオペI', frameId: 'g2a', year: 2, term: '春', slots: ['火2'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '流れと熱の移動、装置の基本の操作',
    }),
    course({
      code: 'EC2102', name: 'ユニットオペレーションII', short: 'ユニオペII', frameId: 'g2a', year: 2, term: '秋', slots: ['火2'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '蒸留と吸収で物を分ける装置',
    }),
    course({
      code: 'EC2103', name: '反応工学', short: '反応', frameId: 'g2a', year: 2, term: '秋', slots: ['木2'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '反応の速さと反応器の設計',
    }),
    course({
      code: 'EC2201', name: '物理化学I', short: '物化I', frameId: 'g2b', year: 2, term: '春', slots: ['月3'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '気体の性質と熱力学の第一法則',
    }),
    course({
      code: 'EC2202', name: '物理化学II', short: '物化II', frameId: 'g2b', year: 2, term: '秋', slots: ['月3'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '化学平衡と相の変化',
    }),
    course({
      code: 'EC2301', name: '分析化学', short: '分析', frameId: 'g2c', year: 2, term: '春', slots: ['水2'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '物質の量を正しく測る方法',
    }),
    course({
      // 授業でやること（概要）が無く、授業計画の最初の3回で代える
      code: 'EC2302', name: '有機化学I', short: '有機I', frameId: 'g2c', year: 2, term: '春', slots: ['木2'], credits: 2,
      kind: '選択', grad: '選択',
      plan: ['有機化合物の結合', '立体の考え方', 'アルカンとアルケン', '置換反応', '脱離反応', '芳香族の化合物', '演習', 'まとめ'],
    }),
    course({
      // 原文の URL が無い
      code: 'EC2401', name: '応用統計学', short: '統計', frameId: 'g2d', year: 2, term: '春', slots: ['金4'], credits: 2,
      kind: '選択', grad: '選択', url: false,
      learn: '実験のデータから確かなことを言う方法',
    }),

    /* ---------- 3年 ---------- */
    course({
      code: 'EC3101', name: '大気・水環境化学工学', short: '大気水', frameId: 'g3a', year: 3, term: '春', slots: ['木3'], credits: 2,
      kind: '選択', grad: '選択', teacher: '宮坂 直樹',
      learn: '大気と水の汚れを取り除くしくみ',
      summary: '大気と水の汚れのでき方と取り除き方を、物質の収支と装置の設計から学ぶ。',
      plan: ['大気環境と化学工学', '大気汚染物質の発生', '粒子状物質の除去', '水質の指標', '水の汚れと生き物', '物質収支で汚れを追う', '排水処理のプロセス', '活性汚泥法', '膜による分離', '吸着と脱臭', '排ガス処理装置の設計', '地球規模の大気の問題', '水資源と再利用', '装置の設計演習', 'まとめと試験'],
      grading: '期末試験 60%、レポート 40%', textbook: TEXTBOOK_HANDOUT,
    }),
    course({
      code: 'EC3102', name: '化学プラント設計', short: 'プラント', frameId: 'g3a', year: 3, term: '秋', slots: ['月4'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '化学工場の装置を組み合わせて設計する',
    }),
    course({
      code: 'EC3103', name: '化学工学実験', short: '化工実験', frameId: 'g3a', year: 3, term: '秋', slots: ['火3'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '装置を動かして物質と熱の移動を測る',
    }),
    course({
      code: 'EC3104', name: 'プロセス制御', short: '制御', frameId: 'g3a', year: 3, term: '秋', slots: ['水2'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '温度や流量を自動で保つしくみ',
    }),
    course({
      // 担当が「シラバスに記載なし」
      code: 'EC3201', name: 'エネルギー材料工学', short: 'エネ材料', frameId: 'g3b', year: 3, term: '春', slots: ['月3'], credits: 2,
      kind: '選択', grad: '選択', teacher: 'none',
      learn: '電池や太陽電池の材料',
    }),
    course({
      code: 'EC3202', name: '電池と燃料電池', short: '電池', frameId: 'g3b', year: 3, term: '秋', slots: ['火2'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '電気をためて取り出すしくみ',
    }),
    course({
      code: 'EC3301', name: '触媒化学', short: '触媒', frameId: 'g3c', year: 3, term: '春', slots: ['水3'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '反応を速める触媒のはたらき',
    }),
    course({
      code: 'EC3302', name: '有機合成化学', short: '有機合成', frameId: 'g3c', year: 3, term: '秋', slots: ['木1'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '目的の分子を組み立てる反応の選び方',
    }),
    course({
      code: 'EC3401', name: '化学プロセス安全工学', short: '安全工学', frameId: 'g3d', year: 3, term: '春', slots: ['金3'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '事故を防ぐ工場の安全の考え方',
    }),
    course({
      code: 'EC3402', name: '技術者倫理', short: '倫理', frameId: 'g3d', year: 3, yearRange: '3〜4年', term: '秋', slots: ['火4'], credits: 2,
      kind: '選択', grad: '教養',
      learn: '技術者が仕事で迷う場面の考え方',
    }),
    course({
      // 集中講義（曜限なし）。授業でやることも授業計画も無い
      code: 'EC3403', name: '特別講義（品質管理）', short: '品質管理', frameId: 'g3d', year: 3, term: '秋', slots: [],
      slotNote: '集中講義', credits: 1, kind: null, grad: '選択',
    }),

    /* ---------- 4年 ---------- */
    course({
      code: 'EC4101', name: '特別研究I', short: '研究I', frameId: 'g4a', year: 4, term: '通年', slots: [],
      slotNote: '研究室で決める', credits: 4, kind: '必修', grad: '必修',
      learn: '研究室に入って研究を進める',
    }),
    course({
      code: 'EC4201', name: '知的財産と技術マネジメント', short: '知財', frameId: 'g4b', year: 4, term: '春', slots: ['水2'], credits: 2,
      kind: '選択', grad: '選択',
      learn: '特許と、技術を仕事にするときの決まり',
    }),
  ],
}

/** データのある学科の一覧（W7）。モックでは1つだけ。 */
export const FIXTURE_DEPARTMENTS: Department[] = [FIXTURE_DEPARTMENT]
