"""M6 단위 테스트 (tests/unit/test_fingerprint.py).

검증 대상 (TDD — env 주입값이 launcher 플래그/JS override 에 반영되는지 단언):
    - ``core.fingerprint.build_fingerprint_from_env`` 가 CHROME_* env 를 올바르게 매핑.
    - ``core.fingerprint.apply_container_drift`` 가 컨테이너별 미세 지문 드리프트를
      결정적 나머지 연산으로 부여 (index==0 이면 drift 없음).
    - ``core.fingerprint.fingerprint_to_chrome_flags`` 가 env 값을 Chrome 플래그로 반영.
    - ``core.fingerprint.fingerprint_to_js_overrides`` 가 env 값을 navigator JS 로 반영.
    - ``core.launcher.build_fingerprint_bundle`` (launcher 진입점)가 env 를
      플래그+JS 모두에 반영.
    - ``core.launcher.build_launch_command`` 가 지문 플래그를 명령줄에 포함하고
      ``--enable-automation`` 은 절대 미포함 (R2).

컨벤션: snake_case, 한국어 주석. pytest + unittest.mock.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from core.fingerprint import (
    ENV_ANGLE_BACKEND,
    ENV_DEVICE_SCALE,
    ENV_GPU_RENDERER,
    ENV_HARDWARE_CONCURRENCY,
    ENV_SCREEN_H,
    ENV_SCREEN_W,
    Fingerprint,
    apply_container_drift,
    build_fingerprint_from_env,
    fingerprint_to_chrome_flags,
    fingerprint_to_js_overrides,
)
from core.launcher import (
    CHROME_PATH,
    build_fingerprint_bundle,
    build_launch_command,
    spawn_chrome_pipe,
)


# ── env → 매핑 ────────────────────────────────────────────────────────────────
def test_build_fingerprint_from_env_reads_env() -> None:
    """CHROME_* env 값이 Fingerprint 필드로 정확히 매핑되어야 한다."""
    env = {
        ENV_GPU_RENDERER: "ANGLE (NVIDIA, GeForce RTX 4090, OpenGL 4.5)",
        ENV_HARDWARE_CONCURRENCY: "16",
        ENV_SCREEN_W: "2560",
        ENV_SCREEN_H: "1440",
        ENV_DEVICE_SCALE: "1.5",
        ENV_ANGLE_BACKEND: "vulkan",
    }
    fp = build_fingerprint_from_env(env=env)
    assert fp.gpu_renderer == "ANGLE (NVIDIA, GeForce RTX 4090, OpenGL 4.5)"
    assert fp.hardware_concurrency == 16
    assert fp.screen_w == 2560
    assert fp.screen_h == 1440
    assert fp.device_scale_factor == 1.5
    assert fp.angle_backend == "vulkan"
    # 미지정 필드는 기본값 유지.
    assert fp.gl_backend == "angle"
    assert fp.container_index == 0


def test_build_fingerprint_from_env_bad_int_falls_back() -> None:
    """정수 env 가 비정상이면 기본값으로 안전 폴백해야 한다."""
    env = {ENV_HARDWARE_CONCURRENCY: "not-a-number", ENV_SCREEN_W: "abc"}
    fp = build_fingerprint_from_env(env=env)
    assert fp.hardware_concurrency == 8  # DEFAULT
    assert fp.screen_w == 1920  # DEFAULT


# ── 컨테이너별 drift (나머지 연산, 결정적) ───────────────────────────────────────
def test_apply_container_drift_none_for_index_zero() -> None:
    """단일 컨테이너(index==0)는 drift 를 적용하지 않는다."""
    fp = Fingerprint(screen_w=1920, screen_h=1080, hardware_concurrency=8, container_index=0)
    out = apply_container_drift(fp)
    assert out.screen_w == 1920
    assert out.screen_h == 1080
    assert out.hardware_concurrency == 8


def test_apply_container_drift_deterministic_per_index() -> None:
    """index>0 이면 결정적 나머지 연산으로 미세 드리프트가 부여된다."""
    base = Fingerprint(screen_w=1920, screen_h=1080, hardware_concurrency=8, container_index=3)
    out = apply_container_drift(base)
    # idx%8 == 3, idx%6 == 3, idx%2 == 1
    assert out.screen_w == 1920 + 3
    assert out.screen_h == 1080 + 3
    assert out.hardware_concurrency == 8 + 1


def test_apply_container_drift_distinct_across_indices() -> None:
    """서로 다른 index 는 서로 다른 지문을 갖는다 (탐지 리스크 완화)."""
    a = apply_container_drift(Fingerprint(screen_w=1920, screen_h=1080, container_index=1))
    b = apply_container_drift(Fingerprint(screen_w=1920, screen_h=1080, container_index=2))
    assert (a.screen_w, a.screen_h) != (b.screen_w, b.screen_h)


# ── env → Chrome 플래그 ────────────────────────────────────────────────────────
def test_fingerprint_to_chrome_flags_reflects_env() -> None:
    """지문 값이 Chrome 플래그(--use-gl/--use-angle/--force-device-scale-factor/
    --window-size)로 반영되어야 한다."""
    fp = Fingerprint(
        gl_backend="angle",
        angle_backend="swiftshader",
        device_scale_factor=2.0,
        screen_w=1728,
        screen_h=1117,
    )
    flags = fingerprint_to_chrome_flags(fp)
    assert "--use-gl=angle" in flags
    assert "--use-angle=swiftshader" in flags
    assert "--force-device-scale-factor=2.0" in flags
    assert "--window-size=1728,1117" in flags
    # 봇 탐지 시그널 절대 금지.
    assert all("--enable-automation" not in f for f in flags)


# ── env → JS override ────────────────────────────────────────────────────────
def test_fingerprint_to_js_overrides_reflects_env() -> None:
    """env 값(GPU renderer, hardwareConcurrency)이 navigator JS override 에 반영되어야 한다."""
    fp = Fingerprint(
        gpu_vendor="Google Inc. (NVIDIA)",
        gpu_renderer="ANGLE (NVIDIA, GeForce RTX 4090)",
        hardware_concurrency=16,
    )
    js = fingerprint_to_js_overrides(fp)
    # navigator.hardwareConcurrency 재정의 값.
    assert "return 16;" in js
    # WebGL UNMASKED_RENDERER 패치에 env 문자열 포함.
    assert "ANGLE (NVIDIA, GeForce RTX 4090)" in js
    assert "Google Inc. (NVIDIA)" in js
    # navigator.webdriver 는 이 모듈이 건드리지 않음(enable-automation 금지 원칙).
    assert "webdriver" not in js


# ── launcher 진입점: env → 플래그 + JS 모두 반영 (핵심 TDD) ───────────────────────
def test_launcher_bundle_reflects_env_into_flags_and_js(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_fingerprint_bundle 가 env 를 Chrome 플래그와 JS override 모두에 반영."""
    env = {
        ENV_GPU_RENDERER: "ANGLE (Apple, Apple M2 Pro, OpenGL 4.1)",
        ENV_HARDWARE_CONCURRENCY: "10",
        ENV_SCREEN_W: "1728",
        ENV_SCREEN_H: "1117",
        ENV_DEVICE_SCALE: "2.0",
    }
    flags, js = build_fingerprint_bundle(env=env)
    # 플래그 측면
    assert "--window-size=1728,1117" in flags
    assert "--force-device-scale-factor=2.0" in flags
    assert "--use-gl=angle" in flags
    # JS 측면
    assert "return 10;" in js
    assert "ANGLE (Apple, Apple M2 Pro, OpenGL 4.1)" in js


