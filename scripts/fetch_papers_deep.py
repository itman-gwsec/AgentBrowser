#!/usr/bin/env python3
"""Phase A: 10건 LLM 연구 논문을 실제 headed Chrome 로 방문→본문 수집.

목적:
    이미 선정된 10건 URL(arxiv/nature/github/blog 등)을 *실제 브라우저*로
    직접 방문해 본문 앞 ~4000자를 수집한다. 분석·해석은 하지 않고
    원본(raw_text)만 수집해 /tmp/llm_deep_10.json 에 저장한다.

동작/안전 (IDEA.md R1/R2 준수):
    - ``build_launch_command`` 로 ``--enable-automation`` 없는 headed Chrome 기동
      (플래그 없음 → navigator.webdriver=False, 봇 탐지 회피).
    - ``CDPBridge.connect()`` 로 attach (webdriver=False 실측 검증).
    - ``Humanizer`` 로 인간유사 동작 적용(think_pause / scroll_to_bottom / hover).
    - 종료 시 Chrome 프로세스 + 포트 정리.
    - print 금지 → logger.
    - 익스텐션(JS) 수정 금지 — core 모듈은 그대로 재사용.

CLI:
    python scripts/fetch_papers_deep.py [--in PATH] [--out PATH] \
        [--port 9226] [--profile deep]

기본 입력: /tmp/llm_final_10.json (final_10[].url)
기본 출력: /tmp/llm_deep_10.json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# scripts/ 실행 시에도 src 임포트 가능하도록 경로 세팅.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.cdp_bridge import BotDetectionError, CDPBridge  # noqa: E402
from core.humanizer import Humanizer  # noqa: E402
from core.launcher import build_launch_command, is_chrome_running  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fetch_papers_deep")

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 본문 수집 상한(자). 논문이면 abstract+intro 보통 포함.
TEXT_CAP = 4000

# 단일 URL 처리 상한(초) — hang 방지.
PAGE_GOTO_TIMEOUT_MS = 30_000
CDP_WAIT_MAX_S = 25.0


def detect_source(url: str) -> str:
    """URL 호스트 기반 source 라벨을 반환한다 (arxiv/nature/github/etc)."""
    u = (url or "").lower()
    if "arxiv.org" in u:
        return "arxiv"
    if "nature.com" in u:
        return "nature"
    if "github.com" in u:
        return "github"
    if "deepinfra.com" in u:
        return "deepinfra"
    if "sebastianraschka" in u:
        return "blog"
    return "web"


def free_port(port: int) -> None:
    """포트를 점유 중인 프로세스를 강제 정리한다 (깨끗한 재기동 보장)."""
    try:
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        pids = {p.strip() for p in out.split() if p.strip().isdigit()}
        for pid in pids:
            try:
                subprocess.run(["kill", "-9", pid], check=False, timeout=5)
            except Exception:
                logger.debug("kill 실패 pid=%s (무시)", pid)
    except Exception:
        logger.debug("free_port: lsof 실패 (무시)")
    time.sleep(0.5)


def launch_chrome(port: int, profile: str) -> subprocess.Popen:
    """build_launch_command 로 명령줄 얻어 headed Chrome 을 백그라운드 기동."""
    free_port(port)
    cmd = build_launch_command(profile, port)
    logger.info("Chrome 기동 명령: %s", " ".join(cmd))
    log_path = LOG_DIR / f"fetch_papers_deep_chrome_{port}.log"
    with log_path.open("wb") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    logger.info("Chrome PID=%s 기동 (port=%s)", proc.pid, port)
    return proc


def terminate_chrome(proc: subprocess.Popen | None, port: int) -> None:
    """Chrome 프로세스를 종료하고 포트를 정리한다."""
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            logger.debug("terminate_chrome: 종료 중 예외 (무시)")
    free_port(port)


def wait_for_cdp(port: int) -> None:
    """CDP 엔드포인트 응답 대기 (최대 CDP_WAIT_MAX_S 폴링)."""
    deadline = time.time() + CDP_WAIT_MAX_S
    while time.time() < deadline:
        if is_chrome_running(port):
            logger.info("CDP 준비 완료 (port=%s)", port)
            return
        time.sleep(0.5)
    raise TimeoutError(f"CDP_TIMEOUT_PORT_{port}")


def hover_some_links(page: Any, humanizer: Humanizer) -> None:
    """일부 링크를 hover 하여 인간 행동(시선 이동)을 모방한다."""
    try:
        links = page.query_selector_all("a[href]")
        if not links:
            return
        sample = random.sample(links, min(3, len(links)))
        for link in sample:
            box = link.bounding_box()
            if not box:
                continue
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            page.mouse.move(cx, cy)
            time.sleep(random.uniform(0.1, 0.4))
    except Exception:
        logger.debug("hover 생략 (무시)")


def extract_text(page: Any) -> str:
    """본문 텍스트를 추출한다 (source 별 타겟 → 전체 body fallback), 4000자 cap.

    arXiv 는 #abstract/.abstract-text, Nature 는 article 본문,
    GitHub 는 .markdown-body(README) 를 우선 시도하고, 없으면
    document.body.innerText 를 사용한다.
    """
    js = r"""() => {
        const pick = (sel) => {
            const el = document.querySelector(sel);
            return el ? (el.innerText || '').trim() : '';
        };
        const targeted = [
            pick('#abstract'),
            pick('.abstract-text'),
            pick('article'),
            pick('[data-test="article-body"]'),
            pick('.c-article-body'),
            pick('article.markdown-body'),
            pick('#readme article'),
            pick('.markdown-body'),
        ].filter((t) => t.length > 0);
        let text = targeted.length ? targeted[0] : (document.body ? (document.body.innerText || '').trim() : '');
        return text;
    }"""
    try:
        raw = page.evaluate(js)
    except Exception:
        logger.exception("본문 추출 evaluate 실패")
        raw = ""
    if not isinstance(raw, str):
        raw = str(raw)
    return raw.strip()[:TEXT_CAP]


def fetch_one(rank: int, url: str, title: str, port: int, profile: str) -> dict:
    """단일 URL 을 실제 브라우저로 방문→본문 수집. 실패해도 호출자로 dict 반환.

    Returns:
        {"rank", "url", "title", "source", "raw_text", "fetch_status", "note"}
    """
    source = detect_source(url)
    proc: subprocess.Popen | None = None
    bridge: CDPBridge | None = None
    try:
        logger.info("[%d] 방문 시작: %s", rank, url)
        proc = launch_chrome(port, profile)
        wait_for_cdp(port)
        bridge = CDPBridge(port=port)
        try:
            bridge.connect()
        except BotDetectionError as exc:
            logger.warning("[%d] 봇 탐지 차단: %s", rank, exc)
            return _fail(rank, url, title, source, f"bot_detection: {exc}")

        page = bridge.page
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)

        humanizer = Humanizer()
        # 인간 행동 시퀀스 (봇 탐지 회피).
        humanizer.think_pause()  # 페이지 인식 찰나
        humanizer.scroll_to_bottom(page, scrolls=3)  # 본문 훑기
        humanizer.think_pause()  # 읽기 체류
        hover_some_links(page, humanizer)  # 일부 링크 hover

        raw_text = extract_text(page)

        # 캡차/봇확인 벽 가벼운 탐지 (본문은 저장하되 note 에 기록).
        # ⚠ 단순 문자열 매칭('recaptcha' 등)은 GitHub/blog 의 HTML 에 흔히
        # 포함되어 FP 가 발생하므로, 실제 챌린지 iframe 또는 명시적 챌린지
        # 문구가 있을 때만 감지한다.
        note = ""
        try:
            if page.evaluate(
                "() => {"
                "const iframes = Array.from(document.querySelectorAll('iframe'));"
                "const captchaIframe = iframes.some((f) => {"
                "  const s = (f.src || f.getAttribute('src') || '').toLowerCase();"
                "  return s.includes('recaptcha') || s.includes('captcha') || s.includes('hcaptcha');"
                "});"
                "const t = (document.body && document.body.innerText || '').toLowerCase();"
                "const challenge = ['please verify you are human','confirm you are human',"
                "'verify you are a human','checking your browser','unusual traffic',"
                "'로봇 확인','자동 프로그램'].some((p) => t.includes(p));"
                "return captchaIframe || challenge;}"
            ):
                note = "captcha_wall_detected"
        except Exception:
            logger.debug("[%d] 캡차 스캔 실패 (무시)", rank)

        if not raw_text:
            return _fail(rank, url, title, source, "empty_body_text")

        status = "ok"
        logger.info(
            "[%d] 수집 성공 (source=%s, raw_len=%d)%s",
            rank,
            source,
            len(raw_text),
            f" [{note}]" if note else "",
        )
        return {
            "rank": rank,
            "url": url,
            "title": title,
            "source": source,
            "raw_text": raw_text,
            "fetch_status": status,
            "note": note,
        }
    except Exception as exc:
        logger.warning("[%d] 수집 실패: %s — %s", rank, url, exc)
        return _fail(rank, url, title, source, f"{type(exc).__name__}: {exc}")
    finally:
        if bridge is not None:
            try:
                bridge._safe_disconnect()
            except Exception:
                logger.debug("[%d] bridge disconnect 예외 (무시)", rank)
        terminate_chrome(proc, port)


def _fail(rank: int, url: str, title: str, source: str, reason: str) -> dict:
    return {
        "rank": rank,
        "url": url,
        "title": title,
        "source": source,
        "raw_text": "",
        "fetch_status": "failed",
        "note": reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase A: 논문 본문 실제 브라우저 수집")
    parser.add_argument(
        "--in",
        dest="in_path",
        default="/tmp/llm_final_10.json",
        help="입력 JSON (final_10[].url). 기본 /tmp/llm_final_10.json",
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        default="/tmp/llm_deep_10.json",
        help="출력 JSON. 기본 /tmp/llm_deep_10.json",
    )
    parser.add_argument("--port", type=int, default=9226, help="CDP 포트 (기본 9226)")
    parser.add_argument("--profile", default="deep", help="Chrome 프로파일명 (기본 deep)")
    args = parser.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        logger.error("입력 파일 없음: %s", in_path)
        return 2
    with in_path.open(encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("final_10") or data.get("papers") or []
    if not items:
        logger.error("입력에 final_10/papers 항목이 없습니다: %s", in_path)
        return 2

    logger.info("대상 %d건 수집 시작 (port=%s, profile=%s)", len(items), args.port, args.profile)

    papers: list[dict] = []
    failed: list[dict] = []
    for item in items:
        rank = item.get("rank")
        url = item.get("url")
        title = item.get("title", "")
        if not url:
            logger.warning("rank=%s url 누락 → 건너뜀", rank)
            continue
        result = fetch_one(rank, url, title, args.port, args.profile)
        papers.append(result)
        if result["fetch_status"] == "failed":
            failed.append(
                {
                    "rank": result["rank"],
                    "url": result["url"],
                    "reason": result["note"],
                }
            )

    out = {"papers": papers, "failed": failed}
    out_path = Path(args.out_path)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    ok_count = sum(1 for p in papers if p["fetch_status"] == "ok")
    logger.info(
        "완료: 총 %d건 / 성공 %d / 실패 %d → %s",
        len(papers),
        ok_count,
        len(failed),
        out_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
