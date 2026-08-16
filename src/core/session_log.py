"""장기 세션 패턴 학습용 검색 로그 모듈 (Search session logging).

서버측 패턴 탐지 회피 목적: "지금까지 무엇을 검색했는지" 를 JSONL 로 누적하여,
같은 쿼리 반복·비정상 간격 등을 후속 로직에서 판단할 수 있게 한다.

설계 제약 (개발 원칙):
- pydantic v2 모델로 항목 직렬화 (typing·OOP 표준, 한국어 주석, snake_case).
- print 금지 — logger 사용.
- 기본 로그 경로는 프로젝트 루트/logs/search_session.jsonl.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

# 모듈 전역 로거 (print 금지, 일관성 유지).
logger = logging.getLogger(__name__)

# 중복 판단 기준: 동일 query 가 이 횟수 이상 등장하면 '중복' 으로 간주.
DUP_QUERY_MIN_OCCURRENCES: int = 2


class SearchLogEntry(BaseModel):
    """단일 검색 로그 항목 (pydantic v2).

    - timestamp: 검색 시각 (기본값 현재 시각, ISO 직렬화).
    - engine: 사용 검색 엔진 (예: "duckduckgo").
    - query: 검색어.
    - url: 결과 페이지 URL.
    - results_count: 추출된 결과 수 (기본 0).
    - click_depth: 클릭 시뮬레이션 깊이 (기본 0).
    - session_gap_s: 이번 검색 전 대기한 세션 간격(초), 없으면 None.
    """

    # 검색 발생 시각 — default_factory 로 항목 기록 시점 시각을 주입.
    timestamp: datetime = Field(default_factory=datetime.now)
    # 사용 엔진 명칭.
    engine: str
    # 검색어.
    query: str
    # 결과 페이지 URL (meta 에서 추출, 미확보 시 빈 문자열).
    url: str = ""
    # 추출된 결과 링크 수 (기본 0, 미확보 시 -1 로 표시 가능).
    results_count: int = 0
    # 인간유사 클릭 부수효과 깊이 (기본 0).
    click_depth: int = 0
    # 직전 세션 간격(초) — 연속 검색 패턴 판단 지표, 없으면 None.
    session_gap_s: float | None = None


class SessionLog:
    """검색 로그 JSONL 누적기 (OOP 표준, logger 사용, print 금지).

    검색 성공 시마다 1행(JSON)을 append 하고, 후속 로직이 최근 기록을
    읽어 중복 쿼리 비율 등을 산출할 수 있게 한다.
    """

    def __init__(self, log_path: str | None = None) -> None:
        """로그 경로를 결정한다.

        미지정 시 프로젝트 루트/logs/search_session.jsonl 을 기본값으로 사용하며,
        부모 디렉터리가 없으면 생성한다.

        Args:
            log_path: 로그 파일 경로. None 이면 기본 logs 경로 사용/생성.
        """
        if log_path is None:
            # src/core/session_log.py → parents[2] = 프로젝트 루트.
            root = Path(__file__).resolve().parents[2]
            self.log_path = root / "logs" / "search_session.jsonl"
        else:
            self.log_path = Path(log_path)
        # 부모 디렉터리 없으면 생성 (ensure directory).
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("SessionLog 초기화 (path=%s)", self.log_path)

    def append(self, entry: SearchLogEntry) -> None:
        """JSONL 형식으로 1행 append 한다 (ensure_ascii=False).

        Args:
            entry: 기록할 검색 로그 항목 (pydantic v2 모델).
        """
        # pydantic v2 기본 ensure_ascii=True 이므로 명시적으로 False 지정(한글 보존).
        line = entry.model_dump_json(ensure_ascii=False)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        logger.debug("검색 로그 1행 기록 (engine=%s, query=%r)", entry.engine, entry.query)

    def recent(self, n: int = 10) -> list[SearchLogEntry]:
        """최근 n개 항목을 반환한다 (파일을 읽어 파싱).

        Args:
            n: 반환할 최근 항목 수 (기본 10).

        Returns:
            최근 n개의 SearchLogEntry 리스트 (원본 순서 유지). 파일 없으면 [].
        """
        if not self.log_path.exists():
            return []
        entries: list[SearchLogEntry] = []
        with self.log_path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    # 손상된 행은 무시(안전 fallback) — 로그 무결성에 영향 없음.
                    logger.debug("손상된 로그 행 무시: %r", line[:80])
                    continue
                try:
                    entries.append(SearchLogEntry(**data))
                except Exception:
                    logger.debug("로그 항목 파싱 실패 — 무시")
                    continue
        # 최근 n개만 (원본 순서 유지).
        return entries[-n:]

    def duplicate_query_ratio(self, window: int = 20) -> float:
        """최근 window 건 중 query 가 2회 이상 등장한 비율을 반환한다 (0.0~1.0).

        비율 = (중복된 query 를 가진 entry 수) / (전체 entry 수).
        서버측 패턴 탐지 지표: 같은 쿼리 반복 여부 판단용.

        Args:
            window: 최근 확인 범위 건수 (기본 20).

        Returns:
            중복 query 비율 (0.0 ~ 1.0). 항목이 없으면 0.0.
        """
        entries = self.recent(window)
        if not entries:
            return 0.0
        counts = Counter(e.query for e in entries)
        # 기준 횟수 이상 등장한 query 가 가진 entry 수 합산.
        dup_count = sum(c for c in counts.values() if c >= DUP_QUERY_MIN_OCCURRENCES)
        return dup_count / len(entries)
