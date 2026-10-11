#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api/deploy.py

Central API Server Remote Development & Deployment Tool:
Manages remote server tech@114.207.112.173:
- Remote status check (PM2 & MariaDB)
- PM2 reload & log monitoring
- MariaDB SQL query execution
- Code push (with remote python syntax validation & auto-reload)
- Code pull (fetch latest from remote)
"""

import os
import sys
import argparse
import paramiko
from pathlib import Path

REMOTE_HOST = "114.207.112.173"
REMOTE_PORT = 22
REMOTE_USER = "tech"
REMOTE_PASS = "Tech1324!"
REMOTE_ROOT = "/home/tech/nshop_api_v1"
LOCAL_API_DIR = Path(__file__).resolve().parent

def get_ssh_client() -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(REMOTE_HOST, port=REMOTE_PORT, username=REMOTE_USER, password=REMOTE_PASS, timeout=10)
    return ssh

def cmd_status(args):
    print("=" * 60)
    print(f"📡 [원격 API 서버 상태] {REMOTE_USER}@{REMOTE_HOST}")
    print("=" * 60)
    ssh = get_ssh_client()
    try:
        stdin, stdout, stderr = ssh.exec_command("pm2 jlist")
        import json
        apps = json.loads(stdout.read().decode())
        print("\n🔹 [PM2 프로세스 현황]:")
        for app in apps:
            name = app.get("name")
            status = app.get("pm2_env", {}).get("status")
            pid = app.get("pid")
            restarts = app.get("pm2_env", {}).get("restart_time", 0)
            mem = round(app.get("monit", {}).get("memory", 0) / 1024 / 1024, 1)
            icon = "🟢" if status == "online" else "🔴"
            print(f"   {icon} {name:<20} | 상태: {status:<8} | PID: {pid:<7} | 메모리: {mem}MB | 재시작: {restarts}회")

        stdin, stdout, stderr = ssh.exec_command(
            'mysql -unshop -pTech1324 nshop_api_v1 -e "'
            'SELECT status, count(*) AS cnt FROM tasks GROUP BY status; '
            'SELECT count(*) AS total_nnbs, sum(case when use_count=0 then 1 else 0 end) AS zero_use FROM nnbs;"'
        )
        out = stdout.read().decode()
        print("\n🔹 [MariaDB 데이터베이스 현황]:")
        print(out.strip())
    finally:
        ssh.close()

def cmd_reload(args):
    service = getattr(args, "service", None) or "nshop-api"
    print(f"🔄 [원격 PM2 리로드 요청] {service}...")
    ssh = get_ssh_client()
    try:
        stdin, stdout, stderr = ssh.exec_command(f"pm2 reload {service}")
        print(stdout.read().decode())
        err = stderr.read().decode()
        if err:
            print("STDERR:", err)
    finally:
        ssh.close()

def cmd_logs(args):
    service = getattr(args, "service", None) or "nshop-api"
    lines = getattr(args, "lines", 50) or 50
    print(f"📜 [원격 로그 조회] {service} (최근 {lines}줄)...")
    ssh = get_ssh_client()
    try:
        stdin, stdout, stderr = ssh.exec_command(f"pm2 logs {service} --lines {lines} --nostream")
        print(stdout.read().decode())
    finally:
        ssh.close()

def cmd_db(args):
    query = args.query
    if not query:
        print("❌ SQL 쿼리를 입력하세요.")
        return
    ssh = get_ssh_client()
    try:
        escaped_query = query.replace('"', '\\"')
        cmd = f'mysql -unshop -pTech1324 nshop_api_v1 -e "{escaped_query}"'
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        if out:
            print(out)
        if err:
            print("STDERR:", err)
    finally:
        ssh.close()

def cmd_push(args):
    rel_path = args.file.lstrip("/")
    l_path = LOCAL_API_DIR / rel_path
    r_path = f"{REMOTE_ROOT}/{rel_path}"

    if not l_path.exists():
        print(f"❌ 로컬 파일이 존재하지 않습니다: {l_path}")
        return

    print(f"⬆️ [원격 소스 배포] {l_path} ➔ {r_path}...")
    ssh = get_ssh_client()
    sftp = ssh.open_sftp()
    try:
        sftp.put(str(l_path), r_path)
        print("   ↳ SFTP 전송 완료")

        if r_path.endswith(".py"):
            stdin, stdout, stderr = ssh.exec_command(f"python3 -m py_compile {r_path}")
            err = stderr.read().decode()
            if err:
                print(f"❌ 원격 문법 검사 실패:\n{err}")
                return
            print("   ↳ [✓] 원격 Python 문법 검사 통과")

        if not getattr(args, "no_reload", False):
            stdin, stdout, stderr = ssh.exec_command("pm2 reload nshop-api")
            print("   ↳ [✓] PM2 nshop-api 리로드 완료")
            print(stdout.read().decode().strip())
        print("🎉 배포 및 적용 완료!")
    finally:
        sftp.close()
        ssh.close()

def cmd_pull(args):
    rel_path = args.file.lstrip("/")
    r_path = f"{REMOTE_ROOT}/{rel_path}"
    l_path = LOCAL_API_DIR / rel_path

    print(f"⬇️ [원격 소스 가져오기] {r_path} ➔ {l_path}...")
    ssh = get_ssh_client()
    sftp = ssh.open_sftp()
    try:
        l_path.parent.mkdir(parents=True, exist_ok=True)
        sftp.get(r_path, str(l_path))
        print("✅ 가져오기 완료!")
    except Exception as e:
        print(f"❌ 가져오기 실패: {e}")
    finally:
        sftp.close()
        ssh.close()

def main():
    parser = argparse.ArgumentParser(description="Central API Server Manager & Deployer")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="원격 PM2 및 DB 상태 조회")

    reload_p = subparsers.add_parser("reload", help="원격 PM2 프로세스 리로드")
    reload_p.add_argument("--service", type=str, default="nshop-api", help="서비스명 (기본: nshop-api)")

    logs_p = subparsers.add_parser("logs", help="원격 PM2 로그 조회")
    logs_p.add_argument("--service", type=str, default="nshop-api", help="서비스명 (기본: nshop-api)")
    logs_p.add_argument("-n", "--lines", type=int, default=50, help="줄 수 (기본: 50)")

    db_p = subparsers.add_parser("db", help="원격 MariaDB 쿼리 실행")
    db_p.add_argument("query", type=str, help="실행할 SQL 쿼리문")

    push_p = subparsers.add_parser("push", help="로컬 api/ 파일 원격 서버로 배포 및 리로드")
    push_p.add_argument("file", type=str, help="배포할 파일 상대경로 (예: services/task_service.py)")
    push_p.add_argument("--no-reload", action="store_true", help="PM2 리로드 생략")

    pull_p = subparsers.add_parser("pull", help="원격 서버 파일 로컬 api/로 내려받기")
    pull_p.add_argument("file", type=str, help="가져올 파일 상대경로 (예: services/task_service.py)")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(args)
    elif args.command == "reload":
        cmd_reload(args)
    elif args.command == "logs":
        cmd_logs(args)
    elif args.command == "db":
        cmd_db(args)
    elif args.command == "push":
        cmd_push(args)
    elif args.command == "pull":
        cmd_pull(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
