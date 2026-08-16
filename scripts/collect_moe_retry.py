#!/usr/bin/env python3
"""Phase A-2 보충: 차단된 HF 페이지 재시도(대기시간↑) + 누락 MoE 소스 방문.

collect_moe.py 와 동일 인프라(headed Chrome + CDP + Humanizer) 사용.
출력: /tmp/moe_raw_supp.json
"""

from __future__ import annotations

import json
import logging
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("collect_moe_retry")
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PAGE_GOTO_TIMEOUT_MS = 45_000
CDP_WAIT_MAX_S = 30.0
TEXT_CAP = 30_000
WAIT_AFTER_LOAD_S = 8.0  # HF JS 카드 로딩 대기


def free_port(port: int) -> None:
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True, timeout=10).stdout
        for pid in {p.strip() for p in out.split() if p.strip().isdigit()}:
            try:
                subprocess.run(["kill", "-9", pid], check=False, timeout=5)
            except Exception:
                pass
    except Exception:
        pass
    time.sleep(0.5)


def launch_chrome(port: int, profile: str) -> subprocess.Popen:
    free_port(port)
    cmd = build_launch_command(profile, port)
    log_path = LOG_DIR / f"collect_moe_retry_{port}.log"
    with log_path.open("wb") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    logger.info("Chrome PID=%s", proc.pid)
    return proc


def terminate_chrome(proc, port):
    if proc is not None:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass
    free_port(port)


def wait_for_cdp(port):
    deadline = time.time() + CDP_WAIT_MAX_S
    while time.time() < deadline:
        if is_chrome_running(port):
            return
        time.sleep(0.5)
    raise TimeoutError(f"CDP_TIMEOUT_{port}")


def hover_some_links(page, humanizer):
    try:
        links = page.query_selector_all("a[href]")
        if not links:
            return
        for link in __import__("random").sample(links, min(3, len(links))):
            box = link.bounding_box()
            if not box:
                continue
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            time.sleep(0.15)
    except Exception:
        pass


def extract_text(page, cap=TEXT_CAP):
    js = r"""() => {
        const pick = (sel) => { const el=document.querySelector(sel); return el?(el.innerText||'').trim():''; };
        const targeted = [pick('#abstract'), pick('.abstract-text'), pick('article'),
            pick('.markdown-body'), pick('#readme article'), pick('.c-article-body'),
            pick('main'), pick('#content'), pick('.model-card'), pick('#model_card')].filter(t=>t.length>0);
        let text = targeted.length ? targeted[0] : (document.body?(document.body.innerText||'').trim():'');
        return text;
    }"""
    try:
        raw = page.evaluate(js)
    except Exception:
        raw = ""
    return (raw if isinstance(raw, str) else str(raw)).strip()[:cap]


_CAPTCHA_JS = ("(() => { const b=(document.body&&document.body.innerText)||''; const h=document.documentElement.outerHTML||'';"
               " const s=(b+' '+h).toLowerCase();"
               " return ['captcha','로봇 확인','unusual traffic','recaptcha','vaptcha','verify you are human','checking your browser'].some(p=>s.includes(p));})()")


def fetch_one(url, source_type, label, bridge, humanizer):
    try:
        logger.info("방문: %s (%s)", label, url)
        page = bridge.page
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)
        time.sleep(WAIT_AFTER_LOAD_S)  # JS 카드/API 로딩 대기
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
            pass
        if not raw_text:
            return {"url": url, "source_type": source_type, "label": label, "raw_text": "", "fetch_status": "failed", "note": "empty_body"}
        logger.info("수집 %s (len=%d)%s", label, len(raw_text), f" [{note}]" if note else "")
        return {"url": url, "source_type": source_type, "label": label, "raw_text": raw_text, "fetch_status": "ok", "note": note}
    except Exception as exc:
        logger.warning("실패 %s: %s", url, exc)
        return {"url": url, "source_type": source_type, "label": label, "raw_text": "", "fetch_status": "failed", "note": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    port = 9232
    profile = "moe_retry"
    targets = [
        ("https://huggingface.co/deepseek-ai/DeepSeek-V3", "hf_card", "DeepSeek-V3 card(retry)"),
        ("https://huggingface.co/collections/Qwen/qwen25", "hf_card", "Qwen2.5-MoE collection(retry)"),
        ("https://huggingface.co/blog/moe", "hf_blog", "HF MoE overview(retry)"),
        ("https://arxiv.org/html/2401.04088v1", "arxiv", "Mixtral of Experts"),
        ("https://arxiv.org/html/2412.15115v1", "arxiv", "Qwen2.5 tech report"),
    ]
    proc = launch_chrome(port, profile)
    bridge = None
    try:
        wait_for_cdp(port)
        bridge = CDPBridge(port=port)
        try:
            bridge.connect()
        except BotDetectionError as exc:
            logger.error("봇 탐지: %s", exc)
            return 1
        humanizer = Humanizer()
        results = [fetch_one(u, s, l, bridge, humanizer) for (u, s, l) in targets]
        with open("/tmp/moe_raw_supp.json", "w", encoding="utf-8") as f:
            json.dump({"results": results}, f, ensure_ascii=False, indent=2)
        ok = sum(1 for r in results if r["fetch_status"] == "ok")
        logger.info("완료: %d/%d → /tmp/moe_raw_supp.json", ok, len(results))
    finally:
        try:
            bridge._safe_disconnect()
        except Exception:
            pass
        terminate_chrome(proc, port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
