// AgentBrowser Content Script (MV3, vanilla JS)
// 역할: 페이지 DOM 추출 → Background(Service Worker)로 핸드오프 전송, 캡차/HITL 감지.
// 원칙: 익스텐션 회피 금지 — navigator.webdriver 등 봇회피 우회 코드 일절 없음(순수 추출/전달).

// DOM 추출: 선택자 기반으로 주요 콘텐츠를 JSON 직렬화 가능한 객체로 수집.
function extractDOM() {
  const pick = (sel) => {
    const el = document.querySelector(sel);
    return el ? el.innerText.trim() : null;
  };
  const links = Array.from(document.querySelectorAll('a[href]'))
    .slice(0, 50)
    .map((a) => ({ text: a.innerText.trim(), href: a.href }));
  return {
    title: document.title,
    url: location.href,
    headings: {
      h1: pick('h1'),
      h2: pick('h2'),
    },
    main: pick('main') || pick('article') || pick('#content'),
    links,
    extractedAt: new Date().toISOString(),
  };
}

// 캡차/HITL 감지: h1/title 텍스트 패턴 또는 캡차 컨테이너 존재 여부.
function detectCaptcha() {
  const text = (document.title + ' ' + (document.querySelector('h1')?.innerText || '')).toLowerCase();
  const patterns = ['verify you are human', 'captcha', 'unusual traffic'];
  const matched = patterns.some((p) => text.includes(p));
  const container = document.querySelector('#captcha, #recaptcha, .g-recaptcha');
  return matched || !!container;
}

// 핸드오프 전송(§3 스키마): url, dom_snapshot, intent, constraints, timestamp.
function sendHandoff(intent = '', constraints = []) {
  const payload = {
    type: 'HANDOFF',
    url: location.href,
    dom_snapshot: extractDOM(),
    intent,
    constraints, // §3 스키마: string[] (메시지 미수신 시 빈 배열)
    timestamp: new Date().toISOString(),
  };
  chrome.runtime.sendMessage(payload, () => {
    if (chrome.runtime.lastError) console.warn('[CS] handoff 전송 실패:', chrome.runtime.lastError.message);
  });
}

// HITL 전송: 캡차 감지 시 인간 위임 알림.
function sendHITL(reason) {
  chrome.runtime.sendMessage({
    type: 'HITL',
    reason,
    url: location.href,
    timestamp: new Date().toISOString(),
  });
}

// 트리거 1: 외부(window.postMessage)로부터 핸드오프 요청 수신.
window.addEventListener('message', (e) => {
  if (e.source !== window) return;
  const msg = e.data;
  if (msg && msg.type === 'AGENTBROWSER_HANDOFF') {
    sendHandoff(msg.intent || '', msg.constraints || []);
  }
});

// 트리거 2: URL 변경 감지(SPA 대응: History API + popstate).
let lastUrl = location.href;
function checkUrlChange() {
  if (location.href !== lastUrl) {
    lastUrl = location.href;
    sendHandoff(); // intent/constraints 미지정 → 기본값
  }
}
['pushState', 'replaceState'].forEach((m) => {
  const orig = history[m];
  history[m] = function (...args) {
    const ret = orig.apply(this, args);
    checkUrlChange();
    return ret;
  };
});
window.addEventListener('popstate', checkUrlChange);

// 캡차 배너 주입(순수 협업 UI — §4 회피 금지): 화면 우상단 고정 div + [재개] 버튼.
// 이미 떠있으면 중복 생성 방지(document.getElementById 체크).
function showCaptchaBanner() {
  if (document.getElementById('agentbrowser-hitl-banner')) return; // 중복 방지

  const banner = document.createElement('div');
  banner.id = 'agentbrowser-hitl-banner';
  banner.setAttribute('style',
    'position:fixed; top:10px; right:10px; z-index:2147483647; ' +
    'background:#222; color:#fff; padding:8px; border-radius:6px; font-size:13px;');

  // 안내 텍스트
  const label = document.createElement('span');
  label.textContent = '⚠ 캡차 발생 — 개입 필요';
  banner.appendChild(label);

  // [재개] 버튼: RESUME 메시지 전송 + 배너 제거(협업 해제).
  const resumeBtn = document.createElement('button');
  resumeBtn.textContent = '재개';
  resumeBtn.setAttribute('style',
    'margin-left:8px; cursor:pointer; background:#3b82f6; color:#fff; ' +
    'border:none; border-radius:4px; padding:4px 8px; font-size:13px;');
  resumeBtn.addEventListener('click', () => {
    // Background 로 RESUME 전송(서버 미구현 시 fetch 실패는 catch 로 무시).
    chrome.runtime.sendMessage({ type: 'RESUME', url: location.href }, () => {
      if (chrome.runtime.lastError) {
        console.warn('[CS] RESUME 전송 실패:', chrome.runtime.lastError.message);
      }
    });
    banner.remove(); // 협업 UI 해제
  });
  banner.appendChild(resumeBtn);

  (document.body || document.documentElement).appendChild(banner);
}

// 캡차 감지 루프(로드 직후 + 주기적).
function scanCaptcha() {
  if (detectCaptcha()) {
    sendHITL('captcha_detected'); // 기존 HITL 알림 유지
    showCaptchaBanner();          // 협업 UI 배너 표시(중복 시 무시)
  }
}
scanCaptcha();
setInterval(scanCaptcha, 2000);
