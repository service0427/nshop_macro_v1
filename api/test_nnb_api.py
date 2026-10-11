import json
import unittest
from datetime import datetime, timedelta
from app import create_app
from database import get_db_cursor
from utils.generator import generate_nnb, validate_nnb

class NNBTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_nnb_generator_and_validation(self):
        """13자리 영문 대문자+숫자 형식 검증"""
        nnb = generate_nnb()
        self.assertEqual(len(nnb), 13)
        self.assertTrue(validate_nnb(nnb))
        self.assertFalse(validate_nnb("abc123"))
        self.assertFalse(validate_nnb("ABC1234567890EXTRA"))

    def test_register_and_use_count(self):
        """신규 등록 및 기존 등록 시 use_count 업데이트 검증"""
        sample_nnb = "TEST12345678A"

        # 1. 최초 등록 (신생아 토큰 -> use_count: 0)
        res = self.client.post("/api/v1/nnb/register", json={"nnb": sample_nnb, "memo": "테스트1"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["nnb"], sample_nnb)
        self.assertEqual(data["use_count"], 0)
        self.assertEqual(data["action"], "BANKED")

        # 2. 동일한 NNB 재호출 시 use_count 1 증가
        res2 = self.client.post("/api/v1/nnb/register", json={"nnb": sample_nnb, "memo": "테스트2"})
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()["data"]
        self.assertEqual(data2["use_count"], 1)
        self.assertEqual(data2["action"], "UPDATED")

    def test_acquire_1200_seconds_rule(self):
        """작업 호출 시 created_at 기준 1200초 초과된 것만 할당되는지 검증"""
        now = datetime.now()

        # A: 방금 생성된 NNB (경과 시간 0초)
        fresh_nnb = "FRESH1234567A"
        # B: 600초 경과한 NNB (경과 시간 600초 - 미달)
        half_nnb = "HALF12345678B"
        # C: 1300초 경과한 NNB (경과 시간 1300초 - 조건 만족!)
        matured_nnb = "MATURE123456C"

        with get_db_cursor(commit=True) as (cur, _):
            cur.execute("""
                INSERT INTO nnbs (nnb, use_count, status, created_at)
                VALUES (%s, 0, 'ACTIVE', %s)
            """, (fresh_nnb, now))

            cur.execute("""
                INSERT INTO nnbs (nnb, use_count, status, created_at)
                VALUES (%s, 0, 'ACTIVE', %s)
            """, (half_nnb, now - timedelta(seconds=600)))

            cur.execute("""
                INSERT INTO nnbs (nnb, use_count, status, created_at)
                VALUES (%s, 0, 'ACTIVE', %s)
            """, (matured_nnb, now - timedelta(seconds=1300)))

        # 1200초 초과 조건으로 작업 호출 (acquire)
        res = self.client.post("/api/v1/nnb/acquire", json={"min_age_seconds": 1200, "memo": "작업1"})
        self.assertEqual(res.status_code, 200)
        res_data = res.get_json()
        self.assertTrue(res_data["success"])
        self.assertEqual(res_data["data"]["nnb"], matured_nnb)
        self.assertEqual(res_data["data"]["use_count"], 1)

        # 이제 matured_nnb를 한번 더 호출하면 use_count가 2가 되는지 확인
        res_again = self.client.post("/api/v1/nnb/acquire", json={"min_age_seconds": 1200, "memo": "작업2"})
        self.assertEqual(res_again.status_code, 200)
        res_again_data = res_again.get_json()
        self.assertEqual(res_again_data["data"]["nnb"], matured_nnb)
        self.assertEqual(res_again_data["data"]["use_count"], 2)

    def test_acquire_fails_when_no_matured_nnb(self):
        """1200초 초과된 NNB가 없으면 할당 실패 응답 (404)"""
        now = datetime.now()
        fresh_nnb = "FRESH12345678"
        with get_db_cursor(commit=True) as (cur, _):
            cur.execute("""
                INSERT INTO nnbs (nnb, use_count, status, created_at)
                VALUES (%s, 0, 'ACTIVE', %s)
            """, (fresh_nnb, now - timedelta(seconds=300)))

        res = self.client.post("/api/v1/nnb/acquire", json={"min_age_seconds": 1200})
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["success"])

if __name__ == "__main__":
    unittest.main()
