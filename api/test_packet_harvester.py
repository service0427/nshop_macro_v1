import unittest
from datetime import datetime, timedelta
from app import create_app
from database import get_db_cursor
from core.harvester import harvest_single_packet
from services.nnb_service import NNBService

class PacketHarvesterTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_live_lcs_packet_harvest(self):
        """실제 네이버 lcs.naver.com/m 호출하여 13자리 정품 NNB 및 BUC 획득 검증"""
        packet = harvest_single_packet()
        self.assertIsNotNone(packet)
        self.assertEqual(len(packet["nnb"]), 13)
        self.assertTrue(len(packet["buc"]) > 0)
        self.assertLess(packet["dur_sec"], 2.0)
        print(f"\n[Live Packet Success] NNB: {packet['nnb']}, BUC: {packet['buc'][:15]}..., Speed: {packet['dur_sec']}s")

    def test_bank_and_aging(self):
        """단말기 웜업 토큰 저금 및 상태 검증"""
        res = self.client.post("/api/v1/nnb/bank", json={
            "nnb": "GENUINE12345A",
            "buc": "dummy_buc_value",
            "source": "APP_WARMUP",
            "device_id": "pixel_7_01",
            "memo": "단말기 웜업 채굴"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["action"], "BANKED")
        self.assertEqual(data["status"], "AGING")
        self.assertEqual(data["source"], "APP_WARMUP")

    def test_acquire_ready_nnb_after_1200s(self):
        """1200초 초과된 READY 토큰 인출 및 타격 확정 테스트"""
        now = datetime.now()

        # 100초 된 신생아 토큰
        with get_db_cursor(commit=True) as (cur, _):
            cur.execute("""
                INSERT INTO nnbs (nnb, buc, status, source, created_at)
                VALUES ('NEWBORN12345A', 'buc1', 'AGING', 'LCS_PACKET', %s)
            """, (now - timedelta(seconds=100)))

            # 1300초 된 숙성 토큰
            cur.execute("""
                INSERT INTO nnbs (nnb, buc, status, source, created_at)
                VALUES ('MATURED12345B', 'buc2', 'AGING', 'LCS_PACKET', %s)
            """, (now - timedelta(seconds=1300)))

        # 작업 호출 (acquire)
        res = self.client.post("/api/v1/nnb/acquire", json={
            "min_age_seconds": 1200,
            "target": "스토어_나이키_운동화",
            "device_id": "phone_02"
        })
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["nnb"], "MATURED12345B")
        self.assertEqual(body["data"]["use_count"], 1)
        self.assertEqual(body["data"]["used_target"], "스토어_나이키_운동화")

        # 타격 완료 확정 (mark-used)
        res_mark = self.client.post("/api/v1/nnb/mark-used", json={
            "nnb": "MATURED12345B",
            "target": "스토어_나이키_운동화_타격성공"
        })
        self.assertEqual(res_mark.status_code, 200)

        # 풀 상태 확인 (pool-status)
        res_status = self.client.get("/api/v1/nnb/pool-status?min_age_seconds=1200")
        self.assertEqual(res_status.status_code, 200)
        status_data = res_status.get_json()
        self.assertEqual(status_data["total"], 2)
        self.assertEqual(status_data["used_count"], 1)
        self.assertEqual(status_data["aging_count"], 1)
        self.assertEqual(status_data["ready_count"], 0)

    def test_topup_watermark(self):
        """수위 조절기 목표치 자동 채굴 보충 테스트"""
        res = self.client.post("/api/v1/nnb/topup", json={
            "target_size": 3
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["target_size"], 3)
        self.assertEqual(data["collected"], 3)
        self.assertEqual(data["current_active_pool"], 3)

if __name__ == "__main__":
    unittest.main()
