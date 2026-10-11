import os
from flask import Flask, jsonify
from config import API_PORT
from routes.nnb import nnb_bp
from routes.task import task_bp
from routes.keyword import keyword_bp

def create_app():
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False

    # 라우트 등록
    app.register_blueprint(nnb_bp)
    app.register_blueprint(task_bp)
    app.register_blueprint(keyword_bp)

    @app.route("/", methods=["GET"])
    def index():
        return jsonify({
            "service": "N-Shop Central API Server v1",
            "status": "ONLINE",
            "version": "1.3.0",
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
