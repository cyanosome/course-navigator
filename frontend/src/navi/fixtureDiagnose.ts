/**
 * これは画面モック用の架空の見本（fixture）です。本物の診断の設定とエンジンではありません。
 *
 * 開発用の診断のデータ源（API が無くても診断の画面を作れるように）。diagnose.ts が開発ビルドで VITE_NAVI_DATA=fixture のときだけ
 * 動的に読み込む。本番のビルドには入らない。
 * - 設定は事前登録（protocol.md）の「設定の形」に合わせた見本。質問・重みは診断のコンペで決めるので、ここの中身は仮。
 * - プランの組み方は事前登録のエンジンの決まり（学期ごとに点の高い順、同じ曜限に2つ入れない、上限を超えない、同点は
 *   syllabus_id、同じ科目名はプランに1つまで（前の学期までに入った名前も入れない）。同じ名前の別クラスは点の順に見て、
 *   上のクラスが曜限か上限で入らなければ次のクラスを見る（backend の P-a、9e23f1f））を、見本の学科（fixtureDepartment.ts）の上でまねたもの。見本だけの簡略: 学期と配当の学年が合わない科目は
 *   点にかかわらず入れない。scale5 は答えの n 番目の選択肢の点の付け方を使う（API と同じ）。理由の文は、選んだ選択肢の効果と
 *   base の in_group・reaches_group・on_curriculum だけから作る（backend のエンジンと同じ決まり。理由が空の科目もある）。
 * - 履修の状況（start・completed・registered）は backend の course_core.diagnose.history をまねる: start から先だけを埋め、
 *   履修済み・登録済みと同じ名前を入れず、登録済みは学期のはじめに置く。誤りは 422（見本の学科の科目で引く）。
 */
import { ApiError } from './api'
import type {
  DiagnoseAnswers,
  DiagnoseConfig,
  DiagnoseEffect,
  DiagnosePlanIn,
  DiagnosePlanOut,
  DiagnoseScopeTerm,
  PlanCourse,
  PlanReason,
} from './apiTypes'
import type { DiagnoseSource } from './diagnose'
import { firstUnanswered, isAnswered } from './diagnose'
import { FIXTURE_DEPARTMENTS } from './fixtureDepartment'
import type { Course, Department } from './types'

const WAIT_MS = 400
/** 理由の文は1科目に2つまで */
const REASONS_PER_COURSE = 2