def _stub_chrome_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """미설치 env 에서도 테스트가 녹색이 되도록 CHROME_PATH 를 스텁."""
    if not os.path.exists(CHROME_PATH):
        monkeypatch.setattr(
            os.path,
            "exists",
            lambda p: True if p == CHROME_PATH else os.path.exists(p),
        )


def test_launcher_build_launch_command_includes_fingerprint_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_launch_command 가 env 지문 플래그를 명령줄에 포함하고
    --enable-automation 은 절대 없어야 한다 (R2)."""
    _stub_chrome_path(monkeypatch)
    monkeypatch.setenv(ENV_HARDWARE_CONCURRENCY, "12")
    monkeypatch.setenv(ENV_SCREEN_W, "1512")
    monkeypatch.setenv(ENV_SCREEN_H, "982")
    monkeypatch.setenv(ENV_DEVICE_SCALE, "1.0")
    cmd = build_launch_command(profile_name="default")

    assert "--window-size=1512,982" in cmd
    assert "--use-gl=angle" in cmd
    assert "--enable-automation" not in cmd
    # pipe 모드(M5) 유지.
    assert "--remote-debugging-pipe" in cmd
    assert "--remote-debugging-port" not in cmd


def test_launcher_spawn_appends_fingerprint_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """spawn_chrome_pipe 가 지문 플래그를 기동 인자에 포함하는지 (Popen Mock)."""
    _stub_chrome_path(monkeypatch)
    monkeypatch.setenv(ENV_HARDWARE_CONCURRENCY, "14")
    monkeypatch.setenv(ENV_SCREEN_W, "1440")
    monkeypatch.setenv(ENV_SCREEN_H, "900")

    captured: dict = {}

    def fake_popen(*args, **kwargs):
        captured.clear()
        captured["args"] = list(args[0]) if args else kwargs.get("args", [])
        fake = mock.MagicMock()
        fake.poll.return_value = None
        captured["_proc"] = fake
        return fake

    monkeypatch.setattr("core.launcher.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    # fd 조작 모킹 (dup2/dup/close 는 no-op).
    monkeypatch.setattr(os, "pipe", lambda: (50, 51))
    monkeypatch.setattr(os, "dup", lambda fd: 999)
    monkeypatch.setattr(os, "dup2", lambda a, b: None)
    monkeypatch.setattr(os, "close", lambda fd: None)

    with mock.patch("core.launcher._dup_pipe_to_chrome_fds", lambda *a, **k: None):
        spawn_chrome_pipe(profile_name="default")

    spawn_args = captured["args"]
    assert any(a.startswith("--window-size=1440,900") for a in spawn_args)
    assert "--use-gl=angle" in spawn_args
    assert "--enable-automation" not in spawn_args
