#!/usr/bin/env python3
"""Qwen2.5 기술보고서 재방문: MoE-A14B 절이 30k cap 이후에 있으므로 대용량 캡으로 재수집."""
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT/"src") not in sys.path: sys.path.insert(0,str(PROJECT_ROOT/"src"))
import contextlib

from core.cdp_bridge import BotDetectionError, CDPBridge
from core.humanizer import Humanizer
from core.launcher import build_launch_command, is_chrome_running

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger=logging.getLogger("qwen25_refetch"); LOG_DIR=PROJECT_ROOT/"logs"; LOG_DIR.mkdir(parents=True,exist_ok=True)
PORT=9233; PROFILE="qwen25"
def free_port(p):
    try:
        out=subprocess.run(["lsof","-ti",f"tcp:{p}"],capture_output=True,text=True,timeout=10).stdout
        for pid in {x.strip() for x in out.split() if x.strip().isdigit()}:
            with contextlib.suppress(Exception): subprocess.run(["kill","-9",pid],check=False,timeout=5)
    except Exception: pass
    time.sleep(0.5)
def launch(port,prof):
    free_port(port); cmd=build_launch_command(prof,port)
    log=LOG_DIR/f"qwen25_{port}.log"
    with log.open("wb") as f: proc=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT)
    return proc
def term(proc,port):
    if proc and proc.poll() is None:
        try: proc.terminate(); proc.wait(timeout=5)
        except Exception: proc.kill()
    free_port(port)
def wait_cdp(port):
    d=time.time()+30
    while time.time()<d:
        if is_chrome_running(port): return
        time.sleep(0.5)
    raise TimeoutError("CDP_TO")
def extract(page,cap):
    js=r"""()=>{const pick=sel=>{const e=document.querySelector(sel);return e?(e.innerText||'').trim():''};const t=[pick('#abstract'),pick('.abstract-text'),pick('article'),pick('main'),pick('#content')].filter(x=>x.length>0);let s=t.length?t[0]:(document.body?(document.body.innerText||'').trim():'');return s;}"""
    try: raw=page.evaluate(js)
    except Exception: raw=""
    return (raw if isinstance(raw,str) else str(raw)).strip()[:cap]

def main():
    url="https://arxiv.org/html/2412.15115v1"
    proc=launch(PORT,PROFILE); bridge=None
    try:
        wait_cdp(PORT); bridge=CDPBridge(port=PORT)
        try: bridge.connect()
        except BotDetectionError as e: logger.exception("bot: %s",e); return 1
        h=Humanizer(); page=bridge.page
        page.goto(url,wait_until="domcontentloaded",timeout=45000)
        time.sleep(8); h.think_pause(); h.scroll_to_bottom(page,scrolls=6); h.think_pause()
        text=extract(page,400000)
        # search for MoE-A14B
        import re
        hits=[]
        for kw in ['Qwen2.5-MoE','MoE-A14B','57B','14B activated','activated 14','A14B','57 billion','total parameters of 57']:
            for m in re.finditer(re.escape(kw),text,re.I):
                s=max(0,m.start()-120); hits.append(text[s:m.end()+200].replace('\n',' '))
        out={"url":url,"len":len(text),"hits":hits[:20]}
        with open("/tmp/qwen25_full.json","w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
        logger.info("saved /tmp/qwen25_full.json len=%d hits=%d",len(text),len(hits))
    finally:
        with contextlib.suppress(Exception): bridge._safe_disconnect()
        term(proc,PORT)
    return 0
if __name__=="__main__": sys.exit(main())
