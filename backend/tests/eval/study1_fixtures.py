"""Study 1 の分析の道具のテストで使う、合成の科目と研究のイベント（人のデータは使わない）。

科目の名前はカード（事前登録 3.1・3.2）の科目名を使い、syllabus_id・曜限・単位は架空。イベントの形は
course_core.research.store の封筒と、frontend の payload（diagnose.ts の planPayload、PlanAi.tsx の plan_refine_decide、
studyFlow.ts の questionnaire_submit など）に合わせた。
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from course_core.research.events import flags_digest
from course_core.research.variants import VARIANTS
from eval.study1.catalog_snapshot import CourseCatalog, CourseInfo, fingerprint

JST = timezone(timedelta(hours=9))
STUDY_ID = "study1-diag-ab-202611"
CONSENT = "v1-diag-ab-202611"
CONFIG_VERSION = "2026-11-07-2"

# (syllabus_id, 名前, 単位, 学期, 配当年次の下限, 曜限, まとまり)
_COURSES: list[tuple[str, str, float | None, str | None, int, tuple[str, ...], str | None]] = [
    # 1年春（K5 の8科目と別クラス、教養）
    ("s01", "化学工学量論及び演習", 2.0, "春", 1, ("火1",), "G_1Y_ChemEng"),
    ("s02", "入門エネルギー環境学", 2.0, "春", 1, ("火2",), "G_1Y_ChemEng"),
    ("s03", "物理を学ぶ（力学１）", 2.0, "春", 1, ("火3",), None),
    ("s03b", "物理を学ぶ（力学１）", 2.0, "春", 1, ("水3",), None),
    ("s04", "基礎からの情報処理", 2.0, "春", 1, ("月1",), None),
    ("s04b", "基礎からの情報処理", 2.0, "春", 1, ("金1",), None),
    ("s05", "線形代数１", 2.0, "春", 1, ("水2",), None),
    ("s06", "情報処理演習", 2.0, "春", 1, ("水1",), "InfoExercise"),
    ("s07", "化学を学ぶ（基礎化学）", 2.0, "春", 1, ("木3",), None),
    ("s08", "フレッシュマンゼミナール", 2.0, "春", 1, ("木5",), "FreshmanSeminar"),
    ("e01", "自然災害の科学", 2.0, "春", 1, ("火5",), None),
    ("e02", "健康・スポーツ科学実習ａ（ソフトボール）", 1.0, "春", 1, ("木2",), None),
    ("e05", "集中の教養", 2.0, "春", 1, (), None),  # 曜限「他」
    # 1年秋
    ("a01", "プロセス量論及び演習", 2.0, "秋", 1, ("火1",), None),
    ("a02", "無機化学", 2.0, "秋", 1, ("火2",), None),
    ("a03", "線形代数２", 2.0, "秋", 1, ("水2",), None),
    ("a04", "入門化学結合論", 2.0, "秋", 1, ("金2",), None),
    ("a05", "化学実験", 2.0, "秋", 1, ("月4", "月5"), None),
    ("a05b", "化学実験", 2.0, "秋", 1, ("木4", "木5"), None),
    ("a06", "物理学実験", 2.0, "秋", 1, ("水4", "水5"), None),
    ("a07", "物理を学ぶ（電磁気学１）", 2.0, "秋", 1, ("木2",), None),
    ("a08", "基礎からの数学２", 2.0, "秋", 1, ("金5",), None),
    ("e03", "宇宙のすがたと歴史", 2.0, "秋", 1, ("木2",), None),
    ("e04", "読書への誘い", 2.0, "秋", 1, ("金4",), None),
    ("e06", "健康・スポーツ科学実習ｂ（卓球）", 1.0, "秋", 1, ("土3",), None),
    # 3年（K1 のまとまり）
    ("g1", "架空の材料Ａ", 2.0, "春", 3, ("月1",), "G_3Y_MatEnergy"),
    ("g1b", "架空の材料Ａ", 2.0, "春", 3, ("月3",), None),  # 同じ名前の別クラス（系統図に無い）
    ("g2", "架空の材料Ｂ", 2.0, "春", 3, ("月2",), "G_3Y_MatEnergy"),
    ("g3", "架空の材料Ｃ", 2.0, "秋", 3, ("月1",), "G_3Y_MatEnergy"),
    ("g4", "架空の材料Ｄ", 2.0, "秋", 3, ("月2",), "G_3Y_MatEnergy"),
    ("o1", "架空の有機Ａ", 2.0, "春", 3, ("火1",), "G_3Y_OrgCatal"),
    ("o2", "架空の有機Ｂ", 2.0, "秋", 3, ("火1",), "G_3Y_OrgCatal"),
    ("o3", "架空の有機Ｃ", 2.0, "秋", 3, ("火2",), "G_3Y_OrgCatal"),
    ("y1", "架空の通年", 2.0, "通年", 1, ("土1",), None),
]


def course_infos() -> list[CourseInfo]:
    return [
        CourseInfo(
            syllabus_id=sid,
            name=name,
            credits=credits,
            year_min=year,
            year_max=4,
            term=term,
            slots=slots,
            slot_note=None if slots else "他",
            group_id=group,
        )
        for sid, name, credits, term, year, slots, group in _COURSES
    ]


def course_catalog() -> CourseCatalog:
    courses = {c.syllabus_id: c for c in course_infos()}
    return CourseCatalog("kansai-enechem-2026", "test", courses, fingerprint(courses.values()), "test")


def catalog_json() -> dict[str, Any]:
    courses = course_infos()
    return {
        "format": "study1-catalog-v1",
        "department_id": "kansai-enechem-2026",
        "data_version": "test",
        "fingerprint": fingerprint(courses),
        "courses": [c.row() for c in courses],
        "groups": [],
    }


def write_catalog(path: Path) -> Path:
    path.write_text(json.dumps(catalog_json(), ensure_ascii=False), encoding="utf-8")
    return path


def plan(**terms: Sequence[str]) -> list[dict[str, Any]]:
    """plan(y1s=[...], y1a=[...], y3s=[...], y3a=[...]) → planPayload の形。"""
    keys = {"y1s": (1, "春"), "y1a": (1, "秋"), "y2s": (2, "春"), "y2a": (2, "秋"), "y3s": (3, "春"), "y3a": (3, "秋")}
    return [{"year": keys[k][0], "term": keys[k][1], "syllabus_ids": list(v)} for k, v in terms.items()]


# P1 の初期プラン（K2: 月1・月4/月5、K3: 1年春 19 単位、K4: 電磁気学１が無い → 満たさない3つ）
P1_INITIAL = plan(
    y1s=["s01", "s02", "s03b", "s04", "s05", "s06", "s07", "s08", "e01", "e02"],
    y1a=["a01", "a02", "a03", "a04", "a05", "a06", "e03", "e04", "e06"],
    y3s=["g1", "g2"],
    y3a=["g3", "g4"],
)
# P1 の全部を満たすプラン（情報処理と化学実験を別クラスへ、電磁気学１を足すため木2 の教養を外す、単位を合わせる）
P1_SOLVED = plan(
    y1s=["s01", "s02", "s03b", "s04b", "s05", "s06", "s07", "s08", "e02"],
    y1a=["a01", "a02", "a03", "a04", "a05b", "a06", "a07", "e04", "e06"],
    y3s=["g1", "g2"],
    y3a=["g3", "g4"],
)
P2_INITIAL = plan(
    y1s=["s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "e02"],
    y1a=["a01", "a02", "a03", "a04", "a05", "a06", "e04", "e06"],
    y3s=["o1"],
    y3a=["o2", "o3"],
)
P2_SOLVED = plan(
    y1s=["s01", "s02", "s03b", "s04", "s05", "s06", "s07", "s08", "e02"],
    y1a=["a01", "a02", "a03", "a04", "a05", "a06", "a08", "e04", "e06"],
    y3s=["o1"],
    y3a=["o2", "o3"],
)
REFERENCE = {
    "P1": {
        "future": ["energy"],
        "style": ["lab"],
        "worry": ["math"],
        "liberal": ["nature"],
        "avoid": ["none"],
        "freeday": ["mon"],
    },
    "P2": {
        "future": ["organic"],
        "style": ["talk"],
        "worry": ["chem"],
        "liberal": ["culture"],
        "avoid": ["none"],
        "freeday": ["none"],
    },
    "practice": {
        "future": ["plant"],
        "style": ["calc"],
        "worry": ["none"],
        "liberal": ["data"],
        "avoid": ["none"],
        "freeday": ["none"],
    },
}
INITIAL = {"P1": P1_INITIAL, "P2": P2_INITIAL, "practice": P1_INITIAL}
SOLVED = {"P1": P1_SOLVED, "P2": P2_SOLVED, "practice": P1_SOLVED}
DIGEST = {"P1": "sha256:p1", "P2": "sha256:p2", "practice": "sha256:c"}
# 系列 → ((ブロック1の記号, 変種, セット), (ブロック2 …))。練習はブロック1の変種
SEQUENCES = {
    "Q1": (("W", "V30", "P1"), ("Y", "V31", "P2")),
    "Q2": (("Y", "V31", "P1"), ("W", "V30", "P2")),
    "Q3": (("W", "V30", "P2"), ("Y", "V31", "P1")),
    "Q4": (("Y", "V31", "P2"), ("W", "V30", "P1")),
}


class Builder:
    """1人のセッションのイベントを、封筒の形で順に作る。"""

    def __init__(self, pid: str, sequence_id: str, *, start: datetime | None = None, mode: str = "remote") -> None:
        self.pid = pid
        self.sequence_id = sequence_id
        self.session_id = f"sess-{pid}-0000000000000000"
        self.mode = mode
        self.clock = start or datetime(2026, 11, 12, 10, 0, tzinfo=JST)
        self.seq = 0
        self.block: int | None = None
        self.condition: str | None = None
        self.variant: str | None = None
        self.lines: list[dict[str, Any]] = []
        self.consent: str | None = None
        self._ids = 0

    def _id(self) -> str:
        self._ids += 1
        return f"{self.pid}-ev-{self._ids:04d}"

    def _envelope(self, event_type: str, origin: str, payload: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
        flags = VARIANTS[self.variant].model_dump() if self.variant else None
        return {
            "schema_version": "1.0",
            "event_id": self._id(),
            "event_type": event_type,
            "origin": origin,
            "ts_client": None,
            "ts_server": self.clock.isoformat(timespec="milliseconds"),
            "seq": None,
            "pid": self.pid,
            "session_id": self.session_id,
            "sequence_id": self.sequence_id,
            "study_id": STUDY_ID,
            "arm": "diag",
            "condition_id": self.condition,
            "variant_id": self.variant,
            "flags": flags,
            "flags_version": "2",
            "block": self.block,
            "task_id": None,
            "app_version": {"frontend": "dev", "backend": "test"},
            "consent_version": self.consent,
            "mode": self.mode,
            "payload": dict(payload),
            "warnings": [],
            **extra,
        }

    def wait(self, seconds: float) -> None:
        self.clock += timedelta(seconds=seconds)

    def client(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        task_id: str | None = None,
        after: float = 5.0,
    ) -> dict[str, Any]:
        self.wait(after)
        self.seq += 1
        line = self._envelope(
            event_type,
            "client",
            payload or {},
            ts_client=self.clock.isoformat(timespec="milliseconds"),
            seq=self.seq,
            task_id=task_id,
        )
        self.lines.append(line)
        return line

    def server(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        line = self._envelope(event_type, "server", payload)
        self.lines.append(line)
        return line

    def start(self, *, consent: str = CONSENT, form_serial: str = "ONLINE") -> None:
        self.server("session_start", {"data_status": {}})
        self.consent = consent
        self.server("consent_recorded", {"consent_version": consent, "form_serial": form_serial, "agreed": True})
        self.questionnaire("事前の質問", None, {"grade": "1", "faculty": "own", "seen_before": "no"})

    def questionnaire(self, scale: str, block: int | None, values: Mapping[str, Any]) -> None:
        self.client(
            "questionnaire_submit",
            {
                "set": "ibuki_sus",
                "questionnaire": scale,
                "scale": scale,
                "scope": "block",
                "block": block,
                "version": "2026-11-10",
                "values": dict(values),
            },
        )

    def begin_block(self, block: int, condition: str, variant: str, task_set: str) -> None:
        self.block, self.condition, self.variant = block, condition, variant
        self.server("block_start", {"block": block, "condition_id": condition, "task_set_id": task_set})
        self.client(
            "variant_applied",
            {
                "block": block,
                "variant_id": variant,
                "flags_digest": flags_digest(VARIANTS[variant].model_dump()),
                "flags_version": "2",
            },
            task_id=None,
        )

    def end_block(self) -> None:
        self.server("block_end", {"block": self.block, "condition_id": self.condition, "task_set_id": None})
        self.block = self.condition = self.variant = None

    def diagnose(
        self, task_id: str, task_set: str, *, answers: Mapping[str, Any] | None = None, plan_value: Any = None
    ) -> None:
        self.client("task_start", {"block": self.block, "task_index": 0}, task_id=task_id)
        self.client("diag_start", {"config_version": CONFIG_VERSION, "question_count": 6}, task_id=task_id)
        self.client(
            "diag_submit",
            {"config_version": CONFIG_VERSION, "answers": dict(answers or REFERENCE[task_set])},
            task_id=task_id,
            after=60,
        )
        shown = plan_value if plan_value is not None else INITIAL[task_set]
        payload = {
            "config_version": CONFIG_VERSION,
            "answers_digest": DIGEST[task_set],
            "plan": shown,
            "course_count": 0,
        }
        self.client("plan_shown", payload, task_id=task_id, after=1)
        self.client("task_submit", {"block": self.block, "task_index": 0, **payload}, task_id=task_id, after=0)

    def edit(self, task_id: str, kind: str, syllabus_id: str, year: int, term: str, source: str, **detail: Any) -> None:
        event_type = "plan_course_add" if kind == "add" else "plan_course_remove"
        self.client(
            event_type,
            {**detail, "syllabus_id": syllabus_id, "year": year, "term": term, "from": source},
            task_id=task_id,
        )

    def refine(
        self,
        task_id: str,
        plan_value: Any,
        *,
        local_id: str,
        latency_ms: int = 12_000,
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
        error: str | None = None,
        delivery: str = "delivered",
    ) -> dict[str, Any]:
        send = self.client(
            "plan_refine_send",
            {"input": "直して", "refine_local_id": local_id, "plan": plan_value, "plan_context": True},
            task_id=task_id,
        )
        self.server(
            "chat_response",
            {
                "client_event_id": send["event_id"],
                "latency_ms": latency_ms,
                "error": error,
                "plan_delivery": "not_delivered" if error else delivery,
                "plan_suggestions": None if error else {"add": list(add), "remove": list(remove), "dropped": []},
                "cited_codes": [],
                "source_codes": [],
                "unverified_codes": [],
                "path": "static",
                "model": "test",
            },
        )
        self.wait(latency_ms / 1000)
        return send

    def decide(
        self, task_id: str, local_id: str, shown: Sequence[Mapping[str, Any]], accepted: Sequence[Mapping[str, Any]]
    ) -> None:
        rejected = [line for line in shown if line not in accepted]
        self.client(
            "plan_refine_decide",
            {
                "refine_local_id": local_id,
                "action": "apply" if accepted else "cancel",
                "shown": list(shown),
                "accepted": list(accepted),
                "rejected": rejected,
                "dropped": 0,
                "delivery": "with_context",
            },
            task_id=task_id,
        )

    def submit(self, task_id: str, plan_value: Any, *, after: float = 30.0) -> None:
        self.client(
            "task_submit",
            {"block": self.block, "task_index": 1, "plan": plan_value, "course_count": 0, "checkpoints": []},
            task_id=task_id,
            after=after,
        )

    def block_questionnaires(self, *, sus: int = 4, q11: int = 4, q12: int = 3) -> None:
        values = {f"sus{i}": (sus if i % 2 == 1 else 6 - sus) for i in range(1, 11)}
        self.questionnaire("SUS", self.block, values)
        self.questionnaire("Q11-Q12", self.block, {"q11": q11, "q12": q12, "free": "書いた文"})

    def finish(self, prefer: str = "2") -> None:
        self.questionnaire("二択", None, {"prefer": prefer, "reason": "理由の文"})
        self.questionnaire("振り返り", None, {"r1": "文", "r2": ""})
        self.client("session_end", {"reason": "completed"}, task_id=None)


def complete_participant(
    pid: str, sequence_id: str, *, start: datetime | None = None, solve: Iterable[str] = ("P1", "P2"), prefer: str = "2"
) -> Builder:
    """同意から二択まで、両ブロックで課題 b を出した1人。solve にあるセットは全部を満たすプランを出す。"""
    b = Builder(pid, sequence_id, start=start)
    b.start()
    blocks = SEQUENCES[sequence_id]
    b.begin_block(0, "P", blocks[0][1], "practice")
    b.diagnose("practice", "practice")
    b.submit("practice", P1_INITIAL)
    b.end_block()
    solved = set(solve)
    for index, (condition, variant, task_set) in enumerate(blocks, 1):
        b.begin_block(index, condition, variant, task_set)
        a_id, b_id = f"{task_set}-a", f"{task_set}-b"
        b.diagnose(a_id, task_set)
        b.client("task_start", {"block": index, "task_index": 1, "continued": True}, task_id=b_id, after=0)
        b.client("status_open", {"how": "band"}, task_id=b_id)
        final = SOLVED[task_set] if task_set in solved else INITIAL[task_set]
        b.submit(b_id, final)
        b.block_questionnaires()
        b.end_block()
    b.finish(prefer)
    return b


def write_events(path: Path, builders: Iterable[Builder], extra_lines: Iterable[str] = ()) -> Path:
    lines = [json.dumps(line, ensure_ascii=False) for builder in builders for line in builder.lines]
    path.write_text("\n".join([*lines, *extra_lines]) + "\n", encoding="utf-8")
    return path
