/**
 * API の応答（apiTypes.ts、snake_case）から画面の型（types.ts）への写像（api-contract.md 5.1）。I/O を持たない純関数だけ。
 * 読めない値は推測で埋めない。学年か学期が読めない科目は今の画面の型（Course）にできないので、理由を付けて返す
 * （扱いは T15 で値を集計してから決める）。
 */
import type {
  CourseDetail,
  CourseSummary,
  DepartmentGraph,
  DepartmentOverview,
  GroupEdge,
  GroupNode,
  InterestOut,
  KindCode,
  RequirementsOut,
} from './apiTypes'
import type { Course, Department, Frame, FrameEdge, Interest, Kind, Requirements, TeacherInfo, Term } from './types'

export interface MappingContext {
  /** 学科の学部名（例 環境都市工学部）。他学部の科目かどうかを決める */
  ownFaculty: string
}

/** 学年か学期が読めず Course にできなかった科目 */
export interface UnmappedCourse {
  syllabusId: string
  name: string
  missing: ('year' | 'term')[]
  syllabusUrl: string | null
}

export type CourseMapping = { ok: true; course: Course } | ({ ok: false } & UnmappedCourse)

const KIND_LABEL: Record<KindCode, Kind> = {
  required: '必修',
  elective_required: '選択必修',
  elective: '選択',
}

/** 区分のコードを画面の言葉に。区分のデータが無い科目は null（画面は「準備中」） */
export function kindLabel(code: KindCode | null): Kind | null {
  return code === null ? null : KIND_LABEL[code]
}

/**
 * 他学部の科目なら、その学部の略号（例 法）。開講の学部に自分の学部が入っていれば null。
 * 【推定】略号は学部名の先頭の文字（例 環 → 環境都市工学部）。T15 で faculties の値を集計して確かめる。
 */
export function otherFaculty(faculties: string[], ownFaculty: string): string | null {
  const named = faculties.filter((f) => f !== '')
  if (named.length === 0) return null
  if (named.some((f) => ownFaculty.startsWith(f))) return null
  return named.join('・')
}

function teacherOf(name: string | null): TeacherInfo {
  return name === null ? { status: 'notInSyllabus' } : { status: 'known', name }
}

/** 教科書の欄（書名を並べ、備考を後ろに）。どちらも無ければ null */
export function textbookText(textbooks: string[], notes: string | null): string | null {
  const parts = [...textbooks, notes ?? ''].map((t) => t.trim()).filter((t) => t !== '')
  return parts.length === 0 ? null : parts.join('、')
}

function mapCourse(s: CourseSummary, year: number | null, ctx: MappingContext, detail: Partial<Course>): CourseMapping {
  const term: Term | null = s.term
  if (year === null || term === null) {
    const missing: ('year' | 'term')[] = []
    if (year === null) missing.push('year')
    if (term === null) missing.push('term')
    return { ok: false, syllabusId: s.syllabus_id, name: s.name, missing, syllabusUrl: s.detail_url }
  }
  const course: Course = {
    code: s.syllabus_id,
    name: s.name,
    short: null,
    frameId: s.group_id,
    faculty: otherFaculty(s.faculties, ctx.ownFaculty),
    year,
    yearRange: s.year_range,
    term,
    slots: s.slots,
    slotNote: s.slot_note,
    credits: s.credits,
    kind: kindLabel(s.kind),
    // 卒業要件の区分（必修・選択・教養）との対応は T17 で決める。それまでは数えない
    grad: null,
    teacher: teacherOf(s.teacher),
    learn: s.lead,
    summary: '',
    plan: [],
    grading: null,
    textbook: null,
    syllabusUrl: s.detail_url,
    ...detail,
  }
  return { ok: true, course }
}

/** 一覧の項目（D3 の members、D4 の items）から。詳細の本文は空 */
export function toCourse(s: CourseSummary, ctx: MappingContext): CourseMapping {
  return mapCourse(s, s.year_min, ctx, {})
}

/** 詳細（D5）から。学年はシラバスの配当年次、無ければ要覧の配当年次 */
export function toCourseFromDetail(d: CourseDetail, ctx: MappingContext): CourseMapping {
  return mapCourse(d, d.year_min ?? d.bulletin?.assigned_year ?? null, ctx, {
    summary: d.description ?? '',
    plan: d.schedule.map((item) => item.topic),
    grading: d.grading_policy,
    textbook: textbookText(d.textbooks, d.textbook_notes),
  })
}

export function toFrame(g: GroupNode): Frame {
  return { id: g.group_id, year: g.academic_year, name: g.name, plain: g.plain ?? g.name, common: g.common }
}

export function toFrameEdge(e: GroupEdge): FrameEdge {
  return { from: e.source, to: e.target }
}

export function toInterest(i: InterestOut): Interest {
  return {
    id: i.id,
    label: i.label,
    targets: i.targets,
    extras: i.extras.map((x) => ({ code: x.syllabus_id, why: x.why, source: x.source })),
  }
}

/** 興味関心のチップの先頭「おすすめ」（画面の既定の一覧。データではない） */
export const DEFAULT_INTEREST: Interest = { id: 'default', label: 'おすすめ', targets: [], extras: [] }

/** 卒業要件。DB に無い（pending）なら null（画面は「準備中」）。学期の上限は DB に無いので null */
export function toRequirements(r: RequirementsOut): Requirements | null {
  if (r.status !== 'available' || r.requirements === null) return null
  return { total: r.requirements.total_credits, termCap: r.requirements.term_cap, needs: [], sample: false }
}

export interface DepartmentMapping {
  department: Department
  /** 学年か学期が読めず、系統図の科目から外したもの */
  unmapped: UnmappedCourse[]
}

/** D2＋D3＋D6 から学科。科目は系統図に載る科目（members）だけ（api-contract.md 2.3） */
export function toDepartment(
  overview: DepartmentOverview,
  graph: DepartmentGraph,
  requirements: RequirementsOut,
): DepartmentMapping {
  const ctx: MappingContext = { ownFaculty: overview.faculty }
  const courses: Course[] = []
  const unmapped: UnmappedCourse[] = []
  for (const m of graph.members) {
    const r = toCourse(m, ctx)
    if (r.ok) courses.push(r.course)
    else unmapped.push({ syllabusId: r.syllabusId, name: r.name, missing: r.missing, syllabusUrl: r.syllabusUrl })
  }
  const interests = graph.interests.map(toInterest)
  return {
    department: {
      id: overview.id,
      university: overview.university,
      faculty: overview.faculty,
      name: overview.name,
      dataVersion: overview.data_version,
      syllabusYear: overview.syllabus_year,
      frames: graph.groups.map(toFrame),
      edges: graph.edges.map(toFrameEdge),
      courses,
      interests: interests.some((i) => i.id === DEFAULT_INTEREST.id) ? interests : [DEFAULT_INTEREST, ...interests],
      requirements: toRequirements(requirements),
    },
    unmapped,
  }
}
