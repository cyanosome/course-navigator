/**
 * status.ts のプランの履修状況とチェック。同じ名前の別のクラスへ移しても、同じ学期なら元の系統図の科目と同じに扱う
 * （事前登録 study1 の 3.3 の K5 と同じ規則。学科の系統図には同じ名前の別クラスが載らない）。
 * - 必修のチェック: 移した科目でも「入っている」
 * - まとまりと必修の印: 移した科目も元の科目の frameId・required を持ち、前のまとまりの抜けとまとまりの数が移す前と同じ
 */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import type { WorkingCourse, WorkingPlan } from '../../src/navi/diagnose.ts'
import { buildStatus, evaluateCheckpoint, statusCoursesFromPlan } from '../../src/navi/status.ts'
import type { Checkpoint, CheckResult } from '../../src/navi/status.ts'
import type { Course, Department } from '../../src/navi/types.ts'

function course(code: string, name: string, year: number, term: '春' | '秋', slots: string[], extra: Partial<Course> = {}): Course {
  return {
    code,
    name,
    short: null,
    frameId: 'g1',
    faculty: null,
    year,
    yearRange: null,
    term,
    slots,
    slotNote: null,
    credits: 2,
    kind: '必修',
    grad: '必修',
    teacher: { status: 'notInSyllabus' },
    learn: '',
    summary: '',
    plan: [],
    grading: null,
    textbook: null,
    syllabusUrl: null,
    ...extra,
  }
}

/** 学科の系統図の必修は、物理（1年春の火3）と化学実験（1年秋の月4・月5）の2科目 */
const DEPT: Department = {
  id: 'test',
  university: 'テスト大学',
  faculty: 'テスト学部',
  name: 'テスト学科',
  dataVersion: 'test',
  syllabusYear: 2026,
  frames: [{ id: 'g1', year: 1, name: '基礎', plain: '基礎', common: false }],
  edges: [],
  courses: [
    course('PHYS-TUE3', '物理を学ぶ（力学１）', 1, '春', ['火3']),
    course('LAB-MON45', '化学実験', 1, '秋', ['月4', '月5']),
  ],
  interests: [],
  requirements: null,
}

function planCourse(syllabusId: string, name: string, slots: string[]): WorkingCourse {
  return { syllabus_id: syllabusId, name, credits: 2, slots, slot_note: null, score: null, reasons: [], origin: 'user' }
}

function plan(spring: WorkingCourse[], autumn: WorkingCourse[]): WorkingPlan {
  return {
    terms: [
      { year: 1, term: '春', courses: spring },
      { year: 1, term: '秋', courses: autumn },
    ],
  }
}

function checkRequired(p: WorkingPlan): CheckResult {
  const status = buildStatus(statusCoursesFromPlan(DEPT, p))
  const terms = p.terms.map((t) => ({ year: t.year, half: t.term }))
  return evaluateCheckpoint({ id: 'required', kind: 'required' }, status, { dept: DEPT, terms, kindsAvailable: true })
}

const LAB = planCourse('LAB-MON45', '化学実験', ['月4', '月5'])

describe('必修のチェック', () => {
  test('系統図のクラスが入っていれば満たす', () => {
    const r = checkRequired(plan([planCourse('PHYS-TUE3', '物理を学ぶ（力学１）', ['火3'])], [LAB]))
    assert.equal(r.status, 'met')
    assert.equal(r.reason, '2科目とも入っています')
  })

  test('同じ学期の同じ名前の別のクラスへ移しても満たす', () => {
    const r = checkRequired(plan([planCourse('PHYS-WED3', '物理を学ぶ（力学１）', ['水3'])], [planCourse('LAB-FRI45', '化学実験', ['金4', '金5'])]))
    assert.equal(r.status, 'met')
    assert.deepEqual(r.codes, [])
  })

  test('同じ名前でも別の学期にあるだけなら満たさない', () => {
    const r = checkRequired(plan([], [LAB, planCourse('PHYS-WED3', '物理を学ぶ（力学１）', ['水3'])]))
    assert.equal(r.status, 'unmet')
    assert.equal(r.reason, '物理を学ぶ（力学１）がありません')
    assert.deepEqual(r.codes, ['PHYS-TUE3'])
  })

  test('名前が違う科目では満たさない', () => {
    const r = checkRequired(plan([planCourse('PHYS-EM', '物理を学ぶ（電磁気学１）', ['水3'])], [LAB]))
    assert.equal(r.status, 'unmet')
    assert.deepEqual(r.codes, ['PHYS-TUE3'])
  })

  test('判定する学期の外の必修は問わない', () => {
    const status = buildStatus(statusCoursesFromPlan(DEPT, plan([], [LAB])))
    const r = evaluateCheckpoint({ id: 'required', kind: 'required' }, status, {
      dept: DEPT,
      terms: [{ year: 1, half: '秋' }],
      kindsAvailable: true,
    })
    assert.equal(r.status, 'met')
    assert.equal(r.reason, '1科目とも入っています')
  })
})

