#!/usr/bin/env bash

# ========================================================================================
# N-Shop Macro Client Host & PM2 Production Setup Script (pm2_setup.sh)
# ========================================================================================
# [신규 클라이언트 PC 원클릭 셋업 1단계]
# 1. 시스템 필수 도구 (ADB, Python3, Node.js, PM2, usbreset, gdown) 자동 설치
# 2. Python 필수 의존성 (requirements.txt) 설치
# 3. 구글 드라이브에서 필수 APK 패키지 (essential_tools, naver_app) 자동 다운로드
# 4. PM2 서비스 등록 (nshop-macro-daemon) 및 재부팅 시 자동 가동 (Systemd) 등록
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
echo -e "${CYAN} 🚀 N-Shop Macro Production Setup & PM2 Service Registration${NC}"
echo -e "${CYAN}    Root: $PROJECT_ROOT${NC}"
echo -e "${CYAN}==========================================================================${NC}"

# 1. 시스템 패키지 설치
echo -e "\n${YELLOW}[*] [1/5] 호스트 시스템 패키지 확인 및 설치 중...${NC}"
sudo apt update -y >/dev/null 2>&1 || true
sudo apt install -y android-tools-adb usbutils python3 python3-pip curl git build-essential >/dev/null 2>&1 || true

# usbreset 빌드 및 설치 (없을 경우)
if ! command -v usbreset &> /dev/null; then
    echo -e "      ↳ usbreset 유틸리티 빌드 및 설치 중..."
    cat << 'EOF' > /tmp/usbreset.c
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <linux/usbdevice_fs.h>

int main(int argc, char **argv) {
    const char *filename;
    int fd;
    int rc;

    if (argc != 2) {
        fprintf(stderr, "Usage: usbreset /dev/bus/usb/BBB/DDD or BBB/DDD\n");
        return 1;
    }
    filename = argv[1];

    char path[128];
    if (filename[0] != '/') {
        snprintf(path, sizeof(path), "/dev/bus/usb/%s", filename);
        filename = path;
    }

    fd = open(filename, O_WRONLY);
    if (fd < 0) {
        perror("Error opening device file");
        return 1;
    }

    printf("Resetting USB device %s\n", filename);
    rc = ioctl(fd, USBDEVFS_RESET, 0);
    if (rc < 0) {
        perror("Error in ioctl");
        close(fd);
        return 1;
    }
    printf("Reset successful\n");

    close(fd);
    return 0;
}
EOF
    gcc /tmp/usbreset.c -o /tmp/usbreset
    sudo mv /tmp/usbreset /usr/local/bin/usbreset
    sudo chmod +x /usr/local/bin/usbreset
    rm -f /tmp/usbreset.c
    echo -e "${GREEN}      ↳ [✓] usbreset 설치 완료!${NC}"
fi

# 2. Node.js & PM2 확인 및 설치
echo -e "\n${YELLOW}[*] [2/5] Node.js 및 PM2 프로세스 매니저 확인 중...${NC}"
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

# 3. Python 의존성 설치
echo -e "\n${YELLOW}[*] [3/5] Python 라이브러리 및 gdown 설치 중...${NC}"
pip3 install --break-system-packages -r requirements.txt gdown >/dev/null 2>&1 || pip3 install -r requirements.txt gdown >/dev/null 2>&1
echo -e "${GREEN}      ↳ [✓] Python 패키지 설치 완료!${NC}"

# 4. 필수 디렉터리 및 구글 드라이브 APK 다운로드
echo -e "\n${YELLOW}[*] [4/5] 로깅 디렉터리 및 구글 드라이브 APK 동기화 중...${NC}"
mkdir -p logs/allocate_history logs/release_history logs/target_screenshot logs/battery_history click_logs apks

if [ -f "$PROJECT_ROOT/scripts/download_apks.sh" ]; then
    chmod +x "$PROJECT_ROOT/scripts/download_apks.sh"
    "$PROJECT_ROOT/scripts/download_apks.sh"
fi

# 5. PM2 서비스 등록 및 Systemd 시작 서비스 설정
echo -e "\n${YELLOW}[*] [5/5] PM2 서비스 등록 및 부팅 시 자동 시작(Systemd) 설정 중...${NC}"

# 기존 등록된 인스턴스가 있다면 정리
pm2 delete nshop-macro-daemon >/dev/null 2>&1 || true

# ecosystem.config.js 기반 실행
pm2 start ecosystem.config.js

# PC 재부팅 시 자동 가동을 위한 Systemd startup 등록 & 상태 저장
pm2 save

# PM2 startup 등록 (실패 시 안내)
sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u $USER --hp $HOME >/dev/null 2>&1 || true

echo -e "\n${CYAN}==========================================================================${NC}"
echo -e "${GREEN} 🎉 [1단계] 클라이언트 호스트 & PM2 셋업이 완벽히 완료되었습니다!${NC}"
echo -e "${CYAN}==========================================================================${NC}"
echo -e "\n${YELLOW}다음 단계 (2단계):${NC}"
echo -e "  1. 단말기들을 USB로 연결합니다."
echo -e "  2. 단말기 초기화 명령을 실행합니다: ${GREEN}./device_init.sh${NC}"
echo -e "  3. PM2 실시간 가동 상태 확인:       ${CYAN}pm2 logs nshop-macro-daemon${NC}"
echo -e "${CYAN}==========================================================================${NC}\n"
