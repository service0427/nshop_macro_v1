#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/monitor/web_dashboard.py

20대 단말기 플릿 실시간 웹 관제 대시보드 (Fleet Live Web Dashboard)
-------------------------------------------------------------------
웹 브라우저를 통해 20대 디바이스의 키워드, 진행 단계, 쿨타임,
"가만히 있는 이유"를 그래픽 카드로 실시간 모니터링.

실행법:
  python3 src/monitor/web_dashboard.py --port 8080
"""

import os
import sys
import json
import time
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.monitor.fleet_state import FleetStateManager
from src.device.device_selector import get_online_devices

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>🚀 N-Shop Fleet Realtime Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: #0f172a; color: #f8fafc; padding: 20px; }
    .header { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #334155; }
    .header h1 { font-size: 22px; color: #38bdf8; display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
    .header-stats { display: flex; gap: 20px; flex-wrap: wrap; }
    .stat-badge { background: #0f172a; padding: 8px 14px; border-radius: 8px; border: 1px solid #334155; font-size: 14px; }
    .stat-badge span.val { font-weight: bold; color: #4ade80; margin-left: 6px; }
    .cooldown-alert { background: #451a03; border: 1px solid #b45309; color: #fde68a; padding: 12px 16px; border-radius: 8px; margin-top: 14px; display: none; }
    .cooldown-alert.active { display: block; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
    .card { background: #1e293b; border-radius: 10px; padding: 16px; border: 1px solid #334155; transition: transform 0.15s, border-color 0.15s; }
    .card:hover { border-color: #38bdf8; transform: translateY(-2px); }
    .card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .device-id { font-weight: bold; color: #94a3b8; font-size: 14px; }
    .badge { font-size: 12px; padding: 3px 8px; border-radius: 12px; font-weight: bold; }
    .badge-success { background: #064e3b; color: #6ee7b7; border: 1px solid #059669; }
    .badge-dwell { background: #164e63; color: #67e8f9; border: 1px solid #0891b2; }
    .badge-searching { background: #1e3a8a; color: #93c5fd; border: 1px solid #2563eb; }
    .badge-launching { background: #713f12; color: #fde047; border: 1px solid #ca8a04; }
    .badge-cooldown { background: #334155; color: #94a3b8; border: 1px solid #475569; }
    .badge-error { background: #7f1d1d; color: #fca5a5; border: 1px solid #dc2626; }
    .card-body { font-size: 13px; line-height: 1.6; }
    .kw { font-size: 15px; font-weight: bold; color: #ffffff; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .store { color: #facc15; font-weight: 500; }
    .progress-txt { color: #38bdf8; font-size: 12px; margin-top: 8px; display: flex; justify-content: space-between; }
    .progress-bar-bg { width: 100%; height: 6px; background: #334155; border-radius: 3px; margin-top: 6px; overflow: hidden; }
    .progress-bar-fill { height: 100%; background: #38bdf8; width: 0%; transition: width 0.3s; }
  </style>
</head>
<body>
  <div class="header">
    <h1>🚀 N-Shop Macro V1 • 20대 단말기 실시간 플릿 관제 센터</h1>
    <div class="header-stats">
      <div class="stat-badge">회차: <span class="val" id="stat-cycle">Cycle #00</span></div>
      <div class="stat-badge">공인 IP: <span class="val" id="stat-ip">-</span></div>
      <div class="stat-badge">온라인 기기: <span class="val" id="stat-devices">0대</span></div>
      <div class="stat-badge">전체 상태: <span class="val" id="stat-status">IDLE</span></div>
    </div>
    <div class="cooldown-alert" id="cooldown-alert">
      ⏳ <strong>쿨타임 안전 대기 중 (<span id="cd-timer">00:00</span> 남음)</strong>: <span id="cd-reason">-</span>
      <div style="font-size: 12px; color: #cbd5e1; margin-top: 4px;">💡 [안내] 비정상 멈춤이 아니며, 스토어 쿨타임 및 LTE 통신 완충을 위해 설계된 정상 대기 상태입니다.</div>
    </div>
  </div>

  <div class="grid" id="device-grid">
    <!-- 단말기 카드 동적 렌더링 -->
  </div>

  <script>
    function getBadgeClass(state) {
      if (state === 'SUCCESS') return 'badge-success';
      if (state === 'DWELL' || state === 'LANDING_DWELL') return 'badge-dwell';
      if (state === 'SEARCHING' || state === 'SERP_FOUND' || state === 'SHOP_NAV') return 'badge-searching';
      if (state === 'LAUNCHING' || state === 'STAGGER_WAIT') return 'badge-launching';
      if (state === 'NO_TASK_COOLDOWN' || state === 'IDLE') return 'badge-cooldown';
      return 'badge-error';
    }

    async function updateDashboard() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        const g = data.global || {};
        const devs = data.devices || {};

        document.getElementById('stat-cycle').textContent = 'Cycle #' + (g.cycle || 0).toString().padStart(2, '0');
        document.getElementById('stat-ip').textContent = g.ip || '-';
        document.getElementById('stat-status').textContent = (g.status || 'IDLE') + ' (' + (g.status_detail || '') + ')';

        const cdSec = g.cooldown_remaining_sec || 0;
        const cdAlert = document.getElementById('cooldown-alert');
        if (cdSec > 0) {
          cdAlert.classList.add('active');
          const m = Math.floor(cdSec / 60).toString().padStart(2, '0');
          const s = (cdSec % 60).toString().padStart(2, '0');
          document.getElementById('cd-timer').textContent = `${m}:${s}`;
          document.getElementById('cd-reason').textContent = g.cooldown_reason || '스토어 쿨다운 및 네트워크 완충';
        } else {
          cdAlert.classList.remove('active');
        }

        const devKeys = Object.keys(devs).sort();
        document.getElementById('stat-devices').textContent = devKeys.length + '대';

        const grid = document.getElementById('device-grid');
        grid.innerHTML = '';

        devKeys.forEach((dId, idx) => {
          const dev = devs[dId];
          const card = document.createElement('div');
          card.className = 'card';
          const bClass = getBadgeClass(dev.state);

          card.innerHTML = `
            <div class="card-head">
              <span class="device-id">#${idx+1} ${dId}</span>
              <span class="badge ${bClass}">${dev.state || 'IDLE'}</span>
            </div>
            <div class="card-body">
              <div class="kw" title="${dev.keyword || '-'}">🔍 ${dev.keyword || '-'}</div>
              <div>몰: <span class="store">${dev.store_name || '-'}</span> | 순위: ${dev.rank || '-'}</div>
              <div class="progress-txt">
                <span>${dev.progress || dev.status_msg || '-'}</span>
                <span>${dev.elapsed_sec ? dev.elapsed_sec + 's' : ''}</span>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${dev.state === 'SUCCESS' ? 100 : (dev.state === 'DWELL' ? 75 : (dev.state === 'SEARCHING' ? 40 : 15))}%"></div>
              </div>
            </div>
          `;
          grid.appendChild(card);
        });
      } catch (e) {
        console.error("Dashboard fetch error:", e);
      }
    }

    setInterval(updateDashboard, 1000);
    updateDashboard();
  </script>
</body>
</html>
"""


class DashboardRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            snap = FleetStateManager.get_snapshot()
            try:
                online_devs = get_online_devices()
                devs = snap.setdefault("devices", {})
                for d in online_devs:
                    if d not in devs:
                        devs[d] = {
                            "device_id": d,
                            "state": "IDLE",
                            "keyword": "-",
                            "store_name": "-",
                            "target_mid": "-",
                            "rank": "-",
                            "progress": "유휴 대기",
                            "elapsed_sec": 0.0,
                            "last_result": "-"
                        }
            except Exception:
                pass

            body = json.dumps(snap, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML_TEMPLATE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        # HTTP 액세스 로그 침묵 (터미널 오염 방지)
        pass


def run_web_dashboard(port: int = 8080):
    server_address = ("", port)
    httpd = HTTPServer(server_address, DashboardRequestHandler)
    print(f"🌐 [웹 대시보드 기동 완료] http://localhost:{port} 에서 실시간 관제 가능")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n웹 대시보드를 종료합니다.")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fleet Live Web Dashboard")
    parser.add_argument("--port", type=int, default=8080, help="웹 서버 포트 (기본: 8080)")
    args = parser.parse_args()
    run_web_dashboard(args.port)
