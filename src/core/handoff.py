"""핸드오프 스키마 (Handoff schema).

AgentBrowser R3(인간→에이전트 위임)과 R6(HITL 캡차 위임)의 데이터 contract를
pydantic v2 모델로 정의한다. design doc §3(핸드오프 스키마) 필드에 부합하도록
구성하되, JS→Python 전송 경로를 고려해 다음과 같이 타입을 확정한다:

- ``dom_snapshot``: 원본 §3 JSON 초안에서는 object 였으나, 크롬 익스텐션(JS)이
  ``chrome.runtime``/IPC 로 전송할 때는 JSON 직렬화된 문자열(str)로 수신된다.
  파싱은 agent/tools 계층에서 수행하므로 수신 단계에서는 str로 보관한다.
- ``constraints``: 원본 초안에서는 string 배열([string])이었으나, 본 위임의
  제약 표현은 단일 자연어 문자열(str)로 충분하므로 str로 확정한다.
- ``timestamp``: ISO8601 문자열이 아닌 파싱된 ``datetime`` 객체로 보관하여
  런타임 검증과 정렬을 용이하게 한다.
- ``version``: 스키마 버전을 기록하여 후속 contract 확장 시 하위 호환을 보장한다.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Handoff(BaseModel):
    """인간→에이전트 위임 핸드오프 페이로드 (R3).

    크롬 익스텐션이 캡처한 페이지 컨텍스트를 Python 계층(core/agent)으로
    위임할 때 사용하는 데이터 모델이다.
    """

    # 위임 대상 페이지의 URL.
    url: str

    # JS에서 전송되는 JSON 직렬화된 DOM 스냅샷 문자열.
    # 파싱은 agent/tools 계층에서 수행한다.
    dom_snapshot: str

    # 작업 의도. 미지정 시 빈 문자열.
    intent: str = ""

    # 위임 제약(예: "로그인 금지", "개인정보 입력 안 함"). 미지정 시 빈 문자열.
    constraints: str = ""

    # 핸드오프 생성 시각. 기본값은 인스턴스 생성 시점.
    timestamp: datetime = Field(default_factory=datetime.now)

    # 스키마 버전 기록 (하위 호환 보장용).
    version: str = "1.0"


class HITLRequest(BaseModel):
    """인간 개입(Human-In-The-Loop) 요청 페이로드 (R6 캡차 위임 등).

    에이전트가 자동 처리 불가한 상황(예: 캡차 탐지)을 인간에게 넘길 때
    사용하는 데이터 모델이다.
    """

    # 개입이 필요한 페이지의 URL.
    url: str

    # 개입 사유 (예: "captcha_detected").
    reason: str

    # 요청 생성 시각. 기본값은 인스턴스 생성 시점.
    timestamp: datetime = Field(default_factory=datetime.now)
