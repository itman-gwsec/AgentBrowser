#!/usr/bin/env bash
# AgentBrowser 컨테이너 entrypoint (M6)
#
# 역할:
#   1) CHROME_CONTAINER_INDEX 미설정 시 hostname 기반 결정적 인덱스 파생
#      (docker compose --scale 시 컨테이너마다 다른 지문 drift 부여 — 나머지 연산).
#   2) DISPLAY 가 없으면 xvfb-run 으로 가상 디스플레이 래핑 (headed 원칙 유지).
#   3) 준비 완료 후 전달된 CMD 실행.
#
# 에러는 stderr 로 남기고, 지문 파생 실패 시 index=0(단일 컨테이너)으로 보수 진행.

set -euo pipefail

# ── 1) 컨테이너별 지문 인덱스 파생 ─────────────────────────────────────────────
if [ -z "${CHROME_CONTAINER_INDEX:-}" ]; then
  H="${HOSTNAME:-agentbrowser}"
  IDX=0
  # hostname 문자열을 단순 해시로 환산 후 나머지 연산 → 결정적 인덱스.
  len=${#H}
  i=0
  while [ "$i" -lt "$len" ]; do
    c=$(printf '%d' "'${H:$i:1}")
    IDX=$(( (IDX * 31 + c) % 100000 ))
    i=$((i + 1))
  done
  export CHROME_CONTAINER_INDEX="$IDX"
  echo "[entrypoint] CHROME_CONTAINER_INDEX 파생: ${CHROME_CONTAINER_INDEX} (hostname=${H})" >&2
else
  echo "[entrypoint] CHROME_CONTAINER_INDEX(env): ${CHROME_CONTAINER_INDEX}" >&2
fi

# ── 2) DISPLAY 없으면 xvfb 가상 디스플레이 ─────────────────────────────────────
if [ -z "${DISPLAY:-}" ]; then
  export DISPLAY=":99"
  echo "[entrypoint] DISPLAY 미설정 → xvfb-run(:99) 로 래핑" >&2
  # xvfb-run 이 인자 앞에 오도록 재귀 실행.
  exec xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" "$0" "$@"
fi

echo "[entrypoint] 지문 주입 준비 완료 (CHROME_CONTAINER_INDEX=${CHROME_CONTAINER_INDEX}, DISPLAY=${DISPLAY})" >&2

# ── 3) CMD 실행 ────────────────────────────────────────────────────────────────
exec "$@"