export const FIXTURE_DIAGNOSE_CONFIG: DiagnoseConfig = {
  version: 'fixture-1107',
  department_id: 'enechem',
  // 学期は本物の設定（kansai-enechem-2026）と同じ 1年春〜3年秋（学期ごとの利用を見本で確かめるため）
  scope: {
    terms: [
      { year: 1, term: '春' },
      { year: 1, term: '秋' },
      { year: 2, term: '春' },
      { year: 2, term: '秋' },
      { year: 3, term: '春' },
      { year: 3, term: '秋' },
    ],
    credit_cap_per_term: 8,
  },
  questions: [
    {
      id: 'field',
      text: '3年で深めたいのはどれに近い？',
      kind: 'single',
      options: [
        { id: 'env', label: '環境とプロセス', effects: [{ primitive: 'reaches_group', args: { target: 'g3a' }, weight: 3 }] },
        { id: 'mat', label: '材料とエネルギー', effects: [{ primitive: 'reaches_group', args: { target: 'g3b' }, weight: 3 }] },
        { id: 'org', label: '有機と触媒', effects: [{ primitive: 'reaches_group', args: { target: 'g3c' }, weight: 3 }] },
        { id: 'soc', label: '技術と社会', effects: [{ primitive: 'reaches_group', args: { target: 'g3d' }, weight: 3 }] },
        { id: 'none', label: 'まだ決めていない', effects: [{ primitive: 'on_curriculum', args: {}, weight: 1 }] },
      ],
    },
    {
      id: 'free',
      text: '空けておきたい曜日は？（2つまで）',
      kind: 'multi',
      max_select: 2,
      options: [
        { id: 'mon', label: '月曜', effects: [{ primitive: 'slot_avoid', args: { days: ['月'], periods: [] }, weight: -3 }] },
        { id: 'wed', label: '水曜', effects: [{ primitive: 'slot_avoid', args: { days: ['水'], periods: [] }, weight: -3 }] },
        { id: 'fri', label: '金曜', effects: [{ primitive: 'slot_avoid', args: { days: ['金'], periods: [] }, weight: -3 }] },
        { id: 'any', label: 'どこでもいい', effects: [] },
      ],
    },
    {
      id: 'math',
      text: '数学や物理は好き？',
      kind: 'scale5',
      options: [
        { id: 's1', label: '苦手', effects: [{ primitive: 'keyword', args: { words: ['数学', '物理'], fields: ['name'] }, weight: -2 }] },
        { id: 's2', label: 'あまり', effects: [{ primitive: 'keyword', args: { words: ['数学', '物理'], fields: ['name'] }, weight: -1 }] },
        { id: 's3', label: 'ふつう', effects: [] },
        { id: 's4', label: '少し好き', effects: [{ primitive: 'keyword', args: { words: ['数学', '物理'], fields: ['name'] }, weight: 1 }] },
        { id: 's5', label: '好き', effects: [{ primitive: 'keyword', args: { words: ['数学', '物理'], fields: ['name'] }, weight: 2 }] },
      ],
    },
  ],
  base_effects: [
    { primitive: 'on_curriculum', args: {}, weight: 1 },
    { primitive: 'own_department', args: {}, weight: 1 },
  ],
  tie_break: 'syllabus_id',
  reason_templates: {
    reaches_group: '3年の「{group}」につながる',
    on_curriculum: '系統図に載っている',
    keyword: '「{word}」を扱う',
    own_department: '学科の科目',
  },
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

function findDept(id: string): Department {
  const dept = FIXTURE_DEPARTMENTS.find((d) => d.id === id)
  if (dept === undefined) throw new ApiError('http', 404, '学科は見本のデータにありません', '診断の設定: HTTP 404（見本）')
  return dept
}

/** まとまりから線を下へたどって target に届くか（同じまとまりも届く） */
function reaches(dept: Department, from: string | null, target: string): boolean {
  if (from === null) return false
  const seen = new Set([from])
  const stack = [from]
  while (stack.length > 0) {
    const id = stack.pop()
    if (id === target) return true
    for (const e of dept.edges) {
      if (e.from === id && !seen.has(e.to)) {
        seen.add(e.to)
        stack.push(e.to)
      }
    }
  }
  return false
}

function stringList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
}

function numberList(v: unknown): number[] {
  return Array.isArray(v) ? v.filter((x): x is number => typeof x === 'number') : []
}

/** primitive の値（見本の学科の科目で計算） */
function primitiveValue(dept: Department, c: Course, e: DiagnoseEffect): number {
  switch (e.primitive) {
    case 'in_group':
      return c.frameId !== null && stringList(e.args.groups).includes(c.frameId) ? 1 : 0
    case 'reaches_group':
      return typeof e.args.target === 'string' && reaches(dept, c.frameId, e.args.target) ? 1 : 0
    case 'slot_avoid': {
      // 曜日か時限を省いたら、その全部
      const days = stringList(e.args.days)
      const periods = numberList(e.args.periods)
      const hit = (s: string) =>
        (days.length === 0 || days.includes(s.slice(0, 1))) && (periods.length === 0 || periods.includes(Number(s.slice(1))))
      return c.slots.some(hit) ? 1 : 0
    }
    case 'keyword': {
      const text = `${c.name} ${c.summary} ${c.learn}`
      return stringList(e.args.words).some((w) => text.includes(w)) ? 1 : 0
    }
    case 'own_department':
      return c.faculty === null ? 1 : 0
    case 'credits':
      return c.credits ?? 0
    case 'on_curriculum':
      return c.frameId !== null ? 1 : 0
    default:
      return 0
  }
}

function frameName(dept: Department, id: unknown): string {
  return dept.frames.find((f) => f.id === id)?.plain ?? String(id)
}

function reasonText(config: DiagnoseConfig, dept: Department, e: DiagnoseEffect): string | null {
  const template = config.reason_templates[e.primitive]
  if (template === undefined) return null
  return template.replace('{group}', frameName(dept, e.args.target)).replace('{word}', stringList(e.args.words).join('・'))
}

