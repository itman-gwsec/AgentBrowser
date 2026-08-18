"""컨테이너 GPU/디스플레이 지문 매핑 (env → Chrome flags / JS override).

M6: 도커 컨테이너 내 Chrome 이 호스트 실제 지문(WebGL renderer, CPU 스레드수,
해상도)을 갖도록, docker-compose 에서 주입한 환경변수를 Chrome 실행 플래그와
``navigator`` JS override 로 변환한다.

설계 포인트:
    - 모든 지문 값은 환경변수로 주입되며, 미지정 시 호스트 안전 기본값 사용
      (로컬 단독 기동 / 단위테스트 호환).
    - 컨테이너별 미세 차이(per-container micro-drift)를 부여해, 동일 이미지가
      스케일되어 여러 개 떠도 모두 같은 지문이 되지 않도록 한다 (봇 탐지 리스크
      완화). drift 는 ``container_index`` 기반 나머지 연산으로 결정적(deterministic)
      이며, ``container_index == 0``(단일 컨테이너)이면 기본값 그대로 둔다.
    - 익스텐션 JS 는 수정하지 않는다. 지문 override 는 launcher 단계에서 CDP
      ``Page.addScriptToEvaluateOnNewDocument`` 로 주입할 JS 문자열을 반환한다.
    - ``navigator.webdriver`` 는 ``--enable-automation`` 미주입 원칙(R2)에 의해
      이미 ``false`` 로 유지되므로, 이 모듈은 해당 플래그를 절대 추가하지 않는다.

금지: ``print`` 사용 금지(logger 사용). RAG 관련 코드 없음.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── 환경변수 키 (docker-compose environment 섹션과 1:1 매핑) ──────────────────
ENV_GPU_VENDOR = "CHROME_GPU_VENDOR"
ENV_GPU_RENDERER = "CHROME_GPU_RENDERER"
ENV_HARDWARE_CONCURRENCY = "CHROME_HARDWARE_CONCURRENCY"
ENV_SCREEN_W = "CHROME_SCREEN_W"
ENV_SCREEN_H = "CHROME_SCREEN_H"
ENV_DEVICE_SCALE = "CHROME_DEVICE_SCALE_FACTOR"
ENV_GL_BACKEND = "CHROME_GL_BACKEND"
ENV_ANGLE_BACKEND = "CHROME_ANGLE_BACKEND"
ENV_CONTAINER_INDEX = "CHROME_CONTAINER_INDEX"

# ── 기본값 (호스트 실제값 미주입 시 안전 fallback) ──────────────────────────
# 단위테스트/로컬 기동에서도 유효한 보수적 Apple 실리콘 프로파일.
DEFAULT_GPU_VENDOR = "Google Inc. (Apple)"
DEFAULT_GPU_RENDERER = "ANGLE (Apple, Apple M-series, OpenGL 4.1)"
DEFAULT_HARDWARE_CONCURRENCY = 8
DEFAULT_SCREEN_W = 1920
DEFAULT_SCREEN_H = 1080
DEFAULT_DEVICE_SCALE = 1.0
DEFAULT_GL_BACKEND = "angle"
DEFAULT_ANGLE_BACKEND = "swiftshader"

# WebGL UNMASKED_VENDOR_WEBGL / UNMASKED_RENDERER_WEBGL 파라미터 상수.
_WEBGL_UNMASKED_VENDOR = 0x9245
_WEBGL_UNMASKED_RENDERER = 0x9246


@dataclass
class Fingerprint:
    """컨테이너용 Chrome 지문 설정 (env → 매핑 결과)."""

    gpu_vendor: str = DEFAULT_GPU_VENDOR
    gpu_renderer: str = DEFAULT_GPU_RENDERER
    hardware_concurrency: int = DEFAULT_HARDWARE_CONCURRENCY
    screen_w: int = DEFAULT_SCREEN_W
    screen_h: int = DEFAULT_SCREEN_H
    device_scale_factor: float = DEFAULT_DEVICE_SCALE
    gl_backend: str = DEFAULT_GL_BACKEND
    angle_backend: str = DEFAULT_ANGLE_BACKEND
    container_index: int = 0


def _int_env(env: dict | None, key: str, default: int) -> int:
    """env(dict) 또는 os.environ 에서 정수 환경변수를 읽는다 (파싱 실패 시 기본값)."""
    raw = env.get(key) if env is not None else os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("env %s 값이 정수가 아님(무시, 기본=%s): %r", key, default, raw)
        return default


def _float_env(env: dict | None, key: str, default: float) -> float:
    """env(dict) 또는 os.environ 에서 실수 환경변수를 읽는다 (파싱 실패 시 기본값)."""
    raw = env.get(key) if env is not None else os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("env %s 값이 실수가 아님(무시, 기본=%s): %r", key, default, raw)
        return default


def _str_env(env: dict | None, key: str, default: str) -> str:
    """env(dict) 또는 os.environ 에서 문자열 환경변수를 읽는다 (빈값 시 기본값)."""
    raw = env.get(key) if env is not None else os.environ.get(key)
    if raw is None or raw == "":
        return default
    return raw


def build_fingerprint_from_env(
    env: dict | None = None, container_index: int | None = None
) -> Fingerprint:
    """환경변수에서 지문 설정을 구성한다.

    ``container_index`` 가 명시되면 그것을, 아니면 ``CHROME_CONTAINER_INDEX`` env
    를 사용한다 (둘 다 없으면 0 = 단일 컨테이너, drift 미적용).

    Args:
        env: 환경변수 dict (테스트 주입용). None 이면 ``os.environ`` 사용.
        container_index: 컨테이너 인덱스(0 기반). None 이면 env 에서 파생.

    Returns:
        drift 가 적용된 ``Fingerprint`` 인스턴스.
    """
    if container_index is None:
        container_index = _int_env(env, ENV_CONTAINER_INDEX, 0)

    fp = Fingerprint(
        gpu_vendor=_str_env(env, ENV_GPU_VENDOR, DEFAULT_GPU_VENDOR),
        gpu_renderer=_str_env(env, ENV_GPU_RENDERER, DEFAULT_GPU_RENDERER),
        hardware_concurrency=_int_env(
            env, ENV_HARDWARE_CONCURRENCY, DEFAULT_HARDWARE_CONCURRENCY
        ),
        screen_w=_int_env(env, ENV_SCREEN_W, DEFAULT_SCREEN_W),
        screen_h=_int_env(env, ENV_SCREEN_H, DEFAULT_SCREEN_H),
        device_scale_factor=_float_env(env, ENV_DEVICE_SCALE, DEFAULT_DEVICE_SCALE),
        gl_backend=_str_env(env, ENV_GL_BACKEND, DEFAULT_GL_BACKEND),
        angle_backend=_str_env(env, ENV_ANGLE_BACKEND, DEFAULT_ANGLE_BACKEND),
        container_index=container_index,
    )
    return apply_container_drift(fp)


def apply_container_drift(fp: Fingerprint, enabled: bool = True) -> Fingerprint:
    """컨테이너별 미세 지문 드리프트를 결정적 나머지 연산으로 적용한다.

    동일 이미지가 스케일되어 여러 컨테이너로 떠도 모두 같은 지문이 되지 않도록,
    인덱스 기반으로 해상도/스레드수에 작은 편차를 더한다. ``container_index == 0``
    이거나 ``enabled=False`` 면 기본값을 그대로 둔다 (단일 컨테이너는 drift 불필요).

    Args:
        fp: 원본 지문.
        enabled: drift 적용 여부.

    Returns:
        드리프트가 반영된 ``fp`` (동일 인스턴스, in-place).
    """
    if not enabled or fp.container_index <= 0:
        return fp

    idx = fp.container_index
    # 해상도 미세 드리프트(±수 px) — 나머지 연산으로 결정적.
    fp.screen_w = max(800, fp.screen_w + (idx % 8))
    fp.screen_h = max(600, fp.screen_h + (idx % 6))
    # hardwareConcurrency 미세 드리프트(0 또는 +1) — 호스트 스레드수와 비슷한 범위 유지.
    fp.hardware_concurrency = max(1, fp.hardware_concurrency + (idx % 2))
    logger.debug(
        "컨테이너 지문 drift 적용 (index=%d, %dx%d, cores=%d)",
        idx,
        fp.screen_w,
        fp.screen_h,
        fp.hardware_concurrency,
    )
    return fp


def fingerprint_to_chrome_flags(fp: Fingerprint) -> list[str]:
    """지문을 Chrome 실행 플래그로 변환한다.

    ``--use-gl`` / ``--use-angle`` 로 WebGL 백엔드(호스트 GPU 모사)를,
    ``--force-device-scale-factor`` 로 DPI 배율을, ``--window-size`` 로 해상도를
    반영한다. ``--enable-automation`` 은 절대 포함하지 않는다 (R2).

    Args:
        fp: 지문 설정.

    Returns:
        Chrome 명령줄 인자 리스트.
    """
    return [
        f"--use-gl={fp.gl_backend}",
        f"--use-angle={fp.angle_backend}",
        f"--force-device-scale-factor={fp.device_scale_factor}",
        f"--window-size={fp.screen_w},{fp.screen_h}",
    ]


def fingerprint_to_js_overrides(fp: Fingerprint) -> str:
    """지문을 ``navigator`` JS override 스크립트로 변환한다.

    런처가 CDP ``Page.addScriptToEvaluateOnNewDocument`` 로 주입한다.

    - ``navigator.hardwareConcurrency`` 를 env 값으로 재정의.
    - WebGL ``UNMASKED_VENDOR_WEBGL`` / ``UNMASKED_RENDERER_WEBGL`` 파라미터를
      env 의 GPU vendor/renderer 문자열로 패치 (WebGL 지문 일치).

    문자열 값은 ``json.dumps`` 로 직렬화해 따옴표/이스케이프를 안전하게 처리한다.

    Args:
        fp: 지문 설정.

    Returns:
        새 문서마다 평가될 JS 스니펫 (문자열).
    """
    vendor = json.dumps(fp.gpu_vendor)
    renderer = json.dumps(fp.gpu_renderer)
    return (
        "(function(){"
        "  try{"
        "    Object.defineProperty(navigator,'hardwareConcurrency',{"
        f"      get:function(){{return {fp.hardware_concurrency};}},configurable:true}});"
        f"    var __v={vendor},__r={renderer};"
        "    var __orig=WebGLRenderingContext.prototype.getParameter;"
        "    WebGLRenderingContext.prototype.getParameter=function(p){"
        f"      if(p==={_WEBGL_UNMASKED_VENDOR})return __v;"
        f"      if(p==={_WEBGL_UNMASKED_RENDERER})return __r;"
        "      return __orig.call(this,p);"
        "    };"
        "  }catch(e){}"
        "})();"
    )
