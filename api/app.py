import os
from flask import Flask, jsonify
from config import API_PORT
from routes.nnb import nnb_bp
from routes.task import task_bp
from routes.keyword import keyword_bp
from routes.network import network_bp
from routes.task_v2 import task_v2_bp, node_v2_bp, admin_v2_bp, product_v2_bp, quota_v2_bp, sim_v2_bp, device_v2_bp, group_v2_bp

def create_app():
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False

    # 라우트 등록
    app.register_blueprint(nnb_bp)
    app.register_blueprint(task_bp)
    app.register_blueprint(keyword_bp)
    app.register_blueprint(network_bp)
    app.register_blueprint(task_v2_bp)
    app.register_blueprint(node_v2_bp)
    app.register_blueprint(admin_v2_bp)
    app.register_blueprint(product_v2_bp)
    app.register_blueprint(quota_v2_bp)
    app.register_blueprint(sim_v2_bp)
    app.register_blueprint(device_v2_bp)
    app.register_blueprint(group_v2_bp)

    @app.route("/", methods=["GET"])
    def index():
        return jsonify({
            "service": "N-Shop Central API Server (v1 & v2 Unified)",
            "status": "ONLINE",
            "version": "2.0.0",
            "endpoints_v2": {
                "task_allocate": "POST /api/v2/task/allocate (5단계 지능형 쿨다운/쿼터 작업 할당)",
                "task_report": "POST /api/v2/task/report (원격 정밀 진단 & 체크포인트 보고)",
                "task_diagnostics": "GET /api/v2/task/diagnostics (원격 관제 요약)",
                "products_unique": "GET /api/v2/products/unique (유니크 상품 목록 및 슬롯/쿼터 현황)",
                "sync_external": "POST /api/v2/products/sync-external (5분 주기 10개 외부 사이트 슬롯 동기화)",
                "quotas_daily": "GET /api/v2/quotas/daily?date=YYYY-MM-DD (일자별 슬롯 쿼터 및 달성 현황)",
                "simulation_day": "POST /api/v2/simulation/run-day (일자별 다일 시뮬레이션 가동 엔진)",
                "node_heartbeat": "POST /api/v2/node/heartbeat (분산 노드 상태 동기화)"
            },
            "endpoints": {
                "health": "GET /health",
                "task_assign": "GET/POST /api/v1/task/assign (20분 초과 NNB/BUC + nshop_list 상품 매칭 작업 할당)",
                "task_report": "POST /api/v1/task/report (작업 결과 보고: search_type, serp_rank, shopping_rank 등)",
                "keyword_random": "GET /api/v1/keyword/random (keyword, nv_mid, compare_id 랜덤 조회)",
                "nnb_random": "GET /api/v1/nnb/random (1200초 초과 NNB/BUC 랜덤 조회)",
                "harvest": "POST /api/v1/nnb/harvest (lcs.naver.com 패킷 0.05초 초고속 채굴)",
                "bank": "POST /api/v1/nnb/bank (앱 웜업/단말기 신생아 토큰 저금)",
                "topup": "POST /api/v1/nnb/topup (수위 조절기 목표치 자동 보충)",
                "acquire": "POST /api/v1/nnb/acquire (1200초 숙성 완료 READY 토큰 인출)",
                "mark_used": "POST /api/v1/nnb/mark-used (타격 완료 USED 확정 갱신)",
                "pool_status": "GET /api/v1/nnb/pool-status (풀 수위 및 AGING/READY/USED 상태 추적)"
            }
        })

    @app.route("/health", methods=["GET"])
    def health_check():
        from database import get_db_cursor
        db_ok = False
        try:
            with get_db_cursor(commit=False) as (cur, _):
                cur.execute("SELECT 1 AS ok")
                res = cur.fetchone()
                db_ok = (res["ok"] == 1)
        except Exception:
            db_ok = False

        return jsonify({
            "status": "OK" if db_ok else "ERROR",
            "database": "CONNECTED" if db_ok else "DISCONNECTED"
        }), (200 if db_ok else 500)

    return app

if __name__ == "__main__":
    app = create_app()
    print(f"🚀 N-Shop API Server running on port {API_PORT}...")
    app.run(host="0.0.0.0", port=API_PORT, debug=False)