/** base の効果のうち、理由の文にしてよいもの（backend のエンジンの決まり。year_fit・term_fit・keyword などは点だけ） */
const BASE_REASON_PRIMITIVES: readonly string[] = ['in_group', 'reaches_group', 'on_curriculum']

interface ActiveEffect {
  e: DiagnoseEffect
  /** 理由の文にしてよいか（選んだ選択肢の効果と、base の BASE_REASON_PRIMITIVES） */
  reason: boolean
}

/** 答えで効く点の付け方（scale5 は答えの n 番目の選択肢） */
function activeEffects(config: DiagnoseConfig, answers: DiagnoseAnswers): ActiveEffect[] {
  const out: ActiveEffect[] = config.base_effects.map((e) => ({ e, reason: BASE_REASON_PRIMITIVES.includes(e.primitive) }))
  const chosen = (effects: readonly DiagnoseEffect[]) => out.push(...effects.map((e) => ({ e, reason: true })))
  for (const q of config.questions) {
    const a = answers[q.id]
    if (q.kind === 'scale5' && typeof a === 'number') {
      chosen(q.options[a - 1]?.effects ?? [])
    } else if (Array.isArray(a)) {
      for (const o of q.options.filter((x) => a.includes(x.id))) chosen(o.effects)
    }
  }
  return out
}

