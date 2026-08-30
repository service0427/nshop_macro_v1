#!/usr/bin/env bash

# ========================================================================================
# Google Drive APK Auto-Downloader for N-Shop Macro (scripts/download_apks.sh)
# ========================================================================================
# - 불변 도구 패키지 (essential_tools: ADBKeyboard, GPSEmulator, WireGuard) 자동 다운로드
# - 최신 네이버 앱 패키지 (naver_app) 자동 다운로드 및 압축 해제
# - 커스텀 구글 드라이브 ID 입력 지원: ./scripts/download_apks.sh [NAVER_GDRIVE_ID]
# ========================================================================================

set -e

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
APKS_DIR="$BASE_DIR/apks"
mkdir -p "$APKS_DIR"

# 기본 구글 드라이브 파일 ID (사용자 등록본)
DEFAULT_ESSENTIAL_GDRIVE_ID="1FtUSY5r9WtrovZ9qE0JuG4OmKoEW9bP8"
DEFAULT_NAVER_GDRIVE_ID="1yYIKikx2E1MP5FMxv6TFIt2FRkk7gIHF"

NAVER_GDRIVE_ID=${1:-$DEFAULT_NAVER_GDRIVE_ID}
ESSENTIAL_GDRIVE_ID=$DEFAULT_ESSENTIAL_GDRIVE_ID

CYAN="\e[1;36m"
GREEN="\e[1;32m"
YELLOW="\e[1;33m"
NC="\e[0m"

echo -e "${CYAN}==========================================================================${NC}"
echo -e "${CYAN} 📦 N-Shop Macro Google Drive APK Auto-Downloader${NC}"
echo -e "${CYAN}==========================================================================${NC}"

# gdown 설치 확인
if ! command -v gdown &> /dev/null; then
    echo -e "${YELLOW}[*] gdown 다운로더 설치 중...${NC}"
    pip3 install --break-system-packages gdown || pip3 install gdown
fi

# 1. 필수 도구 패키지 다운로드 & 압축 해제 (ADBKeyboard, GPSEmulator, WireGuard)
if [ ! -f "$APKS_DIR/essential_tools.tar.gz" ] || [ ! -d "$APKS_DIR/wireguard" ]; then
    echo -e "\n${YELLOW}[*] [1/2] 필수 도구 패키지(essential_tools) 다운로드 중 (ID: $ESSENTIAL_GDRIVE_ID)...${NC}"
    gdown "$ESSENTIAL_GDRIVE_ID" -O "$APKS_DIR/essential_tools.tar.gz"
    echo -e "      ↳ 압축 해제 중..."
    tar -xzf "$APKS_DIR/essential_tools.tar.gz" -C "$APKS_DIR/"
    echo -e "${GREEN}      ↳ [✓] 필수 도구 설치 파일 준비 완료!${NC}"
else
    echo -e "\n${GREEN}[✓] [1/2] 필수 도구 패키지 이미 존재함 (건너뜀)${NC}"
fi

# 2. 네이버 앱 최신 패키지 다운로드 & 압축 해제
echo -e "\n${YELLOW}[*] [2/2] 네이버 앱 패키지(naver_app) 다운로드 중 (ID: $NAVER_GDRIVE_ID)...${NC}"
mkdir -p "$APKS_DIR/naver_app"
gdown "$NAVER_GDRIVE_ID" -O "$APKS_DIR/naver_app_latest.tar.gz"
echo -e "      ↳ 압축 해제 중..."
tar -xzf "$APKS_DIR/naver_app_latest.tar.gz" -C "$APKS_DIR/naver_app/"
echo -e "${GREEN}      ↳ [✓] 네이버 앱 설치 파일 준비 완료!${NC}"

echo -e "\n${CYAN}==========================================================================${NC}"
echo -e "${GREEN} 🎉 모든 APK 다운로드 및 배포 준비가 성공적으로 완료되었습니다!${NC}"
echo -e "${CYAN}==========================================================================${NC}\n"
