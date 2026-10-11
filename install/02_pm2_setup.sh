#!/usr/bin/env bash

# ========================================================================================
# [02 단계] N-Shop Macro PM2 Production Service & APK Setup (02_pm2_setup.sh)
# ========================================================================================
# 1. Node.js 20.x 및 PM2 프로세스 매니저 설치
# 2. Python 라이브러리 (requirements.txt, gdown) 설치
# 3. 구글 드라이브에서 필수 APK (essential_tools, naver_app) 자동 다운로드 및 압축 해제
# 4. PM2 서비스 등록 (nshop-macro-daemon) 및 PC 재부팅 시 자동 가동 (Systemd) 등록
# ========================================================================================

set -e

PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_ROOT" || exit 1

CYAN="\e[1;36m"
GREEN="\e[1;32m"
YELLOW="\e[1;33m"
RED="\e[1;31m"
NC="\e[0m"

echo -e "${CYAN}==========================================================================${NC}"
echo -e "${CYAN} 🚀 [02단계] N-Shop Macro PM2 무한가동 서비스 등록 및 APK 동기화${NC}"
echo -e "${CYAN}    Root: $PROJECT_ROOT${NC}"
echo -e "${CYAN}==========================================================================${NC}"

# 1. Node.js & PM2 확인 및 설치
echo -e "\n${YELLOW}[*] [1/4] Node.js 및 PM2 프로세스 매니저 확인 중...${NC}"
if ! command -v node &> /dev/null; then
    echo -e "      ↳ Node.js 20.x 설치 중..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
    sudo apt install -y nodejs >/dev/null 2>&1
fi

if ! command -v pm2 &> /dev/null; then
    echo -e "      ↳ PM2 글로벌 설치 중..."
    sudo npm install -g pm2 >/dev/null 2>&1
fi
echo -e "${GREEN}      ↳ [✓] Node.js ($(node -v)) / PM2 ($(pm2 -v)) 확인 완료!${NC}"

# 2. Python 의존성 설치
echo -e "\n${YELLOW}[*] [2/4] Python 라이브러리 및 gdown 설치 중...${NC}"
pip3 install --break-system-packages -r requirements.txt gdown >/dev/null 2>&1 || pip3 install -r requirements.txt gdown >/dev/null 2>&1
echo -e "${GREEN}      ↳ [✓] Python 패키지 설치 완료!${NC}"

# 3. 필수 디렉터리 생성 및 구글 드라이브 APK 다운로드
echo -e "\n${YELLOW}[*] [3/4] 로깅 디렉터리 생성 및 구글 드라이브 APK 동기화 중...${NC}"
mkdir -p logs/allocate_history logs/release_history logs/target_screenshot logs/battery_history click_logs apks

if [ -f "$PROJECT_ROOT/scripts/download_apks.sh" ]; then
    chmod +x "$PROJECT_ROOT/scripts/download_apks.sh"
    "$PROJECT_ROOT/scripts/download_apks.sh"
fi

# 4. PM2 서비스 등록 및 Systemd 시작 서비스 설정
echo -e "\n${YELLOW}[*] [4/4] PM2 서비스 등록 및 부팅 시 자동 시작(Systemd) 설정 중...${NC}"

# 기존 등록된 인스턴스가 있다면 정리
pm2 delete nshop-macro-daemon >/dev/null 2>&1 || true

# ecosystem.config.js 기반 실행
pm2 start ecosystem.config.js

# PC 재부팅 시 자동 가동을 위한 Systemd startup 등록 & 상태 저장
pm2 save

# PM2 startup 등록
sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u $USER --hp $HOME >/dev/null 2>&1 || true

echo -e "\n${CYAN}==========================================================================${NC}"
echo -e "${GREEN} 🎉 [02단계] PM2 무한가동 서비스 및 APK 동기화가 완벽히 완료되었습니다!${NC}"
echo -e "${CYAN}==========================================================================${NC}"
echo -e "\n${YELLOW}다음 단계 (03단계):${NC}"
echo -e "  1. 단말기들을 USB로 연결합니다."
echo -e "  2. 단말기 일괄 초기화 명령 실행: ${GREEN}./03_device_init.sh${NC}"
echo -e "  3. PM2 실시간 가동 상태 확인:   ${CYAN}pm2 logs nshop-macro-daemon${NC}"
echo -e "${CYAN}==========================================================================${NC}\n"
