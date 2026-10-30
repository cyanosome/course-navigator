"""
Unit tests for Neo4j Curriculum & Course Loader.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, call
import pytest

from src.loaders.graph.curriculum_loader import (
    Neo4jCurriculumLoader,
    GraphLoadReport,
)
from src.loaders.graph.schema import (
    CONSTRAINTS,
    INGEST_COURSE_GROUPS_QUERY,
    INGEST_DIPLOMA_POLICIES_QUERY,
    INGEST_GROUP_PREREQUISITES_QUERY,
    INGEST_DP_CONTRIBUTIONS_QUERY,
    INGEST_COURSE_MEMBERSHIPS_QUERY,
    INGEST_COURSES_QUERY,
    INGEST_COURSE_PROFESSORS_QUERY,
    INGEST_COURSE_DEPARTMENTS_QUERY,
    INGEST_COURSE_FACULTIES_QUERY,
)


@pytest.fixture
def mock_driver():
    """Mock Neo4j Driver and Session."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    return driver, session


@pytest.fixture
def sample_tree_data():
    """Sample curriculum DAG JSON structure."""
    return {
        "university": "関西大学",
        "faculty": "環境都市工学部",
        "department": "エネルギー環境・化学工学科",
        "groups": [
            {
                "group_id": "DP1",
                "label": "DP1（知識・技能）",
                "academic_year": 0,
                "semester": None,
                "member_courses": [],
            },
            {
                "group_id": "G_2Y_PhysChem",
                "label": "物理化学グループ",
                "academic_year": 2,
                "semester": "春",
                "member_courses": [
                    {
                        "raw_name": "物理化学1",
                        "normalized_name": "物理化学1",
                        "syllabus_id": "162242",
                        "course_code": "062531",
                    }
                ],
            },
            {
                "group_id": "G_3Y_AppChem",
                "label": "応用化学グループ",
                "academic_year": 3,
                "semester": "秋",
                "member_courses": [
                    {
                        "raw_name": "反応工学",
                        "normalized_name": "反応工学",
                        "syllabus_id": "162489",
                        "course_code": "062573",
                    }
                ],
            },
        ],
        "edges": [
            {
                "source_group_id": "G_2Y_PhysChem",
                "target_group_id": "G_3Y_AppChem",
                "edge_type": "prerequisite",
                "is_major_connection": True,
            },
            {
                "source_group_id": "G_3Y_AppChem",
                "target_group_id": "DP1",
                "edge_type": "dp_contribution",
                "is_major_connection": True,
            },
        ],
    }


@pytest.fixture
def sample_courses_data():
    """Sample course details JSON structure."""
    return [
        {
            "syllabus_id": "162242",
            "course_code": "062531",
            "timetable_code": "K1234",
            "subject_name": "物理化学1",
            "subtitle": "",
            "credits": 2,
            "academic_year": 2,
            "year_range": "2-4年",
            "class_name": "",
            "semester": "春学期",
            "term_schedule": "金2",
            "language": "日本語",
            "teaching_type": "講義",
            "detail_url": "https://example.com/162242",
            "instructors": [{"name": "山田 太郎", "code": "P001", "is_primary": True}],
            "department_codes": ["E01"],
            "faculties": ["環境都市工学部"],
        },
        {
            "syllabus_id": "162489",
            "course_code": "062573",
            "timetable_code": "K5678",
            "subject_name": "反応工学",
            "subtitle": "",
            "credits": 2,
            "academic_year": 3,
            "year_range": "3-4年",
            "class_name": "",
            "semester": "秋学期",
            "term_schedule": "月3",
            "language": "日本語",
            "teaching_type": "講義",
            "detail_url": "https://example.com/162489",
            "instructors": [{"name": "佐藤 花子", "code": "P002", "is_primary": True}],
            "department_codes": ["E01"],
            "faculties": ["環境都市工学部"],
        },
    ]


def test_ensure_constraints(mock_driver):
    """Should execute all constraint queries defined in schema."""
    driver, session = mock_driver
    loader = Neo4jCurriculumLoader(driver=driver)

    loader.ensure_constraints(session)

    assert session.run.call_count == len(CONSTRAINTS)
    for q in CONSTRAINTS:
        session.run.assert_any_call(q)


def test_clear_kansai_graph(mock_driver):
    """Should execute detach delete queries for faculty and department."""
    driver, session = mock_driver
    loader = Neo4jCurriculumLoader(driver=driver)

    res = loader.clear_kansai_graph(session, faculty="環境都市工学部", department="エネルギー環境・化学工学科")

    assert "groups_deleted" in res
    assert "dp_deleted" in res
    assert session.run.call_count == 2


def test_load_courses(mock_driver, sample_courses_data, tmp_path: Path):
    """Should load course details in batches and invoke professor/department/faculty queries."""
    driver, session = mock_driver
    courses_file = tmp_path / "courses_detail.json"
    courses_file.write_text(json.dumps(sample_courses_data), encoding="utf-8")

    loader = Neo4jCurriculumLoader(driver=driver)
    summary = loader.load_courses(session, courses_path=courses_file, batch_size=1)

    assert summary["courses_total"] == 2
    assert summary["courses_loaded"] == 2
    # 2 batches * 4 queries (course, professors, departments, faculties) = 8 queries
    assert session.run.call_count == 8


