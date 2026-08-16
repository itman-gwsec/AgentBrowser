"""세션 로그 모듈 테스트 (tests/unit/test_session_log.py).

검증 대상(src/core/session_log.py):
    - ``SearchLogEntry`` (pydantic v2) 필드 구성.
    - ``SessionLog`` 의 append / recent / duplicate_query_ratio 동작.
    - 기본 로그 경로(log_path=None) 사용/생성.

TDD 컨벤션: 실제 파일 I/O 는 tmp_path 로 격리. pytest + pydantic v2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.session_log import SearchLogEntry, SessionLog


def test_append_and_recent(tmp_path: Path) -> None:
    """tmp_path 에 SessionLog 를 만들고 entry 3건 append → recent(10) 가 3건, 순서 유지."""
    log_path = tmp_path / "logs" / "search_session.jsonl"
    log = SessionLog(log_path=str(log_path))

    # 동일 엔진/쿼리로 3건 순차 기록.
    log.append(SearchLogEntry(engine="duckduckgo", query="a", results_count=2))
    log.append(SearchLogEntry(engine="duckduckgo", query="b", results_count=3))
    log.append(SearchLogEntry(engine="google", query="c", results_count=1))

    recent = log.recent(10)

    # 최근 10건 요청 → 기록된 3건 전체 반환.
    assert len(recent) == 3
    # 원본 순서 유지 (query 순서 a→b→c).
    assert [e.query for e in recent] == ["a", "b", "c"]
    # 필드 보존 확인.
    assert recent[0].engine == "duckduckgo"
    assert recent[2].results_count == 1
    # 실제 파일 1행/JSON 확인 (ensure_ascii=False 로 한글 보존).
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    # JSONL 1행 파싱 성공.
    parsed = json.loads(lines[0])
    assert parsed["query"] == "a"
    assert parsed["engine"] == "duckduckgo"


def test_duplicate_query_ratio(tmp_path: Path) -> None:
    """query ['a','a','b'] 3건 → 중복('a' 2건) 비율 = 2/3."""
    log_path = tmp_path / "logs" / "search_session.jsonl"
    log = SessionLog(log_path=str(log_path))

    for q in ["a", "a", "b"]:
        log.append(SearchLogEntry(engine="duckduckgo", query=q, results_count=1))

    # 'a' 가 2건 중복 → 중복 entry 수 2 / 전체 3 = 2/3.
    ratio = log.duplicate_query_ratio(window=20)
    assert abs(ratio - 2 / 3) < 1e-9

    # window 를 2로 좁히면 최근 ['a','b'] → 중복 없음 → 0.0.
    assert log.duplicate_query_ratio(window=2) == 0.0

    # 항목이 없으면 0.0.
    empty = SessionLog(log_path=str(tmp_path / "empty.jsonl"))
    assert empty.duplicate_query_ratio() == 0.0


def test_log_path_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """log_path=None 이면 기본 logs/ 경로를 사용하고 부모 디렉터리를 생성한다.

    ``SessionLog.__init__`` 은 프로젝트 루트/logs/search_session.jsonl 을
    기본값으로 삼는다. 실제 프로젝트 루트 오염을 막기 위해 __file__ 기준
    루트 계산을 tmp_path 로 대체하여 검증한다.
    """
    # src/core/session_log.py 위치 흉내: tmp_path/src/core/session_log.py
    fake_module = tmp_path / "src" / "core" / "session_log.py"
    fake_module.parent.mkdir(parents=True, exist_ok=True)
    fake_module.touch()
    # Path(__file__).resolve().parents[2] 가 tmp_path 가 되도록 패치.
    monkeypatch.setattr(
        "core.session_log.Path",
        lambda p=None: Path(tmp_path / "src" / "core" / "session_log.py")
        if p == __file__
        else Path(p) if p is not None else Path(),
    )

    log = SessionLog()  # log_path=None → 기본 경로

    # 기본 경로가 logs/ 디렉터리 아래 search_session.jsonl 이다.
    assert log.log_path.name == "search_session.jsonl"
    assert log.log_path.parent.name == "logs"
    # 부모 디렉터리가 실제로 생성되었는지 확인.
    assert log.log_path.parent.exists()
    assert log.log_path.parent.is_dir()
