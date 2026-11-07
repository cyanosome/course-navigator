/**
 * 画面のデータ源。学科・系統図・卒業要件・科目の詳細・検索を、要るときに backend の API へ問い合わせる
 * （データはフロントに置かない。api-contract.md 5.2）。
 * 開発ビルドで VITE_NAVI_DATA=fixture のときだけ、API の代わりに見本のデータ（fixtureDataSource.ts）を使う
 * （例 `VITE_NAVI_DATA=fixture npm run dev`）。見本は動的に読み込むので、本番のビルドには入らない。
 */
import { createContext, useContext } from 'react'
import * as api from './api'
import type { CoursePage, CourseQuery, DepartmentSummary, GroupEdgeType } from './apiTypes'
import type { CourseMapping, MappingContext } from './mapping'
import { toCourseFromDetail, toDepartment } from './mapping'
import type { Department } from './types'

export interface NaviDataSource {
  /** D1 */
  listDepartments(signal: AbortSignal): Promise<DepartmentSummary[]>
  /** D2＋D3＋D6 をまとめて画面の学科に。科目は系統図に載る科目だけ */
  loadDepartment(id: string, edgeTypes: readonly GroupEdgeType[], signal: AbortSignal): Promise<Department>
  /** D4 */
  searchCourses(query: CourseQuery, signal: AbortSignal): Promise<CoursePage>
  /** D5 を詳細まで埋めた Course に（学年か学期が読めなければ ok: false） */
  getCourse(syllabusId: string, ctx: MappingContext, signal: AbortSignal): Promise<CourseMapping>
}

export function createHttpDataSource(): NaviDataSource {
  return {
    listDepartments: api.listDepartments,
    async loadDepartment(id, edgeTypes, signal) {
      const [overview, graph, requirements] = await Promise.all([
        api.getDepartment(id, signal),
        api.getGraph(id, edgeTypes, signal),
        api.getRequirements(id, signal),
      ])
      const { department, unmapped } = toDepartment(overview, graph, requirements)
      if (unmapped.length > 0) {
        console.warn(`学年か学期を読めない科目を、系統図の科目から外しました（${unmapped.length}件）`, unmapped)
      }
      return department
    },
    searchCourses: api.searchCourses,
    async getCourse(syllabusId, ctx, signal) {
      return toCourseFromDetail(await api.getCourse(syllabusId, signal), ctx)
    },
  }
}

export function createNaviDataSource(): NaviDataSource {
  if (import.meta.env.DEV && import.meta.env.VITE_NAVI_DATA === 'fixture') return createDevFixtureSource()
  return createHttpDataSource()
}

function createDevFixtureSource(): NaviDataSource {
  const loading = import('./fixtureDataSource').then((m) => m.createFixtureDataSource())
  return {
    listDepartments: async (signal) => (await loading).listDepartments(signal),
    loadDepartment: async (id, edgeTypes, signal) => (await loading).loadDepartment(id, edgeTypes, signal),
    searchCourses: async (query, signal) => (await loading).searchCourses(query, signal),
    getCourse: async (syllabusId, ctx, signal) => (await loading).getCourse(syllabusId, ctx, signal),
  }
}

export interface NaviData {
  source: NaviDataSource
  /**
   * 科目の詳細（D5）。取れた結果は小さな入れ物（Map）に持ち、同じ科目を開き直しても問い合わせない。
   * 学科の科目（dept.courses）には混ぜない（おすすめの候補が閲覧で変わらないように。api-contract.md 5.3）
   */
  loadCourse: (syllabusId: string, signal: AbortSignal) => Promise<CourseMapping>
  /** 入れ物にある科目（まだ取っていなければ undefined。問い合わせない） */
  peekCourse: (syllabusId: string) => CourseMapping | undefined
}

/** 学科ごとに作る（他学部の科目かどうかが学科の学部で決まるため） */
export function createCourseStore(source: NaviDataSource, ctx: MappingContext): Pick<NaviData, 'loadCourse' | 'peekCourse'> {
  const cache = new Map<string, CourseMapping>()
  return {
    async loadCourse(syllabusId, signal) {
      const hit = cache.get(syllabusId)
      if (hit !== undefined) return hit
      const result = await source.getCourse(syllabusId, ctx, signal)
      cache.set(syllabusId, result)
      return result
    },
    peekCourse: (syllabusId) => cache.get(syllabusId),
  }
}

/** 入れ物の科目の名前（Course にできなかった科目も名前は持つ） */
export function mappedCourseName(mapping: CourseMapping | undefined): string | undefined {
  if (mapping === undefined) return undefined
  return mapping.ok ? mapping.course.name : mapping.name
}

export const NaviDataContext = createContext<NaviData | null>(null)

export function useNaviData(): NaviData {
  const value = useContext(NaviDataContext)
  if (value === null) throw new Error('useNaviData は NaviApp の中で使ってください')
  return value
}