/** 見本の答えの指紋（キーを並べた JSON の FNV-1a 32 ビット） */
function digest(answers: DiagnoseAnswers): string {
  const sorted = Object.fromEntries(Object.entries(answers).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
  let hash = 0x811c9dc5
  for (const byte of new TextEncoder().encode(JSON.stringify(sorted))) {
    hash ^= byte
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return `fnv1a32:${hash.toString(16).padStart(8, '0')}`
}

/** 検査を通った履修の状況（見本） */
interface FixtureHistory {
  start: DiagnoseScopeTerm | null
  completed: Course[]
  /** 学期の鍵（例 2-秋）→ その学期の登録済みの科目 */
  registered: Map<string, Course[]>
}

const termKey = (t: DiagnoseScopeTerm) => `${t.year}-${t.term}`
const termRank = (t: DiagnoseScopeTerm) => t.year * 2 + (t.term === '秋' ? 1 : 0)

/** backend の validate_history と同じ誤り（scope に無い start、埋めない学期の registered、知らない科目、重複）を 422 に */
function checkHistory(config: DiagnoseConfig, dept: Department, input: DiagnosePlanIn): FixtureHistory {
  const bad = (what: string) => new ApiError('http', 422, `履修の状況に誤りがあります: ${what}（見本）`, 'プラン: HTTP 422（見本）')
  const start = input.start ?? null
  if (start !== null && !config.scope.terms.some((t) => termKey(t) === termKey(start))) throw bad('start が scope にありません')
  const byId = new Map(dept.courses.map((c) => [c.code, c]))
  const find = (id: string) => {
    const c = byId.get(id)
    if (c === undefined) throw bad(`知らない科目です: ${id}`)
    return c
  }
  const completed = (input.completed ?? []).map(find)
  const registered = new Map<string, Course[]>()
  const seen = new Set(completed.map((c) => c.code))
  if (seen.size !== completed.length) throw bad('completed に同じ科目が2回あります')
  for (const r of input.registered ?? []) {
    if (registered.has(termKey(r))) throw bad(`registered に ${termKey(r)} が2回あります`)
    if (start !== null && termRank(r) < termRank(start)) throw bad(`registered の ${termKey(r)} は埋める学期にありません`)
    const courses = r.syllabus_ids.map(find)
    for (const c of courses) {
      if (seen.has(c.code)) throw bad(`同じ科目が2回あります: ${c.code}`)
      seen.add(c.code)
    }
    registered.set(termKey(r), courses)
  }
  return { start, completed, registered }
}

function makePlan(config: DiagnoseConfig, dept: Department, answers: DiagnoseAnswers, history: FixtureHistory): DiagnosePlanOut {
  const effects = activeEffects(config, answers)
  const cap = config.scope.credit_cap_per_term
  /** プランに入った科目名（同じ名前はプランに1つまで。前の学期までに入った名前も、履修済み・登録済みの名前も入れない） */
  const placedNames = new Set<string>([
    ...history.completed.map((c) => c.name),
    ...[...history.registered.values()].flat().map((c) => c.name),
  ])
  const filled = config.scope.terms.filter((t) => history.start === null || termRank(t) >= termRank(history.start))
  const terms = filled.map((t) => {
    // 登録済みの科目は学期のはじめにそのまま置く（曜限をふさぎ、単位に数える）
    const fixed: PlanCourse[] = (history.registered.get(termKey(t)) ?? []).map((c) => ({
      syllabus_id: c.code,
      name: c.name,
      credits: c.credits,
      slots: c.slots,
      slot_note: c.slotNote,
      score: 0,
      reasons: [],
      status: 'registered',
    }))
    const scored = dept.courses
      .filter((c) => c.year === t.year && (c.term === t.term || c.term === '通年') && !placedNames.has(c.name))
      .map((c) => {
        const parts = effects.map(({ e, reason }) => ({ e, reason, v: e.weight * primitiveValue(dept, c, e) }))
        // 理由は点を足した効果のうち、理由にしてよいものだけ（無ければ理由は空。画面は理由の無い行も出す）
        const reasons: PlanReason[] = parts
          .filter((p) => p.v > 0 && p.reason)
          .sort((a, b) => b.v - a.v)
          .map((p) => ({ primitive: p.e.primitive, text: reasonText(config, dept, p.e) }))
          .filter((r): r is PlanReason => r.text !== null)
          .slice(0, REASONS_PER_COURSE)
        return { c, score: parts.reduce((n, p) => n + p.v, 0), reasons }
      })
      .sort((a, b) => b.score - a.score || (a.c.code < b.c.code ? -1 : a.c.code > b.c.code ? 1 : 0))
    const picked: PlanCourse[] = [...fixed]
    const used = new Set<string>(fixed.flatMap((c) => c.slots))
    let credits = fixed.reduce((n, c) => n + (c.credits ?? 0), 0)
    for (const { c, score, reasons } of scored) {
      // 同じ名前のクラスは点の順に見る。上のクラスが曜限か上限で入らなければ、名前は残して次のクラスを見る（P-a）
      if (placedNames.has(c.name)) continue
      if (score <= 0 || c.slots.some((s) => used.has(s))) continue
      if (cap !== null && credits + (c.credits ?? 0) > cap) continue
      c.slots.forEach((s) => used.add(s))
      credits += c.credits ?? 0
      placedNames.add(c.name)
      picked.push({ syllabus_id: c.code, name: c.name, credits: c.credits, slots: c.slots, slot_note: c.slotNote, score, reasons, status: 'planned' })
    }
    return { year: t.year, term: t.term, credits_total: credits, courses: picked }
  })
  const withHistory = history.start !== null || history.completed.length > 0 || history.registered.size > 0
  return {
    config_version: config.version,
    answers_digest: digest(answers),
    context_digest: withHistory ? 'fixture:history' : null,
    terms,
  }
}

export function createFixtureDiagnoseSource(): DiagnoseSource {
  return {
    async getConfig(deptId, signal) {
      await delay(WAIT_MS, signal)
      findDept(deptId)
      return FIXTURE_DIAGNOSE_CONFIG
    },
    async makePlan(input: DiagnosePlanIn, signal) {
      await delay(WAIT_MS, signal)
      const dept = findDept(input.department_id)
      const config = FIXTURE_DIAGNOSE_CONFIG
      if (input.config_version !== config.version) {
        throw new ApiError('http', 409, '設定の版が違います（見本）', 'プラン: HTTP 409（見本）')
      }
      const known = new Set(config.questions.map((q) => q.id))
      const extra = Object.keys(input.answers).some((id) => !known.has(id))
      const bad = config.questions.some((q) => input.answers[q.id] !== undefined && !isAnswered(q, input.answers[q.id]))
      if (extra || bad || firstUnanswered(config, input.answers) >= 0) {
        throw new ApiError('http', 422, '答えを読めません（見本）', 'プラン: HTTP 422（見本）')
      }
      return makePlan(config, dept, input.answers, checkHistory(config, dept, input))
    },
  }
}
