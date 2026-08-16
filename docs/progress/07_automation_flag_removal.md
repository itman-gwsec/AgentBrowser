# 봇 탐지 플래그(--enable-automation) 제거 및 attach 전용 런처 재구성 (2026-08-14)

> 작성 롤: analyst (R01). 모든 주장은 인용 가능 evidence 기반이며, 미검증 사항은 한계로 정직하게 분리 기록한다.

## §1. 현상 (인포바 스크린샷 사실)

- [사실] 사용자가 실제 Chrome 스크린샷에서 주소창 `about:blank` 상단에 **"Chrome이 자동화된 테스트 소프트웨어에 의해 제어되고 있습니다"** 인포바를 확인했다. 인포바 우측에 **"설정에서 사용 중지"** 버튼과 닫기(X)가 함께 노출된 상태.
- [사실] 해당 인포바는 Chrome이 `--enable-automation` 플래그로 기동될 때만 노출되는 UI다. 이 플래그는 동시에 `navigator.webdriver` 를 `true` 로 고정하므로, 대상 사이트의 JS 봇 탐지 로직이 즉시 양성(자동화 세션)으로 판정한다.

## §2. 근본 원인 (플래그 → 웹드라이버 고정 → 봇 탐지, 런처 spawn 구조)

- [사실] 기존 `src/core/launcher.py` 의 `launch_chrome()` 은 에이전트가 직접 Chrome 을 `subprocess.Popen` 으로 spawn 하는 구조였다. Playwright/CDP attach 경로에서 이 플래그가 주입되는 구조가 그 원인이다.
- [사실] 인과 고리: `launch_chrome() → subprocess.Popen(spawn) → --enable-automation 주입 → 인포바 노출 + navigator.webdriver=true → 사이트 봇 탐지 양성`. 즉 spawn 주체가 에이전트인 것이 플래그 유입의 근본 원인이다.
- [사실] 이는 `IDEA.md` R2(봇회피 = 헤드풀 + 인간유사동작) 위반이다.

## §3. 설계 결정 (spawn 금지 · attach 전용 전환, §03 원칙의 일관 적용)

- [사실] `docs/progress/03_cdp_bridge_implementation.md` 에 이미 사용자 지적이 기록되어 있다(직접 인용): *"기존 크롬 프로파일 공유는 안 됨 … `launch_headed_chrome` 은 공유 세션이 아님 → `connect_over_cdp` attach로 교체."*
- [결정] 런처(spawn 주체)와 브리지(attach 주체)의 역할을 명확히 분리한다. **런처는 더 이상 스스로 Chrome 을 spawn 하지 않는다.** 대신 (1) 이미 떠있는 세션을 감지하거나, (2) 인간(또는 별도 스크립트)이 직접 실행할 **플래그 없는** 기동 명령줄만 반환한다. spawn 주체를 인간으로 분리함으로써 `--enable-automation` 유입 경로를 원천 차단한다.
- [근거] 이는 §03에서 사용자가 이미 지시한 "spawn 이 아닌 attach" 원칙을 런처 계층까지 일관되게 적용한 것이다. 봇회피 책임은 IDEA.md R2대로 헤드풀 환경 + 인간유사동작(브라우저 자체 동작)에 두며, 에이전트 레이어는 회피용 플래그를 절대 주입하지 않는다.

## §4. 적용 변경 (파일별 변경 fact)

### `src/core/launcher.py` (attach 전용 재구성)
- [사실] `launch_chrome()` 함수 제거됨(전체 파일 재독 결과 해당 기동 함수 존재하지 않음).
- [사실] `is_chrome_running(port: int = 9222) -> bool` 추가(L57). 포트의 CDP `/json/version` 응답(200) 여부로 실행 중 판단.
- [사실] `build_launch_command(profile_name, port, extension_dir) -> list[str]` 추가(L77). 반환 문자열에 `--enable-automation` 을 절대 포함하지 않음(L110 주석으로 금지 명시). headed 실제 Chrome 기동 명령줄만 반환하며 **자신은 실행하지 않음**.
- [사실] `ensure_attachable(...) -> bool | list[str]` 추가(L118). 떠있으면 `True`, 아니면 기동 명령줄(list) 반환. `subprocess.Popen` 으로 자체 spawn 하지 않음.

