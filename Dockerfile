# AgentBrowser — 전용 에이전트 브라우저 컨테이너 (M6)
#
# - Python 3.11 slim 베이스 + Chrome(stable) 설치
# - 프로젝트 코드(COPY src, scripts) + 의존성(pyproject)
# - 포트 미개방(pipe 모드 사용하므로 EXPOSE 불필요)
# - 볼륨: ./profiles (전용 프로파일), ./memory (FTS5용, RAG는 미사용이나 준비)
# - 헤드리스 아님(M5 headed 원칙) → 컨테이너 내 display 필요시 entrypoint 가 xvfb 사용
#
# 빌드:  docker build -t agentbrowser:m6 .
# 실행:  docker compose up   (env 주입 지문은 docker-compose.yml 참조)

# python:3.11-slim-bookworm — Debian bookworm 기반 (libasound2 등 Chrome 의존성 보유).
# (trixie 는 libasound2→libasound2t64 로 개명되어 google-chrome-stable 설치 실패)
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 컨테이너 내 Linux Chrome 경로 (launcher 가 CHROME_BIN 으로 읽음)
    CHROME_BIN=/usr/bin/google-chrome-stable

# 시스템 의존성 + Chrome 안정화에 필요한 라이브러리.
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget gnupg ca-certificates \
        xvfb \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
        fonts-liberation fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome stable (Linux) — apt 저장소 등록 후 설치.
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/googlechrome-linux-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/googlechrome-linux-keyring.gpg] \
        http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 복사(캐시 활용) 후 소스 복사.
COPY pyproject.toml ./
COPY src ./src
COPY scripts ./scripts

# 프로젝트 설치 (hatchling build-backend, editable 아님 — 컨테이너용 고정 설치).
RUN pip install --no-cache-dir .

# 전용 프로파일/메모리 볼륨 마운트 지점.
RUN mkdir -p /app/profiles /app/memory

# entrypoint: 컨테이너별 지문 인덱스 파생 + (필요시) xvfb 래핑 후 CMD 실행.
COPY scripts/docker_entrypoint.sh /usr/local/bin/docker_entrypoint.sh
RUN chmod +x /usr/local/bin/docker_entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker_entrypoint.sh"]
# 기본 CMD: 지문 주입이 명령줄/JS 에 반영되는지 컨테이너 내부에서 출력(probe).
# 실제 에이전트 구동 시 이 CMD 를 agent 진입점으로 교체.
CMD ["python", "-c", "import logging; logging.basicConfig(level=logging.INFO); from core.launcher import build_launch_command, build_fingerprint_bundle; print('M6_LAUNCH:', ' '.join(build_launch_command())); flags, js = build_fingerprint_bundle(); print('M6_JS_FINGERPRINT:', js)"]
