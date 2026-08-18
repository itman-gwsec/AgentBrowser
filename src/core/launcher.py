"""크롬 런처 (Chrome launcher) — attach 전용 + pipe 기동 모드.

설계 변경 (2026-08-16, M5 — 포커스 분리 + 원격디버깅 플래그 개선):
    이전까지는 ``--remote-debugging-port`` 로 TCP 포트를 개방하여 CDP 로 붙었다.
    이 방식은 macOS 에서 "리모트 디버깅 허용" 방화벽 프롬프트(네트워크 리스닝)를
    유발하고, 사용자 작업과 포커스가 겹칠 수 있다.

    M5 에서는 **``--remote-debugging-pipe``** 로 전환한다:
        - 포트를 개방하지 않으므로 macOS 방화벽 프롬프트가 발생하지 않는다
          (``lsof -i:9222`` 도 null — Q5 검증 ``port_open:false``).
        - CDP 는 FD 3(명령 읽기) / FD 4(이벤트 쓰기) 로 주고받는다
          (메시지 포맷: NUL(``\\x00``) 구분 JSON).
        - 단, pipe 모드의 FD 는 부모 프로세스가 상속받아야 하므로 **런처(또는
          브리지)가 Chrome 을 직접 spawn** 해야 한다. 외부(인간)가 띄운 pipe
          Chrome 에는 별도 프로세스가 FD 를 물려받을 수 없다.
        - pipe transport 는 Chromium 이 "자동화 채널"로 간주하여
          ``navigator.webdriver`` 를 ``true`` 로 고정한다. 이는 ``--enable-automation``
          플래그(인포바 유발)와는 무관한 transport artifact 이므로, 런처가
          ``--enable-automation`` 없이 기동한 세션은 cdp_bridge 가 신뢰하고
          진행한다 (봇 탐지 가드의 이중 방어 의도 보존 — R2).

    별도 전용 프로파일(``profiles/<name>``) + AgentBrowser 익스텐션 원칙은 그대로.
    ``--enable-automation`` 은 절대 추가하지 않는다 (R2 봇회피).

설계 근거:
    - R1(헤드풀 실제 크롬): build_launch_command 는 headed 실제 Chrome 명령줄.
    - R2(봇회피): 스폰 주체가 런처/브리지라도 ``--enable-automation`` 미주입.
    - 포커스 분리(B): 전용 프로파일 + 별도 프로세스 + focus-isolation 플래그로
      사용자 앱 포커스/백그라운드 스로틀링 간섭을 최소화.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import subprocess
import time
from pathlib import Path

# macOS 실제 Chrome 바이너리 경로 (헤드리스가 아닌 헤드풀 기동).
CHROME_PATH: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 이 모듈 파일 기준 프로젝트 루트: src/core/launcher.py → parents[2] = 프로젝트 루트.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

# 모듈 전용 로거 (console 출력용).
logger = logging.getLogger(__name__)

# CDP 는 항상 127.0.0.1 바인딩을 전제로 한다.
_CDP_HOST: str = "127.0.0.1"

# pipe transport 에서 Chrome 이 사용하는 FD.
_CDP_PIPE_READ_FD: int = 3   # Chrome 이 명령을 읽는 FD (부모 → Chrome)
_CDP_PIPE_WRITE_FD: int = 4  # Chrome 이 이벤트를 쓰는 FD (Chrome → 부모)

# 사용자 작업과 겹치지 않도록 적용하는 포커스/백그라운드 격리 플래그.
# (런처가 스스로 spawn 하지 않더라도 build_launch_command 결과에 포함되어
#  인간/스크립트가 실행할 때 동일 옵션이 적용되도록 한다.)
_FOCUS_ISOLATION_FLAGS: tuple[str, ...] = (
    # 가려진(occluded) 창을 백그라운드화 하지 않음 → 포커스 탈취 최소화.
    "--disable-backgrounding-occluded-windows",
    # 백그라운드 탭의 타이머 스로틀링 비활성 → 사용자 세션과 무관하게 동작.
    "--disable-background-timer-throttling",
    # 렌더러 백그라운드화 비활성.
    "--disable-renderer-backgrounding",
    # macOS 네이티브 창 가림(occlusion) 계산 비활성 → 창이 "숨김"으로 오인되지 않음.
    "--disable-features=CalculateNativeWinOcclusion",
)


def _profile_dir(profile_name: str) -> Path:
    """전용 프로파일 디렉터리 경로를 반환한다 (생성은 호출자 책임)."""
    return PROJECT_ROOT / "profiles" / profile_name


def is_chrome_running(profile_name: str = "default", port: int = 9222) -> bool:
    """지정 프로파일로 떠있는 Chrome 프로세스가 있는지 확인한다 (포트 미사용).

    M5 부터는 원격 디버깅이 pipe 모드(비네트워크)이므로 포트 프로브 대신
    프로세스 존재 여부(pgrep)로 판단한다. ``--remote-debugging-pipe`` 는 TCP
    포트를 열지 않으므로 ``lsof -i:<port>`` 는 항상 null 이다.

    Args:
        profile_name: ``profiles/<name>`` 전용 프로파일 이름.
        port: 하위 호환용 인자 (pipe 모드에서는 무시됨).

    Returns:
        해당 프로파일의 Chrome 프로세스가 있으면 True, 없으면 False.
    """
    pattern = f"Google Chrome.*user-data-dir=.*profiles/{profile_name}"
    try:
        # pgrep -f: 전체 커맨드라인 매칭. macOS 네이티브 제공.
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except OSError:
        # pgrep 미제공 환경에서는 보수적으로 False (포트도 안 열려 있음).
        return False


def build_launch_command(
    profile_name: str = "default",
    extension_dir: str = "src/extension",
) -> list[str]:
    """봇 탐지 플래그 없이 headed Chrome 을 기동하는 명령줄을 반환한다.

    ``--enable-automation`` 을 절대 포함하지 않는다 (인포바 +
    ``navigator.webdriver=true`` 노출 방지). M5 부터는 TCP 포트 대신
    ``--remote-debugging-pipe`` 를 사용하여 macOS 방화벽 프롬프트를 회피한다.
    반환된 명령줄은 인간(또는 별도 스크립트)이 직접 실행해야 한다 — 이 함수는
    실행하지 않는다. (pipe 전용 spawn 이 필요하면 ``spawn_chrome_pipe`` 사용)

    Args:
        profile_name: ``profiles/<name>`` 형태로 사용할 전용 프로파일 이름.
        extension_dir: 프로젝트 루트 기준 익스텐션 디렉터리 경로(상대경로).

    Returns:
        실행 가능한 명령줄 인자 리스트 (``subprocess`` 호환).

    Raises:
        FileNotFoundError: 지정한 Chrome 바이너리가 존재하지 않는 경우.
    """
    if not os.path.exists(CHROME_PATH):
        raise FileNotFoundError(  # noqa: TRY003
            f"Chrome 바이너리를 찾을 수 없습니다: {CHROME_PATH}"
        )

    extension_path: Path = (PROJECT_ROOT / extension_dir).resolve()
    args: list[str] = [
        CHROME_PATH,
        f"--user-data-dir={_profile_dir(profile_name)}",
        # M5: TCP 포트 대신 pipe. 포트 미개방 → 방화벽 프롬프트 없음.
        "--remote-debugging-pipe",
        f"--load-extension={extension_path}",
        # ⚠ 금지: "--enable-automation" 은 절대 추가하지 않는다 (R2 봇회피).
        "--no-first-run",
        "--no-default-browser-check",
        # 포커스/백그라운드 격리 (사용자 작업과 겹치지 않게).
        *_FOCUS_ISOLATION_FLAGS,
        "about:blank",
    ]
    return args


def _dup_pipe_to_chrome_fds(r_cmd: int, w_evt: int) -> None:
    """부모 프로세스에서 pipe 의 양 끝을 Chrome 이 기대하는 FD 3/4 로 dup 한다.

    macOS 에서 ``--remote-debugging-pipe`` 는 FD 3(명령 읽기) / FD 4(이벤트 쓰기) 를
    사용한다. 이전에는 ``preexec_fn`` 안에서 dup 했으나, macOS 에선 ``preexec_fn`` 이
    부모가 물려준 FD 를 자식에 제대로 이어주지 못하는 사례가 있어 Chrome 이
    ``Remote debugging pipe file descriptors are not open`` (exit 13) 으로 즉시
    크래시했다.

    해결: 부모에서 미리 FD 3/4 로 ``dup2`` 한 뒤 ``subprocess.Popen(pass_fds=[3, 4])``
    로 넘긴다. ``pass_fds`` 는 C 수준에서 해당 FD 를 자식에 그대로 상속시키고,
    ``close_fds=True``(기본) 로 나머지 부모 FD 를 정리하므로 macOS FD 이슈를 우회한다.
    """
    os.dup2(r_cmd, _CDP_PIPE_READ_FD)
    os.dup2(w_evt, _CDP_PIPE_WRITE_FD)


def spawn_chrome_pipe(
    profile_name: str = "default",
    extension_dir: str = "src/extension",
    headless: bool = False,
    extra_args: list[str] | None = None,
) -> tuple[subprocess.Popen, int, int]:
    """pipe 모드로 Chrome 을 spawn 하고 (write_fd, read_fd) 를 반환한다.

    TCP 포트를 열지 않으므로 macOS 방화벽 프롬프트가 없다. 반환된 FD 는
    호출자(보통 cdp_bridge 의 WS 브리지)가 CDP 메시지를 주고받는 데 사용한다.

    Args:
        profile_name: 전용 프로파일 이름.
        extension_dir: 익스텐션 디렉터리(프로젝트 루트 기준 상대경로).
        headless: 헤드리스 기동 여부 (기본 False = headed 실제 크롬, R1).
        extra_args: 추가 Chrome 인자.

    Returns:
        ``(proc, write_fd, read_fd)`` — write_fd 는 부모가 CDP 명령을 쓰는 FD,
        read_fd 는 부모가 CDP 이벤트를 읽는 FD.

    Raises:
        FileNotFoundError: Chrome 바이너리가 없거나 기동에 반복 실패한 경우.
    """
    if not os.path.exists(CHROME_PATH):
        raise FileNotFoundError(f"Chrome 바이너리가 없습니다: {CHROME_PATH}")  # noqa: TRY003

    extension_path: Path = (PROJECT_ROOT / extension_dir).resolve()
    base_args: list[str] = [
        CHROME_PATH,
        "--remote-debugging-pipe",
        f"--user-data-dir={_profile_dir(profile_name)}",
        f"--load-extension={extension_path}",
        "--no-first-run",
        "--no-default-browser-check",
        *_FOCUS_ISOLATION_FLAGS,
    ]
    if headless:
        base_args.append("--headless=new")
    if extra_args:
        base_args.extend(extra_args)
    base_args.append("about:blank")

    last_exc: Exception | None = None
    # macOS FD 이슈(exit 13, "pipe fds not open") 우회: 부모에서 FD 3/4 로 dup2 한 뒤
    # pass_fds=[3,4] 로 상속. 드물게 초기 크래시하면 최대 3회 재시도한다.
    for _attempt in range(3):
        r_cmd, w_cmd = os.pipe()   # r_cmd: Chrome 이 읽음 / w_cmd: 부모가 씀
        r_evt, w_evt = os.pipe()   # r_evt: 부모가 읽음 / w_evt: Chrome 이 씀

        # 예약 fd(3/4) 충돌 회피: 부모가 계속 쓸 write/read fd(w_cmd, r_evt) 가
        # 우연히 3/4 에 있으면 dup2 가 덮어써서 부모 핸들이 꼬인다. 미리 높은 fd 로 옮긴다.
        if w_cmd in (_CDP_PIPE_READ_FD, _CDP_PIPE_WRITE_FD):
            _new = os.dup(w_cmd)
            os.close(w_cmd)
            w_cmd = _new
        if r_evt in (_CDP_PIPE_READ_FD, _CDP_PIPE_WRITE_FD):
            _new = os.dup(r_evt)
            os.close(r_evt)
            r_evt = _new

        # 부모에서 FD 3/4 로 미리 dup → Chrome 이 기대하는 위치에 pipe 를 놓는다.
        # (r_cmd/w_evt 가 이미 3/4 인 경우 dup2 는 no-op)
        os.dup2(r_cmd, _CDP_PIPE_READ_FD)
        os.dup2(w_evt, _CDP_PIPE_WRITE_FD)
        try:
            proc = subprocess.Popen(
                base_args,
                # pass_fds: C 수준에서 FD 3/4 를 자식에 그대로 상속시킨다.
                # close_fds=True(기본) 로 나머지 부모 FD 를 정리 → macOS FD 누수/초기화
                # 이슈를 근본 우회. (preexec_fn + close_fds=False 조합은 미사용)
                pass_fds=[_CDP_PIPE_READ_FD, _CDP_PIPE_WRITE_FD],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:  # pragma: no cover - 기동 자체 실패(권한/경로)
            last_exc = exc
            for fd in (r_cmd, w_cmd, r_evt, w_evt, _CDP_PIPE_READ_FD, _CDP_PIPE_WRITE_FD):
                with contextlib.suppress(OSError):
                    os.close(fd)
            continue

        # 짧은 대기 후 즉시 죽었는지 확인(초기 크래시 필터).
        time.sleep(2.0)
        if proc.poll() is None:
            # 성공: 부모가 사용할 write/read FD 반환.
            # w_cmd 는 부모가 CDP 명령을 쓰는 FD, r_evt 는 부모가 이벤트를 읽는 FD.
            # dup2 로 만든 FD 3/4 는 부모 입장에선 여분(반대편)이므로 정리한다.
            # (원본 r_cmd/w_evt 가 3/4 와 겹치지 않도록 보관 fd 는 제외하고 닫음)
            _to_close = {r_cmd, w_evt, _CDP_PIPE_READ_FD, _CDP_PIPE_WRITE_FD}
            _to_close.discard(w_cmd)
            _to_close.discard(r_evt)
            for fd in _to_close:
                with contextlib.suppress(OSError):
                    os.close(fd)
            return proc, w_cmd, r_evt
        # 즉시 죽은 경우 정리 후 재시도.
        with contextlib.suppress(OSError):
            proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=3)
        for fd in (r_cmd, w_cmd, r_evt, w_evt, _CDP_PIPE_READ_FD, _CDP_PIPE_WRITE_FD):
            with contextlib.suppress(OSError):
                os.close(fd)
        last_exc = RuntimeError(f"Chrome pipe spawn failed (exit={proc.returncode})")

    raise RuntimeError(f"Chrome 을 pipe 모드로 기동하지 못했습니다: {last_exc}")  # noqa: TRY003


def ensure_attachable(
    profile_name: str = "default",
    port: int = 9222,
    extension_dir: str = "src/extension",
) -> bool | list[str]:
    """attach 가능 상태를 보장한다.

    M5 부터는 pipe 모드이므로, 떠있지 않으면 **런처가 직접 spawn** 한다
    (pipe FD 는 별도 프로세스가 물려받을 수 없으므로 인간에게 명령줄을 넘기는
    방식은 pipe 와 호환되지 않는다). 스스로 spawn 하더라도 ``--enable-automation``
    이 없으므로 봇 탐지 시그널이 유입되지 않는다 (R2).

    Args:
        profile_name: 전용 프로파일 이름.
        port: 하위 호환용 (pipe 모드에서 무시).
        extension_dir: 익스텐션 디렉터리(프로젝트 루트 기준 상대경로).

    Returns:
        bool: 이미 떠있으면 True.
        list[str]: 안 떠있으면 기동 명령줄 (문서/인간 실행용 참고용).
    """
    if is_chrome_running(profile_name):
        return True
    # pipe 호환을 위해 런처가 직접 spawn 해야 한다. 반환값은 인간 참고용 명령줄.
    return build_launch_command(profile_name, extension_dir)


def _main() -> None:
    """커맨드라인 진입점: ``python -m core.launcher --profile default``.

    동작: 프로파일 프로세스 존재를 확인하고, 떠있으면 메시지, 안 떠있으면
    *인간이 실행할* 기동 명령줄(pipe 모드)을 출력한다.
    """
    parser = argparse.ArgumentParser(
        description="AgentBrowser 전용 프로파일로 Chrome 을 기동한다(pipe 모드 명령줄 출력)."
    )
    parser.add_argument("--profile", default="default", help="profiles/ 하위 프로파일 이름")
    parser.add_argument("--extension", default="src/extension", help="익스텐션 디렉터리")
    args = parser.parse_args()

    if is_chrome_running(args.profile):
        logger.info("Chrome 이미 실행 중 (profile=%s). attach 가능.", args.profile)
        return

    # 안 떠있으면 인간이 실행할 pipe 기동 명령줄을 출력.
    command = " ".join(build_launch_command(args.profile, args.extension))
    logger.info("Chrome 이 없습니다. 아래 pipe 명령으로 인간이 직접 기동하세요:")
    print(command)  # 인간이 터미널에 붙여넣어 실행.


if __name__ == "__main__":
    _main()
