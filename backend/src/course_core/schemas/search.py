"""Search request and response schemas."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    HYBRID = "hybrid"               # 動的 Vector + トポロジー走査 (提案手法)
    SIMILARITY_EDGE = "similarity" # 事前計算 [:SIMILAR_TO] エッジ走査
    PURE_GRAPH = "pure_graph"       # 前提トポロジー走査のみ


class CoursePrereqItem(BaseModel):
    code: str
    title: str
    credits: Optional[float] = None
    term: Optional[str] = None
    depth: int = 1


class CourseSearchResultItem(BaseModel):
    code: str
    title: str
    credits: Optional[float] = None
    term: Optional[str] = None
    category: Optional[str] = None
    requirement_category: Optional[str] = None
    score: float = Field(..., description="類似度スコア (0.0〜1.0)")
    prerequisites: list[CoursePrereqItem] = Field(default_factory=list)


class CourseSearchRequest(BaseModel):
    query: str = Field(..., description="自然言語クエリまたは科目名/コード")
    mode: SearchMode = Field(SearchMode.HYBRID, description="探索モード")
    top_k: int = Field(5, ge=1, le=50)
    max_depth: int = Field(3, ge=1, le=5)


class CourseSearchResponse(BaseModel):
    mode: SearchMode
    query: str
    total_hits: int
    execution_time_ms: float
    results: list[CourseSearchResultItem]


class GraphNode(BaseModel):
    id: str
    code: str
    title: str
    credits: Optional[float] = None
    term: Optional[str] = None
    node_type: str = "course"  # "seed", "prerequisite", "similar"


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str  # "REQUIRES_PREREQUISITE", "SIMILAR_TO"
    score: Optional[float] = None


class CourseGraphResponse(BaseModel):
    course_code: str
    title: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
