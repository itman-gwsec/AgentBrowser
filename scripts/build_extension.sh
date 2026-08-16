#!/usr/bin/env bash
# AgentBrowser 익스텐션 자동빌드 + 로드 헬퍼 스크립트
# 동작:
#   1) src/extension 디렉터리를 builds/agentbrowser_extension/ 로 복사
#   2) zip 으로 배포용 패키징 시도 (zip 없으면 경고만)
#   3) 개발자모드 로드 경로 출력
# 사용: bash scripts/build_extension.sh

set -euo pipefail

# 스크립트 위치 기준으로 프로젝트 루트 계산 (scripts/ 의 상위)
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

SRC_DIR="$PROJECT_ROOT/src/extension"
BUILD_DIR="$PROJECT_ROOT/builds/agentbrowser_extension"
ZIP_PATH="$PROJECT_ROOT/builds/agentbrowser_extension.zip"

echo "[build_extension] 프로젝트 루트: $PROJECT_ROOT"

# 소스 디렉터리 존재 확인
if [ ! -d "$SRC_DIR" ]; then
  echo "오류: 소스 디렉터리가 없습니다: $SRC_DIR" >&2
  exit 1
fi

# 이전 빌드 결과 제거 후 재생성 (idempotent)
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# 익스텐션 파일 복사 (manifest.json + js 등 하위 구조 유지)
cp -R "$SRC_DIR/." "$BUILD_DIR/"

echo "[build_extension] 복사 완료: $BUILD_DIR"

# 배포용 zip 패키징 (zip 명령어가 없으면 경고만 하고 계속)
if command -v zip >/dev/null 2>&1; then
  rm -f "$ZIP_PATH"
  # -r: 재귀, -q: 조용히. BUILD_DIR 안으로 진입해 상대경로(. )로 압축 →
  # zip 내부 루트에 manifest.json 이 위치하도록 함 (Chrome 확장 패키지 표준 구조).
  (cd "$BUILD_DIR" && zip -r -q "$ZIP_PATH" .)
  echo "[build_extension] 패키징 완료: $ZIP_PATH"
else
  echo "[build_extension] 경고: zip 명령어가 없어 배포용 zip 생성을 건너뜁니다."
fi

# 개발자모드 로드 경로 안내
echo ""
echo "로드 경로: $BUILD_DIR"
echo "(chrome://extensions → 개발자모드 → 압축해제된 확장 로드)"
