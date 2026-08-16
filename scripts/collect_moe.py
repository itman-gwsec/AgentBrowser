#!/usr/bin/env python3
"""Phase A-2: MoE 오픈가중치 모델 후보 URL 방문 → 정량수치 수집.

fetch_papers_deep.py 패턴 재사용:
    - headed Chrome 기동(--enable-automation 없음 → webdriver=false)
    - CDPBridge.attach 로 동일 탭 제어
    - Humanizer 로 인간행동(think_pause→scroll→think_pause→hover)
    - 본문 텍스트 추출(정량수치 파싱용, 대용량 cap)
    - captcha/봇벽 가벼운 스캔

입력  : /tmp/moe_pool.json (후보 풀)
출력  : /tmp/moe_raw.json  (방문 원본 텍스트 + 메타)
        /tmp/moe_models.json (구조화 정량수치, 이 스크립트는 raw 까지만)

주의: 단일 에이전트 독점 수집(하위 위임 금지). print 금지 → logger.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

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
logger = logging.getLogger("collect_moe")

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

PAGE_GOTO_TIMEOUT_MS = 45_000
CDP_WAIT_MAX_S = 30.0
TEXT_CAP = 30_000  # 정량수치가 본문 하단에 있을 수 있어 충분히 큼


# ── 후보 선정 (공식 모델카드/문서 우선) ────────────────────────────────────
def select_candidates(pool: list[dict]) -> list[dict]:
    """MoE 오픈가중치 후보 URL 을 우선순위대로 선별(최대 15, 중복제거)."""
    wanted = [
        # (url, source_type, label)
        ("https://huggingface.co/deepseek-ai/DeepSeek-V3", "hf_card", "DeepSeek-V3"),
        ("https://github.com/deepseek-ai/DeepSeek-V3/blob/main/README_WEIGHTS.md",
         "github", "DeepSeek-V3 weights"),
        ("https://arxiv.org/html/2409.02060v1", "arxiv", "Mixtral of Experts"),
        ("https://huggingface.co/collections/Qwen/qwen25", "hf_card", "Qwen2.5-MoE"),
        ("https://github.com/XueFuzhao/OpenMoE", "github", "OpenMoE"),
        ("https://github.com/Tencent-Hunyuan/Hy3", "github", "Hunyuan Hy3"),
        ("https://huggingface.co/blog/ResterChed/kimi-k3-model-overview-mxfp4-quantization-open-wei",
         "hf_blog", "Kimi K3"),
        ("https://arxiv.org/abs/2402.01739", "arxiv", "DeepSeekMoE"),
        ("https://insiderllm.com/guides/gpt-oss-guide-openai-local/", "blog", "gpt-oss"),
        ("https://rocm.blogs.amd.com/artificial-intelligence/instella-moe/README.html",
         "blog", "Instella-MoE"),
        ("https://arxiv.org/html/2412.19437v1", "arxiv", "DeepSeek-V3 tech report"),
        ("https://huggingface.co/blog/moe", "hf_blog", "HF MoE overview"),
        ("https://www.labellerr.com/blog/top-open-source-moe-llms/", "blog", "MoE list"),
        ("https://www.metatech.dev/blog/2026-05-27-local-ai-moe-models-mixtral-vs-qwen2-vs-deepseek-on-96gb-100148",
         "blog", "MoE on 96GB"),
        ("https://arxiv.org/abs/2607.24653", "arxiv", "Kimi K3 report"),
    ]
    seen: set[str] = set()
    out: list[dict] = []
    for url, source_type, label in wanted:
        if url in seen:
            continue
        seen.add(url)
        # 풀에 있는지 확인(없어도 방문 시도—direct URL 임)
        out.append({"url": url, "source_type": source_type, "label": label})
        if len(out) >= 15:
            break
    return out


def free_port(port: int) -> None:
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}"],
                             capture_output=True, text=True, timeout=10).stdout
        for pid in {p.strip() for p in out.split() if p.strip().isdigit()}:
            try:
                subprocess.run(["kill", "-9", pid], check=False, timeout=5)
            except Exception:
                logger.debug("kill 실패 %s", pid)
    except Exception:
        logger.debug("free_port 무시")
    time.sleep(0.5)


def launch_chrome(port: int, profile: str) -> subprocess.Popen:
    free_port(port)
    cmd = build_launch_command(profile, port)
    logger.info("Chrome 기동: %s", " ".join(cmd))
    log_path = LOG_DIR / f"collect_moe_chrome_{port}.log"
    with log_path.open("wb") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    logger.info("Chrome PID=%s", proc.pid)
    return proc


def terminate_chrome(proc: subprocess.Popen | None, port: int) -> None:
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            logger.debug("terminate 예외")
    free_port(port)


def wait_for_cdp(port: int) -> None:
    deadline = time.time() + CDP_WAIT_MAX_S
    while time.time() < deadline:
        if is_chrome_running(port):
            logger.info("CDP 준비 완료 port=%s", port)
            return
        time.sleep(0.5)
    raise TimeoutError(f"CDP_TIMEOUT_{port}")


def hover_some_links(page: Any, humanizer: Humanizer) -> None:
    try:
        links = page.query_selector_all("a[href]")
        if not links:
            return
        for link in __import__("random").sample(links, min(3, len(links))):
            box = link.bounding_box()
            if not box:
                continue
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            page.mouse.move(cx, cy)
            time.sleep(0.15)
    except Exception:
        logger.debug("hover 생략")


def extract_text(page: Any, cap: int = TEXT_CAP) -> str:
    js = r"""() => {
        const pick = (sel) => { const el=document.querySelector(sel); return el?(el.innerText||'').trim():''; };
        const targeted = [
            pick('#abstract'), pick('.abstract-text'), pick('article'),
            pick('.markdown-body'), pick('#readme article'), pick('.c-article-body'),
            pick('main'), pick('#content'), pick('.model-card')
        ].filter(t=>t.length>0);
        let text = targeted.length ? targeted[0] : (document.body?(document.body.innerText||'').trim():'');
        return text;
    }"""
    try:
        raw = page.evaluate(js)
    except Exception:
        logger.exception("본문 추출 실패")
        raw = ""
    if not isinstance(raw, str):
        raw = str(raw)
    return raw.strip()[:cap]


_CAPTCHA_JS = (
    "(() => {"
    "  const b=(document.body&&document.body.innerText)||'';"
    "  const h=document.documentElement.outerHTML||'';"
    "  const s=(b+' '+h).toLowerCase();"
    "  return ['captcha','로봇 확인','unusual traffic','recaptcha','vaptcha','verify you are human','checking your browser'].some(p=>s.includes(p));"
    "})()"
)


def fetch_one(url: str, source_type: str, label: str, bridge: CDPBridge,
              humanizer: Humanizer) -> dict:
    try:
        logger.info("방문: %s (%s)", label, url)
        page = bridge.page
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)

        # 인간행동 시퀀스 (필수): think_pause → scroll → think_pause → hover
        humanizer.think_pause()
        humanizer.scroll_to_bottom(page, scrolls=4)
        humanizer.think_pause()
        hover_some_links(page, humanizer)

        raw_text = extract_text(page)

        note = ""
        try:
            if page.evaluate(_CAPTCHA_JS):
                note = "captcha_wall_detected"
        except Exception:
            logger.debug("captcha 스캔 실패(무시)")

        if not raw_text:
            return {"url": url, "source_type": source_type, "label": label,
                    "raw_text": "", "fetch_status": "failed", "note": "empty_body"}

        logger.info("수집 성공 %s (len=%d)%s", label, len(raw_text),
                    f" [{note}]" if note else "")
        return {"url": url, "source_type": source_type, "label": label,
                "raw_text": raw_text, "fetch_status": "ok", "note": note}
    except Exception as exc:  # noqa: BLE001
        logger.warning("수집 실패 %s: %s", url, exc)
        return {"url": url, "source_type": source_type, "label": label,
                "raw_text": "", "fetch_status": "failed", "note": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", default="/tmp/moe_pool.json")
    parser.add_argument("--out", dest="out_path", default="/tmp/moe_raw.json")
    parser.add_argument("--port", type=int, default=9231)
    parser.add_argument("--profile", default="moe")
    args = parser.parse_args()

    with open(args.in_path, encoding="utf-8") as f:
        pool = json.load(f).get("pool", [])
    cands = select_candidates(pool)
    logger.info("선정 %d건", len(cands))

    proc = launch_chrome(args.port, args.profile)
    bridge = None
    try:
        wait_for_cdp(args.port)
        bridge = CDPBridge(port=args.port)
        try:
            bridge.connect()
        except BotDetectionError as exc:
            logger.error("봇 탐지 차단: %s", exc)
            return 1
        humanizer = Humanizer()
        results: list[dict] = []
        for c in cands:
            results.append(fetch_one(c["url"], c["source_type"], c["label"], bridge, humanizer))
        out = {"results": results}
        with open(args.out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        ok = sum(1 for r in results if r["fetch_status"] == "ok")
        logger.info("완료: %d/%d 성공 → %s", ok, len(results), args.out_path)
    finally:
        try:
            bridge._safe_disconnect()
        except Exception:
            pass
        terminate_chrome(proc, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