/**
 * 系統図: 1年の「基礎」→ 2年の「応用」。基礎は物理（1年春の火3、必修）だけ、応用は物理化学（2年春）。
 * 物理の別のクラスは、系統図に無い id（水3）と、学科のデータにあるが系統図に載っていない id（金3）の2つ
 */
const GRAPH_DEPT: Department = {
  ...DEPT,
  frames: [
    { id: 'g1', year: 1, name: '基礎', plain: '基礎', common: false },
    { id: 'g2', year: 2, name: '応用', plain: '応用', common: false },
  ],
  edges: [{ from: 'g1', to: 'g2' }],
  courses: [
    course('PHYS-TUE3', '物理を学ぶ（力学１）', 1, '春', ['火3']),
    course('PHYS-FRI3', '物理を学ぶ（力学１）', 1, '春', ['金3'], { frameId: null, kind: null, grad: null }),
    course('PCHEM', '物理化学', 2, '春', ['月1'], { frameId: 'g2', kind: '選択', grad: '選択' }),
  ],
}

const PCHEM = planCourse('PCHEM', '物理化学', ['月1'])

function graphPlan(spring1: WorkingCourse[]): WorkingPlan {
  return {
    terms: [
      { year: 1, term: '春', courses: spring1 },
      { year: 2, term: '春', courses: [PCHEM] },
    ],
  }
}

function judge(cp: Checkpoint, p: WorkingPlan): { status: string; reason: string } {
  const status = buildStatus(statusCoursesFromPlan(GRAPH_DEPT, p))
  const terms = p.terms.map((t) => ({ year: t.year, half: t.term }))
  const r = evaluateCheckpoint(cp, status, { dept: GRAPH_DEPT, terms, kindsAvailable: true })
  return { status: r.status, reason: r.reason }
}

const PREREQUISITE: Checkpoint = { id: 'prerequisite', kind: 'prerequisite' }
const BASICS_COUNT: Checkpoint = { id: 'group_count-1', kind: 'group_count', groups: ['g1'], min: 1 }
const ORIGINAL = graphPlan([planCourse('PHYS-TUE3', '物理を学ぶ（力学１）', ['火3'])])

describe('別のクラスへ移した科目のまとまりと必修', () => {
  for (const [label, code, slot] of [
    ['系統図に無い id のクラス', 'PHYS-WED3', '水3'],
    ['学科のデータにあるが系統図に載っていない id のクラス', 'PHYS-FRI3', '金3'],
  ] as const) {
    const moved = graphPlan([planCourse(code, '物理を学ぶ（力学１）', [slot])])

    test(`${label}へ移しても、元の科目の frameId と必修を持つ`, () => {
      const c = statusCoursesFromPlan(GRAPH_DEPT, moved).find((x) => x.code === code)
      assert.deepEqual([c?.frameId, c?.required], ['g1', true])
    })

    test(`${label}へ移しても、前のまとまりの抜けとまとまりの数は移す前と同じ`, () => {
      assert.deepEqual(judge(PREREQUISITE, moved), judge(PREREQUISITE, ORIGINAL))
      assert.deepEqual(judge(PREREQUISITE, moved), { status: 'met', reason: '抜けはありません' })
      assert.deepEqual(judge(BASICS_COUNT, moved), judge(BASICS_COUNT, ORIGINAL))
      assert.deepEqual(judge(BASICS_COUNT, moved), { status: 'met', reason: '1つ' })
    })
  }

  test('同じ名前でも別の学期の科目は、系統図の科目に照らさない', () => {
    const p: WorkingPlan = {
      terms: [
        { year: 1, term: '秋', courses: [planCourse('PHYS-AUT', '物理を学ぶ（力学１）', ['水3'])] },
        { year: 2, term: '春', courses: [PCHEM] },
      ],
    }
    const c = statusCoursesFromPlan(GRAPH_DEPT, p).find((x) => x.code === 'PHYS-AUT')
    assert.deepEqual([c?.frameId, c?.required], [null, false])
    assert.equal(judge(PREREQUISITE, p).status, 'unmet')
  })
})
