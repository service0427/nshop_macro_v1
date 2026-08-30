#!/usr/bin/env bash

# ========================================================================================
# N-Shop Automation Macro Client PC Auto-Installation Script (install.sh)
# ========================================================================================
# - 필수 시스템 패키지 설치 (ADB, Python3, Node.js, PM2, usbreset)
# - Python 패키지 의존성 설치
# - PM2 부팅 시 자동 시작(Systemd) 등록
# - 디렉터리 및 권한 셋업
# ========================================================================================

set -e

CYAN="\e[1;36m"
GREEN="\e[1;32m"
YELLOW="\e[1;33m"
NC="\e[0m"

echo -e "${CYAN}==========================================================================${NC}"
echo -e "${CYAN} 🚀 N-Shop Macro Client Host Setup & Auto-Installer${NC}"
echo -e "${CYAN}==========================================================================${NC}"

# 1. 시스템 패키지 업데이트 및 필수 도구 설치
echo -e "${YELLOW}[*] [1/5] 시스템 패키지 설치 (adb, python3-pip, usbreset, curl)...${NC}"
sudo apt update -y
sudo apt install -y android-tools-adb usbutils python3 python3-pip python3-venv curl git build-essential

# usbreset 컴파일 및 /usr/local/bin 배치 (없을 경우)
if ! command -v usbreset &> /dev/null; then
    echo -e "${YELLOW}      ↳ usbreset 유틸리티 빌드 및 설치 중...${NC}"
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

# 2. Node.js & PM2 설치
echo -e "${YELLOW}[*] [2/5] Node.js 및 PM2 프로세스 매니저 설치...${NC}"
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt install -y nodejs
fi

if ! command -v pm2 &> /dev/null; then
    sudo npm install -g pm2
fi
echo -e "${GREEN}      ↳ [✓] Node $(node -v) / PM2 $(pm2 -v) 설치 완료!${NC}"

# 3. Python 의존성 설치
echo -e "${YELLOW}[*] [3/5] Python 필수 라이브러리 설치 (requirements.txt)...${NC}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

pip3 install --break-system-packages -r requirements.txt || pip3 install -r requirements.txt

# 4. 필수 디렉터리 구조 생성
echo -e "${YELLOW}[*] [4/5] 로깅 및 스크린샷 아카이빙 디렉터리 생성...${NC}"
mkdir -p logs/allocate_history logs/release_history logs/target_screenshot logs/battery_history click_logs apks

# 5. PM2 시스템 서비스 등록 (재부팅 시 자동 가동)
echo -e "${YELLOW}[*] [5/5] PM2 Systemd 시작 서비스 등록...${NC}"
sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u $USER --hp $HOME || true

echo -e "\n${CYAN}==========================================================================${NC}"
echo -e "${GREEN} 🎉 모든 호스트 설치가 완료되었습니다!${NC}"
echo -e "${CYAN}==========================================================================${NC}"
echo -e "다음 단계:"
echo -e "  1. 단말기 USB 연결 후: ${YELLOW}./device_init.sh${NC}"
echo -e "  2. PM2로 무한 가동 시작: ${GREEN}pm2 start ecosystem.config.js && pm2 save${NC}"
echo -e "  3. 실시간 모니터링:     ${CYAN}pm2 logs nshop-macro-daemon${NC}"
echo -e "${CYAN}==========================================================================${NC}\n"