def test_load_curriculum_groups(mock_driver, sample_tree_data, tmp_path: Path):
    """Should load CourseGroups, DiplomaPolicies, prerequisite edges, DP edges, and memberships."""
    driver, session = mock_driver
    tree_file = tmp_path / "curriculum_group_graph.json"
    tree_file.write_text(json.dumps(sample_tree_data), encoding="utf-8")

    loader = Neo4jCurriculumLoader(driver=driver)
    summary = loader.load_curriculum_groups(session, tree_path=tree_file)

    assert summary["groups_loaded"] == 2
    assert summary["dp_loaded"] == 1
    assert summary["prerequisites_loaded"] == 1
    assert summary["dp_contributions_loaded"] == 1
    assert summary["memberships_loaded"] == 2

    # Verify session.run calls for each of the 5 queries
    assert session.run.call_count == 5


def test_load_all(mock_driver, sample_tree_data, sample_courses_data, tmp_path: Path):
    """Should coordinate constraints, courses, and curriculum groups and return GraphLoadReport."""
    driver, session = mock_driver
    tree_file = tmp_path / "curriculum_group_graph.json"
    tree_file.write_text(json.dumps(sample_tree_data), encoding="utf-8")

    courses_file = tmp_path / "courses_detail.json"
    courses_file.write_text(json.dumps(sample_courses_data), encoding="utf-8")

    loader = Neo4jCurriculumLoader(driver=driver)
    report = loader.load_all(
        tree_path=tree_file,
        courses_path=courses_file,
        batch_size=500,
        clear_first=False,
    )

    assert isinstance(report, GraphLoadReport)
    assert report.courses_loaded == 2
    assert report.groups_loaded == 2
    assert report.dp_loaded == 1
    assert report.prerequisites_loaded == 1
    assert report.dp_contributions_loaded == 1
    assert report.memberships_loaded == 2
    assert report.elapsed_seconds >= 0.0


def test_file_not_found(mock_driver, tmp_path: Path):
    """Should raise FileNotFoundError when files are missing."""
    driver, session = mock_driver
    loader = Neo4jCurriculumLoader(driver=driver)

    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        loader.load_courses(session, courses_path=missing)

    with pytest.raises(FileNotFoundError):
        loader.load_curriculum_groups(session, tree_path=missing)


def test_verify_check_all_mocked(monkeypatch):
    """Should run check_all with mocked Neo4j and PostgreSQL and return True."""
    from src.loaders.graph import verify_graph

    # Mock Neo4j driver and session
    mock_neo4j_driver = MagicMock()
    mock_session = MagicMock()
    mock_neo4j_driver.session.return_value.__enter__.return_value = mock_session

    def fake_neo4j_run(query, **kwargs):
        mock_result = MagicMock()
        if "CourseGroup" in query:
            mock_result.single.return_value = {"cnt": 18}
        elif "DiplomaPolicy" in query:
            mock_result.single.return_value = {"cnt": 3}
        elif "PREREQUISITE_FOR" in query:
            mock_result.single.return_value = {"cnt": 22}
        elif "CONTRIBUTES_TO" in query:
            mock_result.single.return_value = {"cnt": 3}
        elif "c.syllabus_id IS NOT NULL" in query:
            if "RETURN c.syllabus_id" in query:
                return [{"sid": "162242"}]
            mock_result.single.return_value = {"cnt": 1029}
        elif "RETURN count(c)" in query:
            mock_result.single.return_value = {"cnt": 1029}
        else:
            mock_result.single.return_value = {"cnt": 10}
        return mock_result

    mock_session.run.side_effect = fake_neo4j_run
    monkeypatch.setattr(verify_graph, "get_neo4j_driver", lambda: mock_neo4j_driver)

    # Mock PostgreSQL connection and cursor
    mock_pg_conn = MagicMock()
    mock_cur = MagicMock()
    mock_pg_conn.__enter__.return_value = mock_pg_conn
    mock_pg_conn.cursor.return_value.__enter__.return_value = mock_cur

    mock_cur.fetchone.side_effect = [
        {"total": 1029},
        {"distinct_sids": 1029},
        {"found": 1},
    ]
    monkeypatch.setattr(verify_graph, "get_connection", lambda: mock_pg_conn)

    passed = verify_graph.check_all()
    assert passed is True


def test_verify_check_course_mocked(monkeypatch, capsys):
    """Should inspect a single course in both Neo4j and PostgreSQL."""
    from src.loaders.graph import verify_graph

    mock_neo4j_driver = MagicMock()
    mock_session = MagicMock()
    mock_neo4j_driver.session.return_value.__enter__.return_value = mock_session

    mock_record = {
        "c": {
            "name": "ユニットオペレーションⅠ",
            "syllabus_id": "162242",
            "course_code": "055060",
            "timetable_code": "64214",
            "credits": 2.0,
            "semester": "春",
        },
        "group_id": "G_2Y_UnitOp",
        "group_label": "【ユニットオペレーション】",
        "prereq_groups": ["【化学工学基礎】"],
        "professors": ["荒木 貞夫"],
        "faculties": ["環境都市工学部"],
        "departments": ["E01"],
    }
    mock_session.run.return_value.single.return_value = mock_record
    monkeypatch.setattr(verify_graph, "get_neo4j_driver", lambda: mock_neo4j_driver)

    mock_pg_conn = MagicMock()
    mock_cur = MagicMock()
    mock_pg_conn.__enter__.return_value = mock_pg_conn
    mock_pg_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        "syllabus_id": "162242",
        "course_code": "055060",
        "subject_name": "ユニットオペレーションⅠ",
        "credits": 2.0,
        "description": "化学工学の基礎",
        "schedule_raw": [{"session": 1}],
    }
    monkeypatch.setattr(verify_graph, "get_connection", lambda: mock_pg_conn)

    verify_graph.check_course("162242")
    captured = capsys.readouterr().out
    assert "Cross-DB Join Confirmed" in captured
    assert "162242" in captured

