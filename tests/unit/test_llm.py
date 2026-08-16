"""LLMClient.complete() 실제 HTTP 연동 + 안전 fallback 검증 테스트.

OpenAI 호환 Chat Completions API 호출을 requests 로 모킹하여 검증한다.

검증 대상:
- test_complete_success: 200 + 가짜 content 반환 시 content 를 그대로 돌려주는지.
- test_complete_api_key_missing_fallback: api_key=None → 요청 미호출 + "[LLM_UNAVAILABLE]" 폴백.
- test_complete_network_error_fallback: 요청 예외 → "[LLM_UNAVAILABLE]" 폴백 + 예외 전파 안 됨.

요구사항은 사실 기반이며, 긍정 케이스는 반환값/호출 인자 비교로, 부정/예외 케이스는
폴백 문자열 포함 여부와 예외 비전파(no raise)로 검증한다.
"""

from unittest.mock import MagicMock, patch

from core.llm import LLMClient


def _fake_response(content: str = "Hello from LLM") -> MagicMock:
    """requests.post 가 돌려줄 200 응답 객체를 모킹한다.

    OpenAI 호환 응답 형태(choices[0].message.content)를 담는다.
    """
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def test_complete_success() -> None:
    """200 응답의 choices[0].message.content 를 손실 없이 반환한다.

    동시에 requests.post 가 올바른 엔드포인트/헤더/바디/timeout 으로
    호출되었는지 검증한다(실제 호출 계약 보존).
    """
    client = LLMClient(provider="openai", model="gpt-4o", api_key="sk-test")

    with patch("core.llm.requests.post", return_value=_fake_response()) as mock_post:
        result = client.complete("What is 2+2?")

    # 실제 content 가 그대로 반환되는지(핵심 계약).
    assert result == "Hello from LLM"

    # POST 호출 인자 검증 — 안전 fallback 이 아닌 실제 호출 경로 사용 확인.
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.openai.com/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["timeout"] == 30

    body = kwargs["json"]
    assert body["model"] == "gpt-4o"
    assert body["messages"] == [{"role": "user", "content": "What is 2+2?"}]
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 1024


def test_complete_api_key_missing_fallback() -> None:
    """api_key=None 이면 requests.post 를 호출하지 않고 폴백 문자열을 반환한다.

    폴백은 "[LLM_UNAVAILABLE]" 로 구분되어야 하며, 네트워크 호출이
    발생하지 않아야 한다(비용/예외 차단).
    """
    client = LLMClient(provider="openai", model="gpt-4o", api_key=None)

    # requests.post 가 호출되면 안 되므로 side_effect 로 실패시켜 조기 감지.
    with patch(
        "core.llm.requests.post",
        side_effect=AssertionError("requests.post 는 호출되지 않아야 함"),
    ) as mock_post:
        result = client.complete("안녕")

    assert "[LLM_UNAVAILABLE]" in result
    mock_post.assert_not_called()


def test_complete_network_error_fallback() -> None:
    """requests.post 가 예외를 던지면 폴백 문자열을 반환하고 예외를 전파하지 않는다.

    네트워크 실패 시에도 complete() 는 호출자에게 예외를 던지지 않고
    안전 폴백("[LLM_UNAVAILABLE]" 포함)을 돌려주어야 한다.
    """
    client = LLMClient(provider="openai", model="gpt-4o", api_key="sk-test")

    with patch(
        "core.llm.requests.post", side_effect=ConnectionError("network down")
    ) as mock_post:
        # 예외가 전파되지 않아야 함 — 여기서 pytest.raises 없이 통과해야 정상.
        result = client.complete("테스트")

    assert "[LLM_UNAVAILABLE]" in result
    mock_post.assert_called_once()
