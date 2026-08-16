// background.js — AgentBrowser MV3 Service Worker (메시지 라우터 + 인메모리 저장소 + Python bridge 스텁)
// 근거: docs/reports/02_implementation_design.md §2(아키텍처)·§3(핸드오프 스키마)·§9(MV3 수명 제약)
// 등록 가정: manifest.json 의 service_worker. 권한(host_permissions 등)은 manifest 에서 관리.

// --- 인메모리 저장소 (MVP) ---------------------------------------------------
// [반대증거] MV3 Service Worker 는 수명이 제한되어 장시간 유지 불가.
// 따라서 영속화는 후속 과제이며, 실제 세션 상태는 Python bridge 가 보유한다 (§9).
const handoffs = [];   // HANDOFF 배열: {url, dom_snapshot, intent, constraints, timestamp}
const hitlQueue = [];  // HITL 큐: {reason, url, timestamp}

// --- Python bridge 전송 ------------------------------------------------------
// Background↔Python 통신은 로컬 HTTP bridge(bridge_server :10899) 로 격리 (§2).
// 전송 대상은 127.0.0.1 로컬 한정. MV3 SW 자체 fetch 요청은 CORS 무관 (OK).
// 인메모리 백업(handoffs[]/hitlQueue[])는 호출부의 push 에서 선행 유지.
function forwardToAgent(handoff) {
  // 실제 전송: 로컬 Python bridge 로 HANDOFF 를 POST.
  fetch("http://127.0.0.1:10899/handoff", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(handoff),
  })
    .then((r) => r.json())
    .catch((e) => console.error("bridge 전송 실패", e));
}

// HITL(인간 개입 요청)도 동일 bridge 로 전송.
function sendHITL(hitl) {
  fetch("http://127.0.0.1:10899/hitl", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(hitl),
  })
    .then((r) => r.json())
    .catch((e) => console.error("bridge 전송 실패", e));
}

// --- 메시지 라우터 -----------------------------------------------------------
// CS / 팝업 / 외부에서 chrome.runtime.sendMessage 로 호출.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message.type !== "string") {
    return; // 타입 없는 메시지는 무시
  }

  switch (message.type) {
    // R3 핸드오프: url, dom_snapshot, intent, constraints, timestamp
    case "HANDOFF": {
      const payload = message.payload || {};
      const handoff = {
        url: payload.url,
        dom_snapshot: payload.dom_snapshot,
        intent: payload.intent,
        constraints: payload.constraints,
        timestamp: payload.timestamp || new Date().toISOString(),
      };
      handoffs.push(handoff);
      forwardToAgent(handoff); // Python core(:10899) 로 실제 전송
      sendResponse({ ok: true, count: handoffs.length });
      return;
    }

    // HITL: 인간 개입 필요 지점(예: 캡차)을 큐에 보관하고 경고 표시 (§6)
    case "HITL": {
      const item = {
        reason: message.reason,
        url: message.url,
        timestamp: message.timestamp || new Date().toISOString(),
      };
      hitlQueue.push(item);
      sendHITL(item); // Python core 로 전송
      console.warn("[HITL] 인간 개입 필요:", item.reason, item.url);
      sendResponse({ ok: true, queued: hitlQueue.length });
      return;
    }

    // 팝업/외부 조회용: 현재 누적된 handoffs 반환
    case "GET_HANDOFFS": {
      sendResponse({ handoffs: handoffs, hitlQueue: hitlQueue });
      return;
    }

    // RESUME: 사용자가 배너 [재개] 클릭 시 수신. Python core(:10899/resume) 로 URL 전달.
    // [회피 금지] 단순 협업 흐름 — 봇 회피 로직 없음. 서버 미구현 시 fetch 실패는 catch 무시.
    case "RESUME": {
      const resumeUrl = message.url;
      console.log("[RESUME] 재개 요청 수신:", resumeUrl);
      fetch("http://127.0.0.1:10899/resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: resumeUrl }),
      })
        .then((r) => r.json())
        .then((data) => console.log("[RESUME] 서버 응답:", data))
        .catch((e) => console.error("[RESUME] bridge 전송 실패:", e));
      sendResponse({ ok: true, url: resumeUrl });
      return;
    }

    default:
      // 정의되지 않은 타입은 무시
      return;
  }
});

// [회피 금지] navigator.webdriver 조작·봇 회피 우회 로직은 일절 포함하지 않음 (§3 R2).
// 익스텐션 레이어는 회피 목적으로 사용하지 않음.
