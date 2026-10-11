import time
from database import get_db_cursor
from core.fast_harvester import harvest_and_insert_batch
from config import TARGET_ZERO_USE_POOL

def test_fill_to_2000():
    print(f"🚀 [테스트] use_count=0 토큰 2,000개 확보 테스트 시작...")

    with get_db_cursor(commit=False) as (cur, _):
        cur.execute("SELECT COUNT(*) AS cnt FROM nnbs WHERE use_count = 0 AND status IN ('AGING', 'READY', 'ACTIVE')")
        current = cur.fetchone()["cnt"]

    needed = TARGET_ZERO_USE_POOL - current
    print(f"현재 토큰 수: {current:,}개, 채굴 필요 수: {needed:,}개")

    t_start = time.time()
    batch_size = 60

    while needed > 0:
        fetch_cnt = min(needed, batch_size)
        t0 = time.time()
        inserted = harvest_and_insert_batch(count=fetch_cnt, max_workers=15)
        dur = round(time.time() - t0, 2)

        with get_db_cursor(commit=False) as (cur, _):
            cur.execute("SELECT COUNT(*) AS cnt FROM nnbs WHERE use_count = 0 AND status IN ('AGING', 'READY', 'ACTIVE')")
            current = cur.fetchone()["cnt"]

        needed = TARGET_ZERO_USE_POOL - current
        speed = round(inserted / max(dur, 0.01), 1)
        print(f"  + {inserted}개 적재 ({dur}초, {speed}/s) -> 현재 확보: {current:,} / {TARGET_ZERO_USE_POOL:,}개 (남은 개수: {max(0, needed):,}개)")
        time.sleep(0.05)

    total_dur = round(time.time() - t_start, 2)
    print(f"\n🎉 2,000개 확보 완료! (소요 시간: {total_dur}초)")

    # NNB 와 BUC 검증
    with get_db_cursor(commit=False) as (cur, _):
        cur.execute("""
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN use_count = 0 THEN 1 ELSE 0 END) AS zero_use_count,
                SUM(CASE WHEN buc IS NOT NULL AND CHAR_LENGTH(buc) > 10 THEN 1 ELSE 0 END) AS valid_buc_count,
                SUM(CASE WHEN CHAR_LENGTH(nnb) = 13 THEN 1 ELSE 0 END) AS valid_nnb_count
            FROM nnbs;
        """)
        summary = cur.fetchone()

        print("\n📊 [DB 무결성 검증 결과]")
        print(f"- 전체 토큰 수      : {summary['total_count']:,}개")
        print(f"- 사용량 0 (신규)   : {summary['zero_use_count']:,}개")
        print(f"- 정품 13자리 NNB   : {summary['valid_nnb_count']:,}개")
        print(f"- 정상 BUC 보유 수  : {summary['valid_buc_count']:,}개")

        assert summary['zero_use_count'] >= 2000, "2000개 미만입니다!"
        assert summary['valid_nnb_count'] >= 2000, "정상 NNB가 2000개 미만입니다!"
        assert summary['valid_buc_count'] >= 2000, "정상 BUC가 2000개 미만입니다!"

        # 샘플 3개 출력
        cur.execute("SELECT nnb, buc, dur_sec, created_at FROM nnbs WHERE use_count = 0 ORDER BY id DESC LIMIT 3")
        samples = cur.fetchall()
        print("\n🔎 [최신 발급 NNB + BUC 샘플]")
        for s in samples:
            print(f"  * NNB: {s['nnb']} | BUC: {s['buc'][:20]}... | 속도: {s['dur_sec']}s | 생성: {s['created_at']}")

if __name__ == "__main__":
    test_fill_to_2000()
