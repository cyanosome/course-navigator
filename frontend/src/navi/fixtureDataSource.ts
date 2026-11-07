/**
 * 開発用の見本のデータ源（API が無くても画面を作れるように）。中身は架空の見本（fixtureDepartment.ts）。
 * dataSource.ts が開発ビルドで VITE_NAVI_DATA=fixture のときだけ動的に読み込む。本番のビルドには入らない。
 */
import { ApiError } from './api'
import type { CoursePage, CourseQuery, CourseSummary, DepartmentSummary, KindCode } from './apiTypes'
import type { NaviDataSource } from './dataSource'
import { FIXTURE_DEPARTMENTS } from './fixtureDepartment'
import type { Course, Department, Kind } from './types'

const DEFAULT_LIMIT = 20

function notFound(what: string): ApiError {
  return new ApiError('http', 404, `${what}は見本のデータにありません`, `${what}: HTTP 404（見本）`)
}

function findDepartment(id: string): Department {
  const dept = FIXTURE_DEPARTMENTS.find((d) => d.id === id)
  if (dept === undefined) throw notFound('学科')
  return dept
}

function allCourses(): Course[] {
  return FIXTURE_DEPARTMENTS.flatMap((d) => d.courses)
}

const KIND_CODE: Record<Kind, KindCode | null> = {
  必修: 'required',
  選択必修: 'elective_required',
  選択: 'elective',
  他学部: null,
}

/** 見本の科目を検索の応答（D4）の形に戻す */
function toSummary(c: Course): CourseSummary {
  return {
    syllabus_id: c.code,
    course_code: c.code,
    name: c.name,
    subtitle: null,
    group_id: c.frameId,
    year_min: c.year,
    year_max: c.year,
    year_range: c.yearRange,
    term: c.term,
    term_raw: c.term,
    slots: c.slots,
    slot_note: c.slotNote,
    credits: c.credits,
    faculties: c.faculty === null ? [] : [c.faculty],
    teacher: c.teacher.status === 'known' ? c.teacher.name : null,
    lead: c.learn,
    kind: kindCode(c),
    detail_url: c.syllabusUrl,
  }
}

function kindCode(c: Course): KindCode | null {
  return c.kind === null ? null : KIND_CODE[c.kind]
}

function compareCode(a: Course, b: Course): number {
  return a.code < b.code ? -1 : a.code > b.code ? 1 : 0
}

/** D4 と同じ並び: 科目名がすべての語を含むものを先に、次に ID の昇順 */
function search(query: CourseQuery): CoursePage {
  // \s は全角の空白（U+3000）も含む
  const words = (query.q ?? '').split(/\s+/).filter((w) => w !== '')
  const matches = (c: Course) => words.every((w) => `${c.name} ${c.summary} ${c.learn}`.includes(w))
  const nameRank = (c: Course) => (words.every((w) => c.name.includes(w)) ? 0 : 1)
  const items = allCourses()
    .filter(matches)
    .filter((c) => query.year === undefined || c.year === query.year)
    .filter((c) => query.term === undefined || c.term === query.term)
    .filter((c) => query.slot === undefined || c.slots.some((s) => query.slot?.includes(s)))
    .filter((c) => query.group === undefined || (c.frameId !== null && query.group.includes(c.frameId)))
    .filter((c) => {
      const code = kindCode(c)
      return query.kind === undefined || (code !== null && query.kind.includes(code))
    })
    .sort((a, b) => nameRank(a) - nameRank(b) || compareCode(a, b))
    .map(toSummary)
  const limit = query.limit ?? DEFAULT_LIMIT
  const offset = query.offset ?? 0
  return { total: items.length, limit, offset, items: items.slice(offset, offset + limit), kinds_status: 'available' }
}

export function createFixtureDataSource(): NaviDataSource {
  return {
    async listDepartments(signal) {
      signal.throwIfAborted()
      return FIXTURE_DEPARTMENTS.map(
        (d): DepartmentSummary => ({
          id: d.id,
          university: d.university,
          faculty: d.faculty,
          name: d.name,
          syllabus_year: d.syllabusYear,
          data_version: d.dataVersion,
          course_count: d.courses.length,
          group_count: d.frames.length,
        }),
      )
    },
    async loadDepartment(id, _edgeTypes, signal) {
      signal.throwIfAborted()
      return findDepartment(id)
    },
    async searchCourses(query, signal) {
      signal.throwIfAborted()
      return search(query)
    },
    async getCourse(syllabusId, _ctx, signal) {
      signal.throwIfAborted()
      const course = allCourses().find((c) => c.code === syllabusId)
      if (course === undefined) throw notFound('科目')
      return { ok: true, course }
    },
  }
}
