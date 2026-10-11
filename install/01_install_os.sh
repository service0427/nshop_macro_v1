#!/usr/bin/env bash

# ========================================================================================
# [01 단계] N-Shop Macro 365일 무한가동 Linux Server OS Initial Setup (01_install_os.sh)
# ========================================================================================
# 1. Sudo 비밀번호 생략 (NOPASSWD) 설정
# 2. 관리자 SSH 공개키 (집/가게) 자동 등록 및 SSHD PubkeyAuthentication 활성화
# 3. 한국 표준시 (Asia/Seoul) 타임존 및 NTP 시간 동기화
# 4. 24/7 무중단 서버 절전/슬립 방지 (Sleep/Suspend/Hibernate Mask)
# 5. USB 자동 절전(Autosuspend) 영구 비활성화 (단말기 ADB 끊김 방지)
# 6. 시스템 파일 디스크립터(ulimit) 및 커널 네트워크/메모리(sysctl) 최적화
# 7. 필수 시스템 패키지 일괄 설치 (adb, python3, usbreset, net-tools, jq 등)
# ========================================================================================

set -e

CYAN="\e[1;36m"
GREEN="\e[1;32m"
YELLOW="\e[1;33m"
NC="\e[0m"

echo -e "${CYAN}==========================================================================${NC}"
echo -e "${CYAN} 🖥️  [01단계] N-Shop Macro 365일 무한가동 Linux OS 서버 셋업 시작${NC}"
echo -e "${CYAN}==========================================================================${NC}"

# 1. Sudo 비밀번호 생략 설정
echo -e "\n${YELLOW}[*] [1/8] 현재 사용자($USER) Sudo 비밀번호 생략(NOPASSWD) 구성 중...${NC}"
if ! sudo grep -q "^$USER ALL=(ALL) NOPASSWD:ALL" "/etc/sudoers.d/$USER" 2>/dev/null; then
    echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee "/etc/sudoers.d/$USER" >/dev/null
    sudo chmod 0440 "/etc/sudoers.d/$USER"
    echo -e "${GREEN}      ↳ [✓] $USER NOPASSWD 적용 완료!${NC}"
else
    echo -e "${GREEN}      ↳ [✓] 이미 NOPASSWD 구성됨 (건너뜀)${NC}"
fi

# 2. SSH 공개키 등록 (집 / 가게)
echo -e "\n${YELLOW}[*] [2/8] SSH 관리자 공개키 등록 중...${NC}"
mkdir -p ~/.ssh
chmod 700 ~/.ssh

HOME_KEY="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC07UNfs5EPAYS1TSHdoZofg93FFiHzIxmnixPJMFDgaDF6eKfCBrco2t+fxyyKO2IoxrSj79ii+MYaxYV+oPqMoAS5RrUHrVEgeYNxkkvW6LkxdJzUiHZZOesfcV2djnRphPPIEQND0m7b8RacDiH3Cxv6UMZRtWQVi3vxtqF02RikluTux5H6nnzn197wQE7yBs4J55Wuut6lftrE3meHU2i/pnhFOjr0qOuC2GzP3N/aRH3BEeZ78lQbgwFlzvfLsEdF8ebYXVKiT7TAExjWfcicSu+lDBsn50tAY8HsJVD30zKXImSJl5W/A3Nv63/rexaRfI2O5LQpdjx8STsGmtwtuYiHmfH6swy2wEyN5UEvTxF/fuI7EYIoC0ej44paH8mSv73svQUButhcMkI5ZgXgIerWz0gCGXMA1pwjW0oZKPgN9GnhqDKBXYQYjRr3NApjxwTCcJ4jlRH5TrV9+ass96ChSKpCeKg0R1BAKX2HYal08egOoiEBbUkX+yQ+C/BP02iZcGPqX886cmuR2lF97JFpeEdMxEdb6ClBTrdbRlB9PWq5R7erUXS/1YMNTJZHAeoVa5Jr2JW1cZYS424S3i48vjBZyHMF3VCFHQA7B9n1ztOalzyRpRfB8QrpfaItwNnTho28kDW4zaZ/Ugv1zV8/4P+JcvVo9A3EZw== techb@TechB"
STORE_KEY="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDrHO2J7IvtUvxry/1jZP/eQfC1CTW2fPUd/x/1xq5A0mNqh7jqM6l1B5jySTCekc4PCHMLqcZFFrsQHVhrKaG2S7ZYtlvDFcxSyWxUcxJUoo5WjhQ7L6OJYy9KvrThbgGhfBx9NVmo0lE/GAYw/RL3JpBfb5mdZr8fFlmm6C9nC2yiQtY+NpnmkeoQnCOL/yFi6uFQpTktpaE0J6tR2JPl0yT524q5J3KV5R4/sPFE1kOmq80C/Gafn6tKaxQ2f7VLX/IYhsxXpq2ymT1UYcH+IDsepYEsNYobEklyod1if2ZuEc0Qr6g76GoR7/3e03p/1vaJJ4Tmge+gIVWmymxzmOJpwQEvDxDBkiWstM2oNqSYYcOc1FC97eA+FqrqJrfYM/LlF70kOQ9KaxJVeZ5dNO99pegYk6DA15tHuWe4RnGtS+A5Sd0Y4V9jIwVDp9PS0oWxjHld7dRMVVqiEUUWcc6fv517OjYkLNg4tXoamYAgDZHDQ4Knjn0Ysusl45lD5Uki+kFbe2yZR8Txr/gwoz7UVarLVxpqmIDyUf0/9D5nWUbLpkYKpVpw8RgTc2G7HALfkzQ28SOX3eMxRTxpVUFQTI/4Y2ys5DEDszHJ0knffLRAPHUUq4f7gcJ8PRWfW8Zs/Yf1ZLpEYV1dcVbyR0mYSOKxC/w9X/6tttR3GQ== moon@DESKTOP-OTKATMO"

