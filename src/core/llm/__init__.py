"""환경변수 기반 LLM 클라이언트(OpenAI 호환 HTTP 연동).

config/env.example 에 정의된 환경변수에서 설정을 읽는다:
- LLM_PROVIDER (기본값: openai)
- LLM_MODEL    (예: gpt-4o)
- LLM_API_KEY
- LLM_BASE_URL (기본값: https://api.openai.com/v1) — OpenAI 호환 엔드포인트 커버

complete() 는 OpenAI 호환 Chat Completions API 를 HTTP 로 호출한다.
api_key 가 없거나 네트워크/파싱 실패 시 안전 폴백 문자열("[LLM_UNAVAILABLE]" 접두)
을 반환하며 예외를 전파하지 않는다. python-dotenv(.env) 로드를 시도하되,
미설치 시 무시한다.
"""

from __future__ import annotations

import logging
import os

import requests

# 모듈 레벨 로거 — 호출 실패 추적용(print 금지 원칙).
logger = logging.getLogger(__name__)

# .env 로드 시도 — python-dotenv 가 없으면 무시(예외 발생 안 함).
try:
    from dotenv import load_dotenv

    load_dotenv()  # .env 파일이 없으면 아무 동작도 하지 않음
except ImportError:
    pass


class LLMClient:
    """환경변수 기반 LLM 클라이언트(OpenAI 호환 HTTP).

    Attributes:
        provider: LLM 제공자(예: openai, anthropic). base_url 로 결정되는
            OpenAI 호환 엔드포인트면 provider 값과 무관하게 동작한다.
        model: 모델명(미설정 시 기본 "gpt-4o").
        api_key: API 키(미설정 시 None → 안전 폴백).
        base_url: OpenAI 호환 API 베이스 URL(기본 https://api.openai.com/v1).
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        # 환경변수는 호출 시점에 읽는다. def-time 기본값(os.getenv 기본인자)으로 두면
        # import 시점에 값이 고정되어 이후 env 변경이 반영되지 않는다.
        # 환경변수명은 config/env.example 과 일치: LLM_PROVIDER/LLM_MODEL/LLM_API_KEY/LLM_BASE_URL
        # 명시적 인자가 None 이면 env 에서 읽고, 그것도 없으면 provider 기본값 "openai".
        self.provider: str = (
            provider if provider is not None else os.getenv("LLM_PROVIDER", "openai")
        )
        self.model: str | None = model if model is not None else os.getenv("LLM_MODEL")
        self.api_key: str | None = api_key if api_key is not None else os.getenv("LLM_API_KEY")
        # base_url 도 동일 원칙: 명시 인자 우선, 미설정 시 env(기본 OpenAI).
        # provider 가 "openai" 가 아니어도 base_url 로 결정되므로 호환 엔드포인트 커버.
        self.base_url: str = (
            base_url
            if base_url is not None
            else os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        )

    def complete(self, prompt: str) -> str:
        """프롬프트에 대한 LLM 응답을 반환한다(OpenAI 호환 HTTP).

        POST {base_url}/chat/completions 를 호출하여
        choices[0].message.content 를 추출해 반환한다.

        안전 fallback: api_key 가 없거나 네트워크/HTTP/JSON 파싱 실패 시 로거 경고 후
        "[LLM_UNAVAILABLE]" 접두 폴백 문자열을 반환하며, 예외를 전파하지 않는다
        (호출자가 예외로부터 안전해야 하는 계약).

        Args:
            prompt: LLM 에 전달할 프롬프트 문자열.

        Returns:
            LLM 응답 텍스트 또는 안전 폴백 문자열.
        """
        # api_key 누락은 즉시 폴백 — 네트워크 호출을 차단(비용/예외 방지).
        if not self.api_key:
            logger.warning("LLM_API_KEY 미설정 — 안전 폴백 반환")
            return f"[LLM_UNAVAILABLE] api_key 없음: {prompt[:50]}..."

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model or "gpt-4o",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
                timeout=30,
            )
            # HTTP 오류 상태(401/429/500 등)도 예외로 바꿔 안전 폴백 경로로 유도.
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:  # BLE001 허용: 안전 fallback 목적 broad except
            logger.warning("LLM 호출 실패 — 안전 폴백 반환: %s", exc)
            return f"[LLM_UNAVAILABLE] {prompt[:50]}... (오류: {type(exc).__name__})"
