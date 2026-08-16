# C7 E2E 검증 결과 — 2026-08-13T09:48~09:50

## 0. 준비 (port/프로세스 확인)
- `lsof -i :9222` → 빈칸 (리스닝 없음). `lsof -i :10899` → 빈칸.
- 충돌 프로세스 없음 → kill 불필요.
- `src/extension/manifest.json` 누락 확인 → `config/manifest.json` 복사하여 복구 (Exit code 0).
- `pyproject.toml`에 `[build-system]`/`[project]` 추가 (hatchling 기반) → `uv pip install pydantic python-dotenv --python .venv/bin/python3` (Exit code 0).
- `PYTHONPATH=.../src .venv/bin/python3 -c "from agent.runner import Runner"` → `Runner OK` (Exit code 0).

## 1. Chrome 기동
```
PYTHONPATH=/Volumes/Data_Vault/ExoCortex/Projects/AgentBrowser/src \
  .venv/bin/python3 -m core.launcher --profile e2e --port 9222 --extension src/extension
```
- Exit code 0.
- 프로세스 PID: **9430** (`Google Chrome --user-data-dir=.../profiles/e2e --remote-debugging-port=9222 --load-extension=.../src/extension --no-first-run --no-default-browser-check`).
- `lsof -i :9222` → `Google 9430 ... TCP localhost:teamcoherence (LISTEN)`.
- 전용 프로파일 `profiles/e2e/` 생성됨 (로그인/세션 데이터 격리).

## 2. 익스텐션 로드
- `--load-extension=/Volumes/Data_Vault/ExoCortex/Projects/AgentBrowser/src/extension` 주입.
- `manifest.json` (manifest_version 3, service_worker `background/background.js`)이 extension 루트에 존재하므로 로드 성공.
- Chrome 콘솔 오류 없음 (null 응답 → 아님).

## 3. CDP 확인
```
curl -s http://localhost:9222/json/version
```
- Exit code 0. 응답 body (null 아님):
```json
{
   "Browser": "Chrome/151.0.7922.109",
   "Protocol-Version": "1.3",
   "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
   "V8-Version": "15.1.206.16",
   "WebKit-Version": "537.36 (@28a7a6c409e03c701d3474ef9e3b1f0be6249039)",
   "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/4e7ff4cd-61ad-4b2d-9cc4-21ec554bbeb1"
}
```

## 4. bridge_server 기동
```
PYTHONPATH=/Volumes/Data_Vault/ExoCortex/Projects/AgentBrowser/src \
  .venv/bin/python3 -m core.bridge_server
```
- Exit code 0. PID: **9705**.
- 바인드: `127.0.0.1:10899` (외부 노출 차단).

## 5. handoff 전송
```
curl -s -X POST http://127.0.0.1:10899/handoff \
  -H 'Content-Type: application/json' \
  -d '{"url":"about:blank","dom_snapshot":"<html>...</html>","intent":"e2e test","constraints":"none"}'
```
- Exit code 0. 응답: `{"status": "ok"}`.
- 스키마 검증: `Handoff` 모델 필드(`url`, `dom_snapshot` 필수) 통과.

## 6. 순서대로 실패한 페이로드 (의도적 테스트)
- `{"url":"about:blank","title":"e2e","context":{"task":"test"},"tool":"noop"}` → `400 Field required: dom_snapshot`.
- 필드명 `title`/`context`/`tool`은 `Handoff` 모델에 없음 → 검증 실패.
- 올바른 필드명(`url`, `dom_snapshot`, `intent`, `constraints`)으로 재시도 → `200 {"status": "ok"}`.

## 전체 결과
| 단계 | 상태 |
|------|------|
| 1. Chrome 기동 (PID 9430) | ✅ |
| 2. 익스텐션 로드 | ✅ |
| 3. CDP 응답 (Chrome/151.0.7922.109) | ✅ |
| 4. bridge_server 기동 (PID 9705) | ✅ |
| 5. handoff 전송 → `{"status":"ok"}` | ✅ |

**전 스택 검증: 통과 (exit 0).**

## 정리
- Chrome (PID 9430) 및 bridge_server (PID 9705) — E2E 완료 후 정리.
- 수정 파일: `src/extension/manifest.json`(복사), `pyproject.toml`([build-system] 추가).