touch ~/.ssh/authorized_keys
if ! grep -q "$HOME_KEY" ~/.ssh/authorized_keys 2>/dev/null; then
    echo "$HOME_KEY" >> ~/.ssh/authorized_keys
fi
if ! grep -q "$STORE_KEY" ~/.ssh/authorized_keys 2>/dev/null; then
    echo "$STORE_KEY" >> ~/.ssh/authorized_keys
fi
chmod 600 ~/.ssh/authorized_keys

sudo sed -i 's/^#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config 2>/dev/null || true
sudo systemctl enable --now ssh 2>/dev/null || true
echo -e "${GREEN}      ↳ [✓] SSH 공개키 등록 및 데몬 활성화 완료!${NC}"

# 3. 타임존 설정 & 시간 동기화 (Asia/Seoul)
echo -e "\n${YELLOW}[*] [3/8] 타임존(Asia/Seoul) 및 NTP 시간 동기화 설정 중...${NC}"
sudo timedatectl set-timezone Asia/Seoul
sudo timedatectl set-ntp true 2>/dev/null || true
echo -e "${GREEN}      ↳ [✓] 현재 서버 시각: $(date)${NC}"

# 4. 24/7 무중단 서버 슬립/절전 완전 차단
echo -e "\n${YELLOW}[*] [4/8] 365일 무중단 가동을 위한 시스템 절전(Sleep/Suspend) 비활성화 중...${NC}"
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || true
echo -e "${GREEN}      ↳ [✓] 슬립/서스펜드 마스킹 완료!${NC}"

# 5. USB 자동 절전(Autosuspend) 영구 비활성화 (단말기 연결 끊김 방지)
echo -e "\n${YELLOW}[*] [5/8] USB 자동 절전(Autosuspend) 비활성화 구성 중...${NC}"
sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 usbcore.autosuspend=-1"/' /etc/default/grub 2>/dev/null || true
sudo update-grub 2>/dev/null || true

cat << 'EOF' | sudo tee /etc/udev/rules.d/50-usb_power.rules >/dev/null
ACTION=="add", SUBSYSTEM=="usb", ATTR{power/control}="on"
EOF
sudo udevadm control --reload 2>/dev/null || true
echo -e "${GREEN}      ↳ [✓] USB 상시 전원 공급(Autosuspend Disable) 규칙 적용 완료!${NC}"

# 6. 커널 파라미터 및 파일 디스크립터(ulimit) 최적화
echo -e "\n${YELLOW}[*] [6/8] 커널 네트워크/메모리(sysctl) 및 ulimit 최적화 중...${NC}"
cat << 'EOF' | sudo tee /etc/sysctl.d/99-nshop-server.conf >/dev/null
# 365일 무한가동 서버 커널 최적화
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
vm.swappiness = 10
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_forward = 1
EOF
sudo sysctl --system >/dev/null 2>&1 || true

cat << 'EOF' | sudo tee /etc/security/limits.d/99-nshop-limits.conf >/dev/null
* soft nofile 65536
* hard nofile 65536
* soft nproc 65536
* hard nproc 65536
EOF
echo -e "${GREEN}      ↳ [✓] 커널 및 ulimit 튜닝 완료!${NC}"

# 7. 필수 시스템 패키지 설치
echo -e "\n${YELLOW}[*] [7/8] 필수 시스템 패키지 일괄 설치 중...${NC}"
sudo apt update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    android-tools-adb usbutils python3 python3-pip python3-dev python3-venv \
    curl wget git build-essential cron net-tools nano jq openssl unzip zip lsof \
    iptables-persistent

# 8. usbreset 유틸리티 컴파일 및 배치
echo -e "\n${YELLOW}[*] [8/8] USB 하드웨어 리셋 유틸리티(usbreset) 확인 및 빌드...${NC}"
if ! command -v usbreset &> /dev/null; then
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
fi
echo -e "${GREEN}      ↳ [✓] usbreset 준비 완료!${NC}"

echo -e "\n${CYAN}==========================================================================${NC}"
echo -e "${GREEN} 🎉 [01단계] 365일 무한가동 Server OS 셋업이 완벽히 완료되었습니다!${NC}"
echo -e "${CYAN}==========================================================================${NC}"
echo -e "\n${YELLOW}다음 단계 순서대로 진행:${NC}"
echo -e "  2. 호스트 및 PM2 자동화 셋업: ${GREEN}./02_pm2_setup.sh${NC}"
echo -e "  3. 단말기 USB 연결 후 초기화: ${GREEN}./03_device_init.sh${NC}"
echo -e "${CYAN}==========================================================================${NC}\n"