### `src/core/cdp_bridge.py` (봇 탐지 사전 검증)
- [사실] `BotDetectionError(Exception)` 추가(L43). attach 대상에 봇 탐지 시그널이 감지되었을 때 사용.
- [사실] `connect()` 에서 attach 직후, 제어권 행사 **이전**에 `page.evaluate("() => navigator.webdriver === true")` 로 흔적 확인(L97). 양성 시 `_safe_disconnect()` 호출 후 `BotDetectionError` 발생(L102–105). 평가 예외 시에도 보수적으로 `BotDetectionError` 차단(L98–100).
- [사실] `_safe_disconnect()` 추가(L107). 차단 전 browser/p 인스턴스 안전 정리.

### `tests/` (신규 + 마이그레이션)
- [사실] 신규 `tests/integration/test_launcher_attach.py`: `build_launch_command()` 반환에 `--enable-automation` 이 없음 명시 검증, `ensure_attachable()` 이 스스로 spawn 하지 않고 명령줄을 반환함을 검증(전체 재독 확인).
- [사실] 신규 `tests/unit/test_cdp_bridge_guard.py`: `navigator.webdriver=true` 주입 시 `BotDetectionError` 발생, `false` 시 정상 attach 진입 검증(전체 재독 확인).
- [사실] 기존 `tests/integration/test_launcher.py` 가 신규 API(`is_chrome_running`/`build_launch_command`/`ensure_attachable`)로 마이그레이션되어 존재함(디스크 확인).

## §5. 검증 (ruff / pytest 실측 출력 인용)

- [사실] `ruff check src tests` 실행 결과(2026-08-14, 프로젝트 루트):
  ```
  All checks passed!
  ```
  (에러 0, pyproject.toml strict 설정 기준).
- [사실] `python -m pytest tests -q` 실행 결과(2026-08-14):
  ```
  .....................                                                    [100%]
  21 passed in 1.57s
  ```
- [사실] 코드 레벨로 `--enable-automation` 미주입이 `build_launch_command` 테스트(`--enable-automation not in cmd`)와 `ensure_attachable` 반환값 테스트(`--enable-automation not in result`)로 자동 보증된다.

## §6. 한계 및 후속

- [한계 · 미검증] 실제 headed Chrome 을 육안으로 띄워 **인포바가 소멸했음을 눈으로 확인하지는 않았다.** 단, 코드상 `--enable-automation` 이 어떤 경로로도 주입되지 않음이 `launcher.py` 소스(L110 금지 주석)와 두 테스트로 보증된다. 육안 확인은 후속 태스크로 분리.
- [한계 · 범위] 본 조치는 `navigator.webdriver` 고정 플래그 노출만 차단한다. TLS 지문·Canvas/WebGL 지문·타이밍 기반 고급 봇 탐지 우회는 포함하지 않으며, IDEA.md R2 원칙에 따라 인간유사동작(지터 등) 레이어에서 별도 대응한다.
- [후속] Captcha 등 인간 확인 지점은 즉시 HITL(인간 위임) 분기로 처리하는 설계가 미구현 — 후속 과제로 남김(§03·IDEA R2 방향과 일치).
- [권고] 런처가 반환한 명령줄을 인간이 직접 실행하는 운용 절차를 문서화(또는 small 스크립트로 고정)하여, 에이전트가 우회적으로 spawn 을 재도입하는 것을 방지할 것.

## 난이도 / 공수

- 이 결정 로그 작성: **하**(문서화, 실측 출력 인용 기반).
- 코드 수정(런처 attach 전용 재구성 + 브리지 봇 탐지 가드 + 테스트): **중**(기존 패턴§03 원칙 준수, TDD/ruff/pytest 통과 확인).

## 참조

- `src/core/launcher.py` (L57 `is_chrome_running`, L77 `build_launch_command`, L118 `ensure_attachable`)
- `src/core/cdp_bridge.py` (L43 `BotDetectionError`, L97 웹드라이버 검증, L107 `_safe_disconnect`)
- `tests/integration/test_launcher_attach.py`, `tests/unit/test_cdp_bridge_guard.py`, `tests/integration/test_launcher.py`
- `docs/progress/03_cdp_bridge_implementation.md` (사용자 지적: spawn→attach 전환)
- `IDEA.md` R2 (봇 탐지 회피 + 캡차 HITL)
- 실측: `ruff check src tests` → All checks passed! / `python -m pytest tests -q` → 21 passed
