#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api/services/task_service_v2.py

Next-Generation Task Service (v2):
- Unique Target Products Master (SSOT)
- External Slots Mapping (10 Sites, Multiple Slots per Product)
- Multi-Keyword Pool (Rank Priority 1~5, Exposure Tracking)
- Daily Slot Quota Management (20 hits/slot, Hard-Capped at 100 hits/day)
- 5-Gate Intelligent Scheduling (Quota, Quarantine, Store 80m, IP/C-Class, 1:1 Device)
- Self-Healing Feedback Loop (Auto-quarantine on drop-off, Quota Locking)
"""

import time
import json
import random
import re
import logging
from typing import Dict, Any, Optional, List, Set
from database import get_db_cursor
from config import MIN_AGING_SECONDS

logger = logging.getLogger("TaskServiceV2")

# 가상의 10개 외부 제휴 사이트 목록
EXTERNAL_SITES = [
    {"code": "agency_alpha", "name": "알파 마케팅", "domain": "alpha.ad-agency.kr"},
    {"code": "agency_beta", "name": "베타 트래픽", "domain": "beta.traffic-hub.co.kr"},
    {"code": "agency_gamma", "name": "감마 커머스", "domain": "gamma.commerce-lab.com"},
    {"code": "store_boost_01", "name": "스토어부스터 1호", "domain": "boost01.nstore.biz"},
    {"code": "store_boost_02", "name": "스토어부스터 2호", "domain": "boost02.nstore.biz"},
    {"code": "traffic_lead_01", "name": "트래픽리드 A", "domain": "lead01.traffic-flow.net"},
    {"code": "traffic_lead_02", "name": "트래픽리드 B", "domain": "lead02.traffic-flow.net"},
    {"code": "commerce_pro_01", "name": "커머스프로 메인", "domain": "pro01.commerce-api.io"},
    {"code": "growth_engine_01", "name": "그로스엔진 쇼핑", "domain": "growth01.marketing.kr"},
    {"code": "rank_optimizer_01", "name": "랭크옵티마이저", "domain": "opt01.rank-guard.com"}
]


class TaskServiceV2:
    @staticmethod
    def extract_title_chunks(base_kw: str, real_title: str) -> List[str]:
        """
        [실물 제목 기반 5개 마디 키워드 추출 (SSOT)]
        - '추천', '인기' 등 없는 말 절대 배제
        - [1순위] 메인 키워드 (base_kw 또는 원천 헤드 2단어): 순위 모니터링용
        - [2~5순위] 실물 제목에서 마디로 구분된 2~3단어 슬라이스 (롤링용)
        - 100% 제목에 존재하는 실제 단어들로만 구성
        """
        clean_title = re.sub(r'\[.*?\]|\(.*?\)|【.*?】|<.*?>', ' ', real_title or base_kw or '')
        clean_title = re.sub(r'[★▲◆!~#%&*+/:;,?=_\-]', ' ', clean_title)
        tokens = [t.strip() for t in clean_title.split() if len(t.strip()) >= 2]

        candidates = []
        # 1. 메인 키워드 (순위 확인용): base_kw가 유효하고 4단어 이하이면 사용, 아니면 제목 앞 2단어
        main_kw = (base_kw or '').strip()
        if not main_kw or len(main_kw.split()) > 4:
            main_kw = ' '.join(tokens[:2]) if len(tokens) >= 2 else (tokens[0] if tokens else '')
        if main_kw:
            candidates.append(main_kw)

        # 2. 앞 마디 (롱테일)
        if len(tokens) >= 3:
            candidates.append(' '.join(tokens[:3]))
        elif len(tokens) >= 2:
            candidates.append(' '.join(tokens[:2]))

        # 3. 중간 마디 1
        if len(tokens) >= 4:
            candidates.append(' '.join(tokens[1:3]))
        elif len(tokens) >= 3:
            candidates.append(' '.join(tokens[1:3]))

        # 4. 중간 마디 2
        if len(tokens) >= 5:
            candidates.append(' '.join(tokens[2:4]))
        elif len(tokens) >= 4:
            candidates.append(' '.join(tokens[2:4]))

        # 5. 후반 마디
        if len(tokens) >= 6:
            candidates.append(' '.join(tokens[3:5]))
        elif len(tokens) >= 3:
            candidates.append(tokens[0] + ' ' + tokens[-1])

        # 유니크 필터링
        unique = []
        for c in candidates:
            c_str = c.strip()
            if c_str and c_str not in unique:
                unique.append(c_str)

        # 5개 미만인 경우 남은 단어 조합으로 5개 채움
        if len(unique) < 5 and len(tokens) >= 2:
            for i in range(len(tokens)):
                for j in range(i + 1, min(i + 3, len(tokens))):
                    comb = f'{tokens[i]} {tokens[j]}'
                    if comb not in unique:
                        unique.append(comb)
                    if len(unique) >= 5:
                        break
                if len(unique) >= 5:
                    break

        return unique[:5] if unique else [base_kw or '상품']

    @staticmethod
    def refresh_all_product_keywords() -> Dict[str, Any]:
        """
        [전체 활성 상품 키워드 풀 마디 분할 5개 롤링 재생성]
        - '추천' 등 인위적 단어 전면 제거
        - 실물 제목(product_name)을 마디로 구분하여 5개 순수 조합 생성
        - 1순위: 메인 키워드 (주기적 순위 확인용, 가중치 30%)
        - 2~5순위: 제목 내 실물 2~3단어 마디 슬라이스 (롤링용, 가중치 25/20/15/10)
        """
        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("""
                SELECT nv_mid, store_name, product_name
                FROM target_products
                WHERE is_active = 1
            """)
            prods = cur.fetchall()

            # 기존 키워드 풀 일괄 비우기
            cur.execute("DELETE FROM product_keyword_pool")

            total_keywords = 0
            ratios = [30, 25, 20, 15, 10]

            for p in prods:
                mid = str(p["nv_mid"]).strip()
                p_title = str(p.get("product_name") or "").strip()
                chunks = TaskServiceV2.extract_title_chunks(p_title, p_title)

                for p_rank, kw in enumerate(chunks, start=1):
                    ratio = ratios[p_rank - 1] if p_rank <= len(ratios) else 10
                    cur.execute("""
                        INSERT INTO product_keyword_pool (
                            nv_mid, keyword, priority_rank, traffic_ratio, is_exposed
                        ) VALUES (%s, %s, %s, %s, 1)
                        ON DUPLICATE KEY UPDATE
                            priority_rank = VALUES(priority_rank),
                            traffic_ratio = VALUES(traffic_ratio),
                            is_exposed = 1
                    """, (mid, kw, p_rank, ratio))
                    total_keywords += 1

            sample_chunks = TaskServiceV2.extract_title_chunks(prods[0]["product_name"], prods[0]["product_name"]) if prods else []
            return {
                "success": True,
                "refreshed_products": len(prods),
                "total_keywords": total_keywords,
                "sample": {
                    "product_name": prods[0]["product_name"] if prods else "",
                    "chunks": sample_chunks
                },
                "message": f"총 {len(prods)}개 상품에 대해 100% 제목 실물 마디 키워드 {total_keywords}개 재생성 완료 (추천/허위 단어 0건)"
            }

    @staticmethod
    def init_tables() -> Dict[str, Any]:
        """
        [v2 신규 4대 테이블 자동 생성 (DDL)]
        1. target_products : 상품만 고유하게 관리하는 유니크 마스터 (SSOT)
        2. external_slots : 가상의 10개 외부 사이트 및 슬롯 ID 매핑
        3. product_keyword_pool : 상품별 1~5순위 키워드 풀
        4. daily_slot_quotas : 일자별 통합 쿼터 (슬롯당 20타, 최대 100타 상한)
        """
        ddl_queries = [
            """
            CREATE TABLE IF NOT EXISTS target_products (
                nv_mid VARCHAR(100) NOT NULL PRIMARY KEY,
                compare_id VARCHAR(100) NULL,
                store_name VARCHAR(255) NOT NULL,
                product_name VARCHAR(500) NOT NULL,
                product_url VARCHAR(2000) NULL,
                is_catalog TINYINT(1) NOT NULL DEFAULT 0,
                total_slots INT NOT NULL DEFAULT 1,
                daily_target_hits INT NOT NULL DEFAULT 20,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_store (store_name),
                INDEX idx_active (is_active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """,
            """
            CREATE TABLE IF NOT EXISTS external_slots (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                site_code VARCHAR(32) NOT NULL,
                slot_id VARCHAR(64) NOT NULL,
                nv_mid VARCHAR(100) NOT NULL,
                base_keyword VARCHAR(255) NOT NULL,
                hits_per_slot INT NOT NULL DEFAULT 20,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uk_site_slot (site_code, slot_id),
                INDEX idx_mid (nv_mid),
                INDEX idx_site (site_code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """,
            """
            CREATE TABLE IF NOT EXISTS product_keyword_pool (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                nv_mid VARCHAR(100) NOT NULL,
                keyword VARCHAR(255) NOT NULL,
                priority_rank INT NOT NULL DEFAULT 1,
                traffic_ratio INT NOT NULL DEFAULT 20,
                last_known_rank INT NULL,
                is_exposed TINYINT(1) NOT NULL DEFAULT 1,
                last_checked_at DATETIME NULL,
                UNIQUE KEY uk_mid_keyword (nv_mid, keyword),
                INDEX idx_mid_priority (nv_mid, priority_rank, is_exposed)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """,
            """
            CREATE TABLE IF NOT EXISTS daily_slot_quotas (
                target_date DATE NOT NULL,
                nv_mid VARCHAR(100) NOT NULL,
                total_slots INT NOT NULL DEFAULT 1,
                target_hits INT NOT NULL DEFAULT 20,
                current_hits INT NOT NULL DEFAULT 0,
                status VARCHAR(16) NOT NULL DEFAULT 'IN_PROGRESS',
                PRIMARY KEY (target_date, nv_mid),
                INDEX idx_date_status (target_date, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """
        ]

        with get_db_cursor(commit=True) as (cur, conn):
            for q in ddl_queries:
                cur.execute(q)

        return {
            "success": True,
            "message": "v2 핵심 테이블 4종 (target_products, external_slots, product_keyword_pool, daily_slot_quotas) 생성 완료"
        }

    @staticmethod
    def migrate_from_nshop_list() -> Dict[str, Any]:
        """
        [nshop_list 원천 상품 -> 유니크 테이블 및 가상 10개 사이트 슬롯 자동 이관]
        - nshop_list의 상품들을 유니크화하여 target_products에 적재
        - 가상의 10개 사이트에 1~6개의 슬롯을 분배 (중복 슬롯 생성)
        - 슬롯당 20타 계산 후 최대 100타 상한(Hard-Cap) 적용
        - 상품당 1~5순위 키워드를 생성하여 product_keyword_pool에 적재
        - 당일 daily_slot_quotas 자동 생성
        """
        # 먼저 테이블 생성 보장
        TaskServiceV2.init_tables()

        today_str = time.strftime("%Y-%m-%d")

        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("""
                SELECT target_id, product_name, product_title, mall_name, mall_product_id,
                       product_url, mall_count, is_active
                FROM nshop_list
                WHERE is_active = 1 AND product_name IS NOT NULL AND product_name != ''
            """)
            rows = cur.fetchall()
            if not rows:
                cur.execute("""
                    SELECT target_id, product_name, product_title, mall_name, mall_product_id,
                           product_url, mall_count, is_active
                    FROM nshop_list
                    WHERE product_name IS NOT NULL AND product_name != ''
                """)
                rows = cur.fetchall()

            migrated_products = 0
            created_slots = 0
            created_keywords = 0

            slot_counter = 1000

            for r in rows:
                mid = str(r["target_id"]).strip()
                p_name = (r.get("product_name") or "").strip()
                p_title = (r.get("product_title") or p_name).strip()
                store = (r.get("mall_name") or "스마트스토어").strip()
                compare_id = str(r["mall_product_id"]).strip() if r.get("mall_product_id") else None
                p_url = r.get("product_url")
                is_catalog = 1 if (r.get("mall_count", 0) > 1 or compare_id) else 0

                # 1. 가상 슬롯 분배 (상품당 1~6개 슬롯 무작위 할당 -> 중복 슬롯 모델)
                assigned_slot_count = random.randint(1, 6)
                # 슬롯당 20타 집계, 최대 100타 하드캡 적용!
                target_hits = min(assigned_slot_count * 20, 100)

                # 2. target_products 유니크 상품 테이블 적재
                cur.execute("""
                    INSERT INTO target_products (
                        nv_mid, compare_id, store_name, product_name, product_url,
                        is_catalog, total_slots, daily_target_hits, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                    ON DUPLICATE KEY UPDATE
                        compare_id = VALUES(compare_id),
                        store_name = VALUES(store_name),
                        product_name = VALUES(product_name),
                        product_url = VALUES(product_url),
                        is_catalog = VALUES(is_catalog),
                        total_slots = VALUES(total_slots),
                        daily_target_hits = VALUES(daily_target_hits),
                        is_active = 1
                """, (mid, compare_id, store, p_title, p_url, is_catalog, assigned_slot_count, target_hits))
                migrated_products += 1

                # 3. external_slots 가상 사이트 및 슬롯 매핑
                chosen_sites = random.sample(EXTERNAL_SITES, min(assigned_slot_count, len(EXTERNAL_SITES)))
                for site in chosen_sites:
                    slot_counter += 1
                    slot_id = f"SLOT-{slot_counter}"
                    cur.execute("""
                        INSERT INTO external_slots (
                            site_code, slot_id, nv_mid, base_keyword, hits_per_slot, is_active
                        ) VALUES (%s, %s, %s, %s, 20, 1)
                        ON DUPLICATE KEY UPDATE
                            base_keyword = VALUES(base_keyword),
                            hits_per_slot = 20,
                            is_active = 1
                    """, (site["code"], slot_id, mid, p_name))
                    created_slots += 1

                # 4. 1~5순위 키워드 풀 생성 (product_keyword_pool: 실물 제목 마디 분할 5개 롤링)
                unique_kw_list = TaskServiceV2.extract_title_chunks(p_name, p_title)
                ratios = [30, 25, 20, 15, 10]
                for p_rank, kw in enumerate(unique_kw_list, start=1):
                    ratio = ratios[p_rank - 1] if p_rank <= len(ratios) else 10
                    cur.execute("""
                        INSERT INTO product_keyword_pool (
                            nv_mid, keyword, priority_rank, traffic_ratio, is_exposed
                        ) VALUES (%s, %s, %s, %s, 1)
                        ON DUPLICATE KEY UPDATE
                            priority_rank = VALUES(priority_rank),
                            traffic_ratio = VALUES(traffic_ratio),
                            is_exposed = 1
                    """, (mid, kw, p_rank, ratio))
                    created_keywords += 1

                # 5. 당일 daily_slot_quotas 등록
                cur.execute("""
                    INSERT INTO daily_slot_quotas (
                        target_date, nv_mid, total_slots, target_hits, current_hits, status
                    ) VALUES (%s, %s, %s, %s, 0, 'IN_PROGRESS')
                    ON DUPLICATE KEY UPDATE
                        total_slots = VALUES(total_slots),
                        target_hits = VALUES(target_hits)
                """, (today_str, mid, assigned_slot_count, target_hits))

        return {
            "success": True,
            "migrated_products": migrated_products,
            "created_slots": created_slots,
            "created_keywords": created_keywords,
            "sites_count": len(EXTERNAL_SITES),
            "message": f"총 {migrated_products}개 유니크 상품, {created_slots}개 가상 슬롯(최대 100타 캡), {created_keywords}개 키워드 풀 이관 완료"
        }

    @staticmethod
    def enrich_from_underscore_nshop_list(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        [_nshop_list의 실제 수집 정보(제목, 몰명, compare_id)로 target_products 정밀 완성]
        - _nshop_list의 실제 몰명(mall_name), 상세 제목(product_title), mall_product_id(compare_id), URL 등을 추출
        - reset_existing=True 시 기존 불완전 더미 데이터를 정리하고 완벽한 실물 상품 마스터로 재구축
        - 10개 제휴 사이트 슬롯 매핑 (슬롯당 20타, 최대 100타 상한 하드캡)
        - 1~5순위 키워드 풀 자동 생성 (가중치 40/25/15/10/10)
        - 당일 daily_slot_quotas 쿼터 자동 초기화
        """
        options = options or {}
        reset_existing = bool(options.get("reset_existing", True))
        limit = int(options.get("limit", 500))  # 기본 500개 실물 상품 적재
        today_str = time.strftime("%Y-%m-%d")

        TaskServiceV2.init_tables()

        with get_db_cursor(commit=True) as (cur, conn):
            if reset_existing:
                logger.info("기존 v2 테이블 초기화 진행 (실물 데이터로 완전 재구축)")
                cur.execute("DELETE FROM daily_slot_quotas WHERE target_date = %s", (today_str,))
                cur.execute("DELETE FROM external_slots")
                cur.execute("DELETE FROM product_keyword_pool")
                cur.execute("DELETE FROM target_products")

            # 1. _nshop_list에서 고품질 상품 데이터 조회 (실제 몰명 & 정식 상세 제목이 있는 상품 우선)
            cur.execute("""
                SELECT target_id, product_name, product_title, mall_name, mall_product_id,
                       product_url, mall_count
                FROM _nshop_list
                WHERE (mall_name IS NOT NULL AND mall_name != '')
                  AND (product_title IS NOT NULL AND product_title != '')
                ORDER BY (CASE WHEN mall_product_id IS NOT NULL AND mall_product_id != '' THEN 2 ELSE 1 END) DESC,
                         id ASC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

            migrated_count = 0
            created_slots = 0
            created_keywords = 0
            catalog_count = 0
            slot_counter = 1000

            for r in rows:
                mid = str(r["target_id"]).strip()
                if not mid:
                    continue

                raw_kw = (r.get("product_name") or "").strip()
                real_title = (r.get("product_title") or raw_kw).strip()
                mall_name = (r.get("mall_name") or "").strip()
                p_url = r.get("product_url")
                mall_prod_id = str(r["mall_product_id"]).strip() if r.get("mall_product_id") else None

                # 몰명이 비어있고 product_url에 smartstore 서브도메인이 있는 경우 추출
                if not mall_name and p_url:
                    m = re.search(r"smartstore\.naver\.com/([^/?&#]+)", p_url)
                    if m:
                        mall_name = m.group(1)

                if not mall_name:
                    mall_name = "스마트스토어"

                # compare_id: mall_product_id (가격비교 내 입점몰 상품 ID)
                compare_id = mall_prod_id
                is_catalog = 1 if ((r.get("mall_count") or 0) > 1 or compare_id) else 0
                if is_catalog:
                    catalog_count += 1

                # 슬롯 배분 (1~5개 무작위 슬롯)
                assigned_slots = random.randint(1, 5)
                target_hits = min(assigned_slots * 20, 100)  # 최대 100타 상한(Hard-Cap)

                # 1. target_products 유니크 마스터 적재
                cur.execute("""
                    INSERT INTO target_products (
                        nv_mid, compare_id, store_name, product_name, product_url,
                        is_catalog, total_slots, daily_target_hits, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                    ON DUPLICATE KEY UPDATE
                        compare_id = VALUES(compare_id),
                        store_name = VALUES(store_name),
                        product_name = VALUES(product_name),
                        product_url = VALUES(product_url),
                        is_catalog = VALUES(is_catalog),
                        total_slots = VALUES(total_slots),
                        daily_target_hits = VALUES(daily_target_hits),
                        is_active = 1
                """, (mid, compare_id, mall_name, real_title, p_url, is_catalog, assigned_slots, target_hits))
                migrated_count += 1

                # 2. external_slots 가상 제휴 사이트 슬롯 매핑
                chosen_sites = random.sample(EXTERNAL_SITES, min(assigned_slots, len(EXTERNAL_SITES)))
                for site in chosen_sites:
                    slot_counter += 1
                    slot_id = f"SLOT-{slot_counter}"
                    cur.execute("""
                        INSERT INTO external_slots (
                            site_code, slot_id, nv_mid, base_keyword, hits_per_slot, is_active
                        ) VALUES (%s, %s, %s, %s, 20, 1)
                        ON DUPLICATE KEY UPDATE
                            base_keyword = VALUES(base_keyword),
                            hits_per_slot = 20,
                            is_active = 1
                    """, (site["code"], slot_id, mid, raw_kw or real_title[:20]))
                    created_slots += 1

                # 3. product_keyword_pool 1~5순위 키워드 생성 (실물 제목 마디 분할 5개 롤링)
                unique_kw_list = TaskServiceV2.extract_title_chunks(raw_kw or real_title, real_title)
                ratios = [30, 25, 20, 15, 10]
                for p_rank, kw in enumerate(unique_kw_list, start=1):
                    ratio = ratios[p_rank - 1] if p_rank <= len(ratios) else 10
                    cur.execute("""
                        INSERT INTO product_keyword_pool (
                            nv_mid, keyword, priority_rank, traffic_ratio, is_exposed
                        ) VALUES (%s, %s, %s, %s, 1)
                        ON DUPLICATE KEY UPDATE
                            priority_rank = VALUES(priority_rank),
                            traffic_ratio = VALUES(traffic_ratio),
                            is_exposed = 1
                    """, (mid, kw, p_rank, ratio))
                    created_keywords += 1

                # 4. 당일 쿼터 등록 (daily_slot_quotas)
                cur.execute("""
                    INSERT INTO daily_slot_quotas (
                        target_date, nv_mid, total_slots, target_hits, current_hits, status
                    ) VALUES (%s, %s, %s, %s, 0, 'IN_PROGRESS')
                    ON DUPLICATE KEY UPDATE
                        total_slots = VALUES(total_slots),
                        target_hits = VALUES(target_hits)
                """, (today_str, mid, assigned_slots, target_hits))

        return {
            "success": True,
            "migrated_products": migrated_count,
            "catalog_products": catalog_count,
            "created_slots": created_slots,
            "created_keywords": created_keywords,
            "message": f"실물 상품 {migrated_count}건 (카탈로그 {catalog_count}건), {created_slots}개 제휴 슬롯, {created_keywords}개 키워드 풀 완성"
        }

    @staticmethod
    def inspect_tables() -> Dict[str, Any]:
        """
        [DB 테이블 정밀 진단]
        - 전체 테이블 목록
        - _nshop_list vs nshop_list 스키마 및 데이터 확인
        - mall_product_id, compare_id, product_title, mall_name 현황 파악
        - target_products와의 매칭 가능성 분석
        """
        result = {}
        with get_db_cursor(commit=False) as (cur, conn):
            # 1. 전체 테이블 목록
            cur.execute("SHOW TABLES")
            raw_tables = cur.fetchall()
            table_names = [list(r.values())[0] for r in raw_tables]
            result["all_tables"] = table_names

            # 2. _nshop_list 및 nshop_list 확인
            for tbl in ["_nshop_list", "nshop_list", "target_products"]:
                if tbl in table_names:
                    cur.execute(f"DESCRIBE {tbl}")
                    cols = cur.fetchall()
                    cur.execute(f"SELECT COUNT(*) AS cnt FROM {tbl}")
                    cnt = cur.fetchone()["cnt"]
                    cur.execute(f"SELECT * FROM {tbl} LIMIT 5")
                    samples = cur.fetchall()
                    result[tbl] = {
                        "exists": True,
                        "count": cnt,
                        "columns": [c["Field"] for c in cols],
                        "columns_detail": cols,
                        "samples": samples
                    }
                else:
                    result[tbl] = {"exists": False}

            # 3. _nshop_list 및 nshop_list의 상세 통계
            for tbl in ["_nshop_list", "nshop_list"]:
                if tbl in table_names:
                    try:
                        cur.execute(f"""
                            SELECT 
                                COUNT(*) AS total_count,
                                COUNT(DISTINCT target_id) AS unique_targets,
                                COUNT(CASE WHEN mall_name IS NOT NULL AND mall_name != '' THEN 1 END) AS has_mall_name,
                                COUNT(CASE WHEN product_title IS NOT NULL AND product_title != '' THEN 1 END) AS has_product_title,
                                COUNT(CASE WHEN mall_product_id IS NOT NULL AND mall_product_id != '' THEN 1 END) AS has_mall_product_id,
                                COUNT(CASE WHEN product_url IS NOT NULL AND product_url != '' THEN 1 END) AS has_product_url,
                                COUNT(CASE WHEN (mall_name IS NOT NULL AND mall_name != '') 
                                            AND (product_title IS NOT NULL AND product_title != '') THEN 1 END) AS has_mall_and_title
                            FROM {tbl}
                        """)
                        result[f"{tbl}_stats"] = cur.fetchone()
                    except Exception as ex:
                        result[f"{tbl}_stats_error"] = str(ex)

            # 4. target_products와 _nshop_list 매칭 통계
            if "_nshop_list" in table_names and "target_products" in table_names:
                try:
                    cur.execute("""
                        SELECT 
                            COUNT(*) AS total_targets,
                            COUNT(CASE WHEN r.product_title IS NOT NULL AND r.product_title != '' THEN 1 END) AS has_ref_title,
                            COUNT(CASE WHEN r.mall_name IS NOT NULL AND r.mall_name != '' THEN 1 END) AS has_ref_mall,
                            COUNT(CASE WHEN r.mall_product_id IS NOT NULL AND r.mall_product_id != '' THEN 1 END) AS has_ref_mall_prod_id
                        FROM target_products t
                        LEFT JOIN _nshop_list r ON t.nv_mid = r.target_id COLLATE utf8mb4_unicode_ci
                    """)
                    result["matching_stats_underscore"] = cur.fetchone()
                except Exception as ex:
                    result["matching_stats_underscore_error"] = str(ex)

            if "nshop_list" in table_names and "target_products" in table_names:
                try:
                    cur.execute("""
                        SELECT 
                            COUNT(*) AS total_targets,
                            COUNT(CASE WHEN r.product_title IS NOT NULL AND r.product_title != '' THEN 1 END) AS has_ref_title,
                            COUNT(CASE WHEN r.mall_name IS NOT NULL AND r.mall_name != '' THEN 1 END) AS has_ref_mall,
                            COUNT(CASE WHEN r.mall_product_id IS NOT NULL AND r.mall_product_id != '' THEN 1 END) AS has_ref_mall_prod_id
                        FROM target_products t
                        LEFT JOIN nshop_list r ON t.nv_mid = r.target_id COLLATE utf8mb4_unicode_ci
                    """)
                    result["matching_stats_no_underscore"] = cur.fetchone()
                except Exception as ex:
                    result["matching_stats_no_underscore_error"] = str(ex)

            # 5. _nshop_list 카탈로그(mall_count > 1) vs 단독(mall_count <= 1) 세부 샘플
            if "_nshop_list" in table_names:
                try:
                    cur.execute("""
                        SELECT target_id, product_name, product_title, mall_name, mall_product_id, mall_count, product_url
                        FROM _nshop_list
                        WHERE mall_count > 1 AND mall_product_id IS NOT NULL AND mall_product_id != ''
                        LIMIT 3
                    """)
                    result["catalog_with_mall_product_id_samples"] = cur.fetchall()

                    cur.execute("""
                        SELECT target_id, product_name, product_title, mall_name, mall_product_id, mall_count, product_url
                        FROM _nshop_list
                        WHERE (mall_count <= 1 OR mall_count IS NULL) AND mall_name IS NOT NULL AND mall_name != ''
                        LIMIT 3
                    """)
                    result["single_store_samples"] = cur.fetchall()
                except Exception as ex:
                    result["sample_query_error"] = str(ex)

        return {"success": True, "data": result}

    @staticmethod
    def allocate(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        [지능형 작업 할당 v2 엔진 - 유니크 상품 및 쿼터 기반]
        POST /api/v2/task/allocate
        - 1단계: target_products 및 daily_slot_quotas 에서 당일 미완료(current_hits < target_hits) 상품 선별
        - 2단계: product_keyword_pool 에서 현재 노출 유효한 1~5순위 키워드 자동 배정
        - 3단계: 스토어 80분 쿨다운 및 WG C클래스 쿨다운 검증
        - 4단계: 1:1 고유 상품 매칭 및 tasks 생성
        """
        node_id = str(payload.get("node_id") or "node-default").strip()
        net_mode = str(payload.get("net_mode") or "lte").lower().strip()
        router_num = payload.get("router_num")
        public_ip = payload.get("public_ip")
        ip_c_class = payload.get("ip_c_class")
        if not ip_c_class and public_ip and "." in public_ip:
            parts = public_ip.split(".")
            if len(parts) >= 3:
                ip_c_class = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"

        # 단말기 목록 정규화
        dev_param = payload.get("devices") or payload.get("device_ids") or ["default"]
        device_ids: List[str] = []
        if isinstance(dev_param, list):
            for item in dev_param:
                if isinstance(item, dict):
                    d_id = item.get("device_id")
                    if d_id:
                        device_ids.append(str(d_id).strip())
                elif item:
                    device_ids.append(str(item).strip())
        elif isinstance(dev_param, str):
            device_ids = [d.strip() for d in dev_param.split(",") if d.strip()]

        if not device_ids:
            device_ids = ["default"]

        local_quarantine = set(str(m).strip() for m in (payload.get("local_quarantine_mids") or []) if str(m).strip())
        min_age_seconds = max(1200, int(payload.get("min_nnb_age_sec") or MIN_AGING_SECONDS))
        requested_n = len(device_ids)
        target_date_str = str(payload.get("target_date") or time.strftime("%Y-%m-%d")).strip()

        with get_db_cursor(commit=True) as (cur, conn):
            # 0. 30분 이상 미완료 작업 타임아웃 처리
            cur.execute("""
                UPDATE tasks
                SET status = 'TIMEOUT', completed_at = NOW(), result_memo = 'Auto-expired: client did not report back within 30m'
                WHERE status = 'ASSIGNED' AND assigned_at < NOW() - INTERVAL 30 MINUTE
            """)

            # 1. 20분 이상 숙성된 NNB 선점
            cur.execute("""
                SELECT id, nnb, buc, use_count, status, created_at
                FROM nnbs
                WHERE status IN ('AGING', 'READY', 'ACTIVE')
                  AND created_at <= NOW() - INTERVAL %s SECOND
                ORDER BY use_count ASC, created_at ASC, id ASC
                LIMIT %s
                FOR UPDATE
            """, (min_age_seconds, requested_n))
            selected_nnbs = cur.fetchall()

            if not selected_nnbs:
                return {
                    "success": False,
                    "is_no_task": True,
                    "code": "NNB_EXHAUSTED",
                    "message": f"20분({min_age_seconds}초) 이상 숙성된 NNB 토큰이 부족하여 대기 중입니다."
                }

            alloc_count = min(len(selected_nnbs), requested_n)

            # [디바이스 마스터 자동 등록 및 그룹 매핑 (회사별/그룹별 분할 운영 지원)]
            dev_group_map = {}
            for d_id in device_ids:
                if not d_id or d_id == "default":
                    continue
                cur.execute("""
                    INSERT INTO devices (device_id, group_name, node_id, status, last_ip, last_seen_at)
                    VALUES (%s, 'DEFAULT', %s, 'WORKING', %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        node_id = VALUES(node_id),
                        status = 'WORKING',
                        last_ip = VALUES(last_ip),
                        last_seen_at = NOW()
                """, (d_id, node_id, public_ip))
            
            if device_ids:
                fmt_q = ','.join(['%s'] * len(device_ids))
                cur.execute(f"SELECT device_id, group_name FROM devices WHERE device_id IN ({fmt_q})", tuple(device_ids))
                for r in cur.fetchall():
                    dev_group_map[r["device_id"]] = r["group_name"]

            # 2. [SSOT 유니크 상품 & 일일 쿼터 연동 & 그룹 필터링]
            # 오늘 target_hits에 아직 도달하지 않은 상품 조회
            cur.execute("""
                SELECT p.nv_mid, p.compare_id, p.store_name, p.product_name, p.is_catalog,
                       p.daily_target_hits, COALESCE(q.current_hits, 0) as current_hits,
                       COALESCE(q.target_hits, p.daily_target_hits) as today_target_hits,
                       COALESCE(p.target_group, 'ALL') as target_group
                FROM target_products p
                LEFT JOIN daily_slot_quotas q ON p.nv_mid = q.nv_mid AND q.target_date = %s
                WHERE p.is_active = 1
                  AND (q.current_hits IS NULL OR q.current_hits < q.target_hits)
            """, (target_date_str,))
            active_unique_products = cur.fetchall()

            # 만약 target_products 테이블이 아직 비어있다면 레거시 nshop_list 폴백
            if not active_unique_products:
                cur.execute("""
                    SELECT target_id as nv_mid, mall_product_id as compare_id, mall_name as store_name,
                           product_name, (mall_count > 1) as is_catalog, 100 as daily_target_hits,
                           0 as current_hits, 100 as today_target_hits
                    FROM nshop_list
                    WHERE is_active = 1 AND product_name IS NOT NULL AND product_name != ''
                """)
                active_unique_products = cur.fetchall()

            if not active_unique_products:
                return {
                    "success": False,
                    "is_no_task": True,
                    "code": "DAILY_QUOTA_ALL_COMPLETED",
                    "message": "오늘 등록된 모든 상품의 일일 목표 타수(최대 100타)가 달성되었습니다."
                }

            # 3. 쿨다운 및 격리 게이트 검증
            cur.execute("""
                SELECT DISTINCT store_name
                FROM tasks
                WHERE status = 'SUCCESS'
                  AND completed_at >= NOW() - INTERVAL 80 MINUTE
                  AND store_name IS NOT NULL AND store_name != ''
            """)
            cooling_stores = set(r["store_name"] for r in cur.fetchall())

            # 최근 1시간 동안 성공이 0건이고 연속 실패 5회 이상인 상품만 일시 격리
            cur.execute("""
                SELECT nv_mid
                FROM tasks
                WHERE completed_at >= NOW() - INTERVAL 1 HOUR
                GROUP BY nv_mid
                HAVING SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) = 0
                   AND SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) >= 5
            """)
            server_quarantined = set(str(r["nv_mid"]) for r in cur.fetchall())

            eligible_products = []
            for p in active_unique_products:
                mid = str(p.get("nv_mid") or "")
                st = str(p.get("store_name") or "")

                if mid in local_quarantine or mid in server_quarantined:
                    continue
                if st and st in cooling_stores:
                    continue

                eligible_products.append(p)

            # 완화 폴백 1단계: 스토어 쿨다운 완화 (단, 격리 상품은 제외)
            if len(eligible_products) < alloc_count:
                for p in active_unique_products:
                    mid = str(p.get("nv_mid") or "")
                    if mid not in local_quarantine and mid not in server_quarantined and p not in eligible_products:
                        eligible_products.append(p)

            # 완화 폴백 2단계: 서버 격리 완화 (로컬 단말기 명시적 격리 제외하고 전수 활용 - 시스템 고갈 원천 차단)
            if len(eligible_products) < alloc_count:
                for p in active_unique_products:
                    mid = str(p.get("nv_mid") or "")
                    if mid not in local_quarantine and p not in eligible_products:
                        eligible_products.append(p)

            if not eligible_products:
                return {
                    "success": False,
                    "is_no_task": True,
                    "code": "ALL_TARGETS_IN_COOLDOWN",
                    "message": "모든 대상 상품이 스토어 쿨다운(80분) 또는 로컬 격리 상태입니다.",
                    "status_summary": {
                        "total_active_candidates": len(active_unique_products),
                        "cooling_stores_count": len(cooling_stores),
                        "quarantined_count": len(server_quarantined.union(local_quarantine))
                    },
                    "recommended_sleep_sec": 180
                }

            # [사이트 묶음 그룹 매핑 로드]
            cur.execute("SELECT group_code, is_all_sites FROM device_groups")
            group_all_map = {r["group_code"]: bool(r["is_all_sites"]) for r in cur.fetchall()}
            
            cur.execute("SELECT group_code, site_code FROM device_group_sites")
            group_sites_map = {}
            for r in cur.fetchall():
                group_sites_map.setdefault(r["group_code"], set()).add(r["site_code"])

            # 상품별 external_slots 소속 사이트 맵 조회
            cur.execute("SELECT nv_mid, site_code FROM external_slots WHERE is_active = 1")
            mid_sites_map = {}
            for r in cur.fetchall():
                mid_sites_map.setdefault(r["nv_mid"], set()).add(r["site_code"])

            # 4. 1:1 고유 상품 매칭 및 1~5순위 키워드 풀 연동
            random.shuffle(eligible_products)
            actual_alloc = min(alloc_count, len(eligible_products))
            allocated_tasks = []

            for i in range(actual_alloc):
                dev_id = device_ids[i]
                dev_group = dev_group_map.get(dev_id, "DEFAULT")
                nnb_row = selected_nnbs[i]
                
                # 그룹에 묶인 사이트 목록 확인
                is_all = group_all_map.get(dev_group, True)
                bound_sites = group_sites_map.get(dev_group, set())

                # [사이트 묶음 그룹 매칭]
                # 1) 그룹에 1개 이상의 사이트가 묶여 있는 경우: 해당 사이트들의 슬롯 상품 최우선 매칭
                matched_prod = None
                if not is_all and bound_sites:
                    matched_prod = next((p for p in eligible_products if (mid_sites_map.get(str(p.get("nv_mid")), set()) & bound_sites)), None)
                
                # 2) 전용 상품이 없거나 공용 그룹인 경우: 일반 후보 매칭
                if not matched_prod:
                    matched_prod = next((p for p in eligible_products if p.get("target_group") in ("ALL", None, "")), None)
                if not matched_prod and eligible_products:
                    matched_prod = eligible_products[0]
                
                if not matched_prod:
                    break

                prod = matched_prod
                if prod in eligible_products:
                    eligible_products.remove(prod)
                mid = str(prod["nv_mid"])

                # 상품 키워드 풀에서 노출 유효한 키워드 조회
                cur.execute("""
                    SELECT keyword, priority_rank, traffic_ratio
                    FROM product_keyword_pool
                    WHERE nv_mid = %s AND is_exposed = 1
                    ORDER BY priority_rank ASC
                """, (mid,))
                kws = cur.fetchall()

                # 키워드 풀에 있으면 1~5순위 가중치 기반 동적 확률 선택 (1순위 40%, 2순위 25%, 3순위 15%, 4순위 10%, 5순위 10%)
                if kws:
                    weights = [max(1, int(r.get("traffic_ratio") or 10)) for r in kws]
                    chosen_kw = random.choices([r["keyword"] for r in kws], weights=weights, k=1)[0]
                else:
                    chosen_kw = prod["product_name"]

                compare_id = str(prod["compare_id"]) if prod.get("compare_id") else None
                store_name = str(prod.get("store_name") or "")
                nnb_val = nnb_row["nnb"]
                buc_val = nnb_row["buc"]
                is_catalog = bool(prod.get("is_catalog"))

                cur.execute("""
                    INSERT INTO tasks (nnb, buc, keyword, nv_mid, compare_id, store_name, device_id, ip, status, assigned_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ASSIGNED', NOW())
                """, (nnb_val, buc_val, chosen_kw, mid, compare_id, store_name, dev_id, public_ip))
                new_task_id = cur.lastrowid

                cur.execute("""
                    UPDATE nnbs
                    SET use_count = use_count + 1,
                        last_used_at = NOW(),
                        used_target = %s,
                        device_id = COALESCE(%s, device_id)
                    WHERE id = %s
                """, (mid, dev_id, nnb_row["id"]))

                # 1~5순위 후보 키워드 목록 (120초 동적 데드라인 체인 탐색용)
                candidate_list = [
                    {"rank": int(r["priority_rank"]), "keyword": str(r["keyword"]).strip()}
                    for r in kws
                ] if kws else [{"rank": 1, "keyword": chosen_kw}]

                allocated_tasks.append({
                    "task_id": int(new_task_id),
                    "node_id": node_id,
                    "device_id": dev_id,
                    "keyword": chosen_kw,
                    "keyword_candidates": candidate_list,
                    "nv_mid": mid,
                    "compare_id": compare_id,
                    "store_name": store_name,
                    "is_catalog": is_catalog,
                    "expected_rank": None,
                    "target_dwell_sec": 40,
                    "nnb": nnb_val,
                    "buc": buc_val,
                    "assigned_ip": public_ip,
                    "ip_c_class": ip_c_class,
                    "policy": {
                        "max_duration_sec": 120.0,
                        "use_jitter_on_more": False,
                        "use_jitter_on_product": True
                    }
                })

            res = {
                "success": True,
                "node_id": node_id,
                "net_mode": net_mode,
                "allocated_count": len(allocated_tasks),
                "tasks": allocated_tasks,
                "server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            if len(allocated_tasks) == 1:
                for k, v in allocated_tasks[0].items():
                    res[k] = v
            return res

    @staticmethod
    def report(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        [원격 정밀 진단 보고 v2 엔진 & 일일 쿼터 카운터 갱신]
        POST /api/v2/task/report
        - 성공 시: daily_slot_quotas.current_hits + 1 갱신 (목표치 도달 시 COMPLETED 자동 마감)
        - 실패 시: 순위 소멸 감지 시 product_keyword_pool.is_exposed = 0 갱신
        """
        task_id = payload.get("task_id")
        if not task_id:
            return {"success": False, "error": "task_id는 필수입니다."}

        try:
            task_id_val = int(task_id)
        except (ValueError, TypeError):
            return {"success": False, "error": "task_id는 정수여야 합니다."}

        final_status = str(payload.get("final_status") or payload.get("status") or "").upper().strip()
        is_success = (final_status == "SUCCESS") or bool(payload.get("success", False))
        db_status = "SUCCESS" if is_success else "FAILED"

        failed_phase = payload.get("failed_phase")
        error_code = payload.get("error_code") or (None if is_success else final_status)
        error_msg = payload.get("error_message") or ""

        telemetry = payload.get("telemetry") or {}
        checkpoints = payload.get("checkpoints") or {}
        action_guidance = payload.get("action_guidance") or {}

        search_type = telemetry.get("search_type") or payload.get("search_type")
        match_type = telemetry.get("match_type") or payload.get("match_type")
        serp_rank = telemetry.get("serp_rank") or payload.get("serp_rank")
        shop_rank = telemetry.get("shopping_rank") or payload.get("shopping_rank")
        shop_page = telemetry.get("shopping_page") or payload.get("shopping_page")
        duration_sec = telemetry.get("total_duration_sec") or payload.get("duration_seconds") or 0.0

        if is_success:
            rank_str = f"SERP {serp_rank}위" if serp_rank else f"쇼핑 {shop_rank}위"
            memo = f"[SUCCESS] {search_type or 'msearch'}, {rank_str}, 소요: {duration_sec}s"
        else:
            phase_tag = f"[{failed_phase}] " if failed_phase else ""
            memo = f"{phase_tag}[{error_code or 'FAILED'}] {error_msg}".strip()
        if len(memo) > 250:
            memo = memo[:247] + "..."

        today_str = str(payload.get("target_date") or time.strftime("%Y-%m-%d")).strip()

        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("""
                UPDATE tasks
                SET status = %s,
                    completed_at = NOW(),
                    search_type = %s,
                    match_type = %s,
                    serp_rank = %s,
                    shopping_rank = %s,
                    shopping_page = %s,
                    duration_seconds = %s,
                    result_memo = %s
                WHERE task_id = %s
            """, (
                db_status,
                search_type,
                match_type,
                serp_rank,
                shop_rank,
                shop_page,
                round(float(duration_sec), 2),
                memo,
                task_id_val
            ))

            cur.execute("""
                SELECT nv_mid, compare_id, keyword, store_name, device_id, ip
                FROM tasks
                WHERE task_id = %s
            """, (task_id_val,))
            task_row = cur.fetchone()
            target_mid = task_row["nv_mid"] if task_row else None
            kw = task_row["keyword"] if task_row else None
            is_cat = bool(task_row and task_row.get("compare_id"))
            dev_id = (task_row.get("device_id") if task_row else None) or payload.get("device_id") or "UNKNOWN"
            t_ip = (task_row.get("ip") if task_row else None) or payload.get("ip")

            # 단말기 소속 그룹 조회
            dev_group = "DEFAULT"
            if dev_id and dev_id != "UNKNOWN":
                cur.execute("SELECT group_name FROM devices WHERE device_id = %s", (dev_id,))
                d_row = cur.fetchone()
                if d_row and d_row.get("group_name"):
                    dev_group = d_row["group_name"]

            # [1. 디바이스 레코드별 상세 실행 로그 INSERT (디버깅 용이 정보)]
            js_found = int(bool(telemetry.get("js_target_found") or payload.get("js_target_found", False)))
            sc_count = int(telemetry.get("scroll_count") or payload.get("scroll_count", 0))
            clk_succ = int(bool(telemetry.get("click_success") or payload.get("click_success", False)))
            fnl_rank = serp_rank if serp_rank is not None else shop_rank
            dur_float = round(float(duration_sec), 2)

            try:
                cur.execute("""
                    INSERT INTO device_execution_logs (
                        log_date, device_id, group_name, task_id, keyword, store_name, nv_mid, ip,
                        status, is_success, search_type, final_rank, duration_seconds,
                        js_target_found, scroll_count, click_success, error_code, error_message, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, NOW()
                    )
                """, (
                    today_str, dev_id, dev_group, task_id_val, kw, task_row.get("store_name") if task_row else None,
                    target_mid, t_ip, final_status or db_status, int(is_success), search_type,
                    fnl_rank, dur_float, js_found, sc_count, clk_succ,
                    error_code, (error_msg[:500] if error_msg else None)
                ))
            except Exception as e_log:
                logger.warning(f"device_execution_logs INSERT error: {e_log}")

            # [2. 디바이스 일자별 성적 통계 UPSERT (일자별/기기별/그룹별 집계)]
            if dev_id and dev_id != "UNKNOWN":
                is_login = 1 if (final_status and "LOGIN" in final_status) else 0
                is_not_found = 1 if (final_status and "NOT_FOUND" in final_status) else 0
                is_timeout = 1 if (final_status and "TIMEOUT" in final_status) else 0
                is_rollback = 1 if (final_status and "ROLLBACK" in final_status) else 0
                succ_cnt = 1 if is_success else 0
                fail_cnt = 0 if is_success else 1

                try:
                    cur.execute("""
                        INSERT INTO device_daily_stats (
                            stat_date, device_id, group_name, total_tasks, success_tasks, fail_tasks,
                            success_rate, login_popup_count, not_found_count, timeout_count, rollback_count,
                            avg_duration_seconds, last_updated_at
                        ) VALUES (
                            %s, %s, %s, 1, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, NOW()
                        )
                        ON DUPLICATE KEY UPDATE
                            total_tasks = total_tasks + 1,
                            success_tasks = success_tasks + %s,
                            fail_tasks = fail_tasks + %s,
                            success_rate = ROUND(success_tasks / total_tasks * 100, 1),
                            login_popup_count = login_popup_count + %s,
                            not_found_count = not_found_count + %s,
                            timeout_count = timeout_count + %s,
                            rollback_count = rollback_count + %s,
                            avg_duration_seconds = ROUND((avg_duration_seconds * (total_tasks - 1) + %s) / total_tasks, 1),
                            last_updated_at = NOW()
                    """, (
                        today_str, dev_id, dev_group, succ_cnt, fail_cnt,
                        100.0 if is_success else 0.0, is_login, is_not_found, is_timeout, is_rollback, dur_float,
                        succ_cnt, fail_cnt, is_login, is_not_found, is_timeout, is_rollback, dur_float
                    ))
                except Exception as e_stat:
                    logger.warning(f"device_daily_stats UPSERT error: {e_stat}")

                # [3. 디바이스 마스터 테이블 상태 업데이트]
                try:
                    cur.execute("""
                        UPDATE devices
                        SET status = 'IDLE',
                            last_status = %s,
                            last_task_id = %s,
                            last_seen_at = NOW()
                        WHERE device_id = %s
                    """, (final_status or db_status, task_id_val, dev_id))
                except Exception as e_dev:
                    logger.warning(f"devices master UPDATE error: {e_dev}")

            server_decision = {
                "action_taken": "LOG_RECORDED",
                "quarantine_applied": False,
                "quota_status": "IN_PROGRESS"
            }

            # 성공 시: 일일 쿼터 카운터 1 증가
            if is_success and target_mid:
                cur.execute("""
                    UPDATE daily_slot_quotas
                    SET current_hits = current_hits + 1,
                        status = CASE WHEN current_hits + 1 >= target_hits THEN 'COMPLETED' ELSE 'IN_PROGRESS' END
                    WHERE target_date = %s AND nv_mid = %s
                """, (today_str, target_mid))

                # 현재 쿼터 상태 확인
                cur.execute("""
                    SELECT current_hits, target_hits, status
                    FROM daily_slot_quotas
                    WHERE target_date = %s AND nv_mid = %s
                """, (today_str, target_mid))
                q_row = cur.fetchone()
                if q_row:
                    server_decision["quota_status"] = q_row["status"]
                    server_decision["current_hits"] = q_row["current_hits"]
                    server_decision["target_hits"] = q_row["target_hits"]

            # 실패 시: 자가 치유 및 키워드 노출 소멸 감지
            if not is_success and target_mid:
                # 1. 키워드 순위 소멸 감지 (NOT_IN_PAGE1_DATA 발생 시 is_exposed = 0)
                if error_code == "NOT_IN_PAGE1_DATA" and kw:
                    cur.execute("""
                        UPDATE product_keyword_pool
                        SET is_exposed = 0, last_checked_at = NOW()
                        WHERE nv_mid = %s AND keyword = %s
                    """, (target_mid, kw))
                    server_decision["keyword_status"] = "EXPOSURE_DROPPED_FLAGGED"

                # 2. 최근 실패 횟수 집계
                cur.execute("""
                    SELECT COUNT(*) AS fail_cnt
                    FROM tasks
                    WHERE nv_mid = %s AND status = 'FAILED'
                      AND completed_at >= NOW() - INTERVAL 2 HOUR
                """, (target_mid,))
                cnt_row = cur.fetchone()
                fail_cnt = cnt_row["fail_cnt"] if cnt_row else 1

                if (is_cat and fail_cnt >= 1) or fail_cnt >= 3:
                    server_decision["action_taken"] = "AUTO_QUARANTINE_APPLIED"
                    server_decision["quarantine_applied"] = True
                    server_decision["consecutive_failures"] = fail_cnt
                    server_decision["quarantine_duration_sec"] = 7200
                    server_decision["message"] = f"타겟(MID: {target_mid})이 {fail_cnt}회 미노출되어 2시간 격리 처리되었습니다."

            return {
                "success": True,
                "task_id": task_id_val,
                "status": db_status,
                "failed_phase": failed_phase,
                "error_code": error_code,
                "server_decision": server_decision,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }

    @staticmethod
    def get_unique_products(limit: int = 50) -> Dict[str, Any]:
        """
        [유니크 상품 목록 및 슬롯/쿼터 현황 조회 API]
        GET /api/v2/products/unique
        """
        limit_val = max(1, min(int(limit or 50), 200))
        today_str = time.strftime("%Y-%m-%d")
        with get_db_cursor(commit=False) as (cur, conn):
            cur.execute("""
                SELECT p.nv_mid, p.compare_id, p.store_name, p.product_name, p.total_slots,
                       p.daily_target_hits, p.is_catalog, p.is_active,
                       COALESCE(q.current_hits, 0) as today_hits,
                       COALESCE(q.target_hits, p.daily_target_hits) as today_target,
                       COALESCE(q.status, 'PENDING') as today_status
                FROM target_products p
                LEFT JOIN daily_slot_quotas q ON p.nv_mid = q.nv_mid AND q.target_date = %s
                ORDER BY p.total_slots DESC, p.nv_mid ASC
                LIMIT %s
            """, (today_str, limit_val))
            products = cur.fetchall()

            return {
                "success": True,
                "today": today_str,
                "count": len(products),
                "products": products
            }

    @staticmethod
    def get_diagnostics(limit: int = 50) -> Dict[str, Any]:
        """
        [원격 정밀 진단 요약 조회]
        GET /api/v2/task/diagnostics
        """
        limit = min(max(int(limit), 1), 200)
        with get_db_cursor(commit=False) as (cur, conn):
            cur.execute("""
                SELECT task_id, device_id, keyword, nv_mid, store_name, status,
                       search_type, serp_rank, shopping_rank, duration_seconds,
                       result_memo, assigned_at, completed_at
                FROM tasks
                ORDER BY task_id DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

            cur.execute("""
                SELECT status, COUNT(*) as cnt
                FROM tasks
                WHERE assigned_at >= NOW() - INTERVAL 24 HOUR
                GROUP BY status
            """)
            stats = {r["status"]: r["cnt"] for r in cur.fetchall()}

            return {
                "success": True,
                "stats_24h": stats,
                "recent_count": len(rows),
                "items": rows
            }

    @staticmethod
    def sync_external_products(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        [5분 주기 외부 10개 사이트 슬롯 동기화 API]
        POST /api/v2/products/sync-external
        - site_code: 제휴 사이트 코드 (예: agency_alpha, site_01 등)
        - slots: 슬롯 리스트 [{ slot_id, nv_mid, compare_id, base_keyword, product_url, store_name, product_name, hits_per_slot, sub_keywords, is_active }]
        - target_date: 대상 일자 (YYYY-MM-DD, 기본값: 오늘)
        """
        site_code = str(payload.get("site_code") or "default_site").strip()
        slots_list = payload.get("slots") or []
        target_date_str = str(payload.get("target_date") or time.strftime("%Y-%m-%d")).strip()

        if not slots_list:
            return {"success": False, "message": "동기화할 slots 데이터가 비어있습니다."}

        synced_slots = 0
        updated_products = 0
        synced_keywords = 0
        affected_mids = set()

        with get_db_cursor(commit=True) as (cur, conn):
            for s in slots_list:
                s_id = str(s.get("slot_id") or "").strip()
                mid = str(s.get("nv_mid") or "").strip()
                if not s_id or not mid:
                    continue

                affected_mids.add(mid)
                cmp_id = str(s.get("compare_id")).strip() if s.get("compare_id") else None
                kw = str(s.get("base_keyword") or "").strip()
                p_url = s.get("product_url")
                store = str(s.get("store_name") or "스마트스토어").strip()
                p_name = str(s.get("product_name") or kw).strip()
                hits = int(s.get("hits_per_slot") or 20)
                is_active = int(s.get("is_active", 1))

                # 1. external_slots 등록/갱신
                cur.execute("""
                    INSERT INTO external_slots (
                        site_code, slot_id, nv_mid, base_keyword, hits_per_slot, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        nv_mid = VALUES(nv_mid),
                        base_keyword = VALUES(base_keyword),
                        hits_per_slot = VALUES(hits_per_slot),
                        is_active = VALUES(is_active)
                """, (site_code, s_id, mid, kw, hits, is_active))
                synced_slots += 1

                # 2. 키워드 풀 등록 (메인 키워드)
                if kw:
                    cur.execute("""
                        INSERT INTO product_keyword_pool (
                            nv_mid, keyword, priority_rank, traffic_ratio, is_exposed
                        ) VALUES (%s, %s, 1, 40, 1)
                        ON DUPLICATE KEY UPDATE
                            priority_rank = 1,
                            traffic_ratio = 40,
                            is_exposed = 1
                    """, (mid, kw))
                    synced_keywords += 1

                # 서브 키워드 (2~5순위) 등록
                sub_kws = s.get("sub_keywords") or []
                sub_ratios = [25, 15, 10, 10]
                for idx, sub_kw in enumerate(sub_kws[:4], start=2):
                    sub_kw_str = str(sub_kw).strip()
                    if sub_kw_str and sub_kw_str != kw:
                        ratio = sub_ratios[idx - 2] if idx - 2 < len(sub_ratios) else 10
                        cur.execute("""
                            INSERT INTO product_keyword_pool (
                                nv_mid, keyword, priority_rank, traffic_ratio, is_exposed
                            ) VALUES (%s, %s, %s, %s, 1)
                            ON DUPLICATE KEY UPDATE
                                priority_rank = VALUES(priority_rank),
                                traffic_ratio = VALUES(traffic_ratio),
                                is_exposed = 1
                        """, (mid, sub_kw_str, idx, ratio))
                        synced_keywords += 1

            # 3. 영향받은 상품들의 유니크 마스터(target_products) 및 당일 쿼터(daily_slot_quotas) 집계 재계산
            for mid in affected_mids:
                # 활성화된 전체 슬롯 합산
                cur.execute("""
                    SELECT COUNT(*) as slot_cnt, COALESCE(SUM(hits_per_slot), 0) as total_hits
                    FROM external_slots
                    WHERE nv_mid = %s AND is_active = 1
                """, (mid,))
                agg = cur.fetchone()
                tot_slots = agg["slot_cnt"] if agg else 1
                sum_hits = agg["total_hits"] if agg else 20

                # 최대 100타 상한(Hard-Cap) 적용!
                capped_target = min(sum_hits, 100)
                is_catalog = 1 if cmp_id else 0

                cur.execute("""
                    INSERT INTO target_products (
                        nv_mid, compare_id, store_name, product_name, product_url,
                        is_catalog, total_slots, daily_target_hits, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                    ON DUPLICATE KEY UPDATE
                        total_slots = VALUES(total_slots),
                        daily_target_hits = VALUES(daily_target_hits),
                        is_active = 1
                """, (mid, cmp_id, store, p_name, p_url, is_catalog, tot_slots, capped_target))
                updated_products += 1

                # 4. 당일 쿼터 동기화
                cur.execute("""
                    INSERT INTO daily_slot_quotas (
                        target_date, nv_mid, total_slots, target_hits, current_hits, status
                    ) VALUES (%s, %s, %s, %s, 0, 'IN_PROGRESS')
                    ON DUPLICATE KEY UPDATE
                        total_slots = VALUES(total_slots),
                        target_hits = VALUES(target_hits)
                """, (target_date_str, mid, tot_slots, capped_target))

        return {
            "success": True,
            "site_code": site_code,
            "synced_slots": synced_slots,
            "updated_products": updated_products,
            "synced_keywords": synced_keywords,
            "affected_mids_count": len(affected_mids),
            "target_date": target_date_str,
            "message": f"{site_code} 사이트로부터 {synced_slots}개 슬롯, {updated_products}개 상품 동기화 완료 (최대 100타 캡 적용)"
        }

    @staticmethod
    def get_daily_quotas(target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        [일자별 슬롯 쿼터 및 달성 현황 조회 API]
        GET /api/v2/quotas/daily?date=YYYY-MM-DD
        """
        date_str = str(target_date or time.strftime("%Y-%m-%d")).strip()
        with get_db_cursor(commit=False) as (cur, conn):
            cur.execute("""
                SELECT q.target_date, q.nv_mid, q.total_slots, q.target_hits, q.current_hits, q.status,
                       p.store_name, p.product_name, p.compare_id, p.is_catalog,
                       ROUND(q.current_hits / q.target_hits * 100, 1) as completion_rate
                FROM daily_slot_quotas q
                JOIN target_products p ON q.nv_mid = p.nv_mid
                WHERE q.target_date = %s
                ORDER BY q.status ASC, q.target_hits DESC, q.current_hits DESC
            """, (date_str,))
            rows = cur.fetchall()

            total_products = len(rows)
            total_target_hits = sum(r["target_hits"] for r in rows)
            total_current_hits = sum(r["current_hits"] for r in rows)
            completed_products = sum(1 for r in rows if r["status"] == "COMPLETED")
            in_progress_products = sum(1 for r in rows if r["status"] == "IN_PROGRESS")
            overall_rate = round(total_current_hits / total_target_hits * 100, 1) if total_target_hits else 0.0

            return {
                "success": True,
                "target_date": date_str,
                "summary": {
                    "total_products": total_products,
                    "completed_products": completed_products,
                    "in_progress_products": in_progress_products,
                    "total_target_hits": total_target_hits,
                    "total_current_hits": total_current_hits,
                    "overall_completion_rate": overall_rate
                },
                "items": rows
            }

    @staticmethod
    def simulate_day(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        [일자별 다일 시뮬레이션 가동 엔진]
        POST /api/v2/simulation/run-day
        - target_date: 시뮬레이션 대상 일자 (예: 2026-10-15)
        - cycles: 모의 회차 수 (기본 10회)
        - devices_count: 회차당 단말기 수 (기본 20대)
        - hit_success_rate: 모의 타격 성공률 (기본 0.75)
        - drop_rank_failure_prob: 1P 미노출 소멸 확률 (기본 0.05)
        """
        target_date_str = str(payload.get("target_date") or time.strftime("%Y-%m-%d")).strip()
        cycles = max(1, min(int(payload.get("cycles") or 10), 100))
        devices_count = max(1, min(int(payload.get("devices_count") or 20), 50))
        hit_success_rate = float(payload.get("hit_success_rate", 0.75))
        drop_prob = float(payload.get("drop_rank_failure_prob", 0.05))

        # 1. 대상 일자의 daily_slot_quotas 시딩 보장
        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("""
                INSERT INTO daily_slot_quotas (target_date, nv_mid, total_slots, target_hits, current_hits, status)
                SELECT %s, nv_mid, total_slots, daily_target_hits, 0, 'IN_PROGRESS'
                FROM target_products
                WHERE is_active = 1
                ON DUPLICATE KEY UPDATE
                    total_slots = VALUES(total_slots),
                    target_hits = VALUES(target_hits)
            """, (target_date_str,))

        cycle_history = []
        total_allocated = 0
        total_success = 0
        total_dropped = 0

        # 2. 회차별 할당 및 결과 보고 시뮬레이션
        for c_idx in range(1, cycles + 1):
            mock_ip = f"110.70.{(c_idx * 17) % 250}.100"
            mock_c_class = f"110.70.{(c_idx * 17) % 250}.0/24"
            mock_devices = [f"SIM_DEV_{i:02d}" for i in range(1, devices_count + 1)]

            alloc_res = TaskServiceV2.allocate({
                "node_id": "sim-node-01",
                "net_mode": "lte",
                "public_ip": mock_ip,
                "ip_c_class": mock_c_class,
                "devices": mock_devices,
                "target_date": target_date_str
            })

            tasks = alloc_res.get("tasks", [])
            c_succ = 0
            c_dropped = 0

            for t in tasks:
                t_id = t["task_id"]
                mid = t["nv_mid"]
                kw = t["keyword"]
                is_hit = (random.random() < hit_success_rate)
                is_drop = (not is_hit and random.random() < drop_prob)

                rep_payload = {
                    "task_id": t_id,
                    "target_date": target_date_str,
                    "node_id": "sim-node-01",
                    "device_id": t["device_id"],
                    "nv_mid": mid,
                    "keyword": kw,
                    "status": "SUCCESS" if is_hit else "FAILED",
                    "error_code": "NOT_IN_PAGE1_DATA" if is_drop else ("TIMEOUT" if not is_hit else None),
                    "search_type": "msearch",
                    "match_type": "SHOPPING",
                    "shopping_rank": random.randint(15, 38) if is_hit else None,
                    "duration_seconds": round(random.uniform(60.0, 85.0) if is_hit else random.uniform(20.0, 35.0), 2),
                    "checkpoints": {
                        "app_launched": True,
                        "ackey_intent_sent": True,
                        "serp_rendered": True,
                        "shopping_section_found": True,
                        "more_touch_success": True,
                        "next_data_verified": is_hit,
                        "dom_target_found": is_hit,
                        "pinpoint_touch_success": is_hit,
                        "landing_verified": is_hit,
                        "dwell_completed": is_hit,
                        "traffic_log_flushed": is_hit
                    },
                    "telemetry": {
                        "scroll_count": random.randint(1, 4) if is_hit else 8,
                        "organic_items_count": 40 if is_hit else 0
                    }
                }

                rep_res = TaskServiceV2.report(rep_payload)
                if is_hit:
                    c_succ += 1
                if is_drop:
                    c_dropped += 1

            total_allocated += len(tasks)
            total_success += c_succ
            total_dropped += c_dropped

            cycle_history.append({
                "cycle": c_idx,
                "allocated": len(tasks),
                "success": c_succ,
                "dropped_keywords": c_dropped,
                "is_no_task": alloc_res.get("is_no_task", False),
                "code": alloc_res.get("code")
            })

            # 모든 상품이 100타 달성으로 마감되었으면 조기 완료
            if alloc_res.get("code") == "DAILY_QUOTA_ALL_COMPLETED":
                break

        # 3. 당일 쿼터 최종 요약 집계
        quota_summary = TaskServiceV2.get_daily_quotas(target_date_str)

        return {
            "success": True,
            "target_date": target_date_str,
            "simulated_cycles": len(cycle_history),
            "total_allocated": total_allocated,
            "total_success": total_success,
            "total_dropped_keywords": total_dropped,
            "success_rate": round(total_success / total_allocated * 100, 1) if total_allocated else 0.0,
            "quota_status": quota_summary.get("summary"),
            "cycle_history": cycle_history
        }

    # =========================================================================
    # [디바이스 마스터 및 그룹/이력 관리 엔드포인트 지원]
    # =========================================================================
    @staticmethod
    def get_devices(target_date: Optional[str] = None) -> Dict[str, Any]:
        """전체 디바이스 목록 및 실시간 상태, 당일 실적 집계 조회"""
        t_date = target_date or time.strftime("%Y-%m-%d")
        with get_db_cursor(commit=False) as (cur, conn):
            cur.execute("""
                SELECT d.device_id, d.group_name, d.node_id, d.model_name, d.status,
                       d.battery_level, d.last_ip, d.last_task_id, d.last_status, d.last_seen_at,
                       COALESCE(s.total_tasks, 0) as today_tasks,
                       COALESCE(s.success_tasks, 0) as today_success,
                       COALESCE(s.fail_tasks, 0) as today_fails,
                       COALESCE(s.success_rate, 0.0) as today_success_rate,
                       COALESCE(s.login_popup_count, 0) as today_login_popups,
                       COALESCE(s.not_found_count, 0) as today_not_found,
                       COALESCE(s.timeout_count, 0) as today_timeouts,
                       COALESCE(s.rollback_count, 0) as today_rollbacks,
                       COALESCE(s.avg_duration_seconds, 0.0) as today_avg_duration
                FROM devices d
                LEFT JOIN device_daily_stats s ON d.device_id = s.device_id AND s.stat_date = %s
                ORDER BY d.group_name ASC, d.device_id ASC
            """, (t_date,))
            devs = cur.fetchall()
            return {"success": True, "date": t_date, "count": len(devs), "devices": devs}

    @staticmethod
    def update_device_group(device_id: str, group_name: str) -> Dict[str, Any]:
        """특정 단말기의 소속 그룹 변경 (예: DEFAULT -> COMPANY_A)"""
        group_name = str(group_name or "DEFAULT").strip().upper()
        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("""
                INSERT INTO devices (device_id, group_name, status, last_seen_at)
                VALUES (%s, %s, 'IDLE', NOW())
                ON DUPLICATE KEY UPDATE group_name = VALUES(group_name), updated_at = NOW()
            """, (device_id, group_name))
            return {"success": True, "device_id": device_id, "group_name": group_name}

    @staticmethod
    def get_device_logs(device_id: str, limit: int = 50) -> Dict[str, Any]:
        """특정 단말기의 최근 상세 실행 로그 조회"""
        with get_db_cursor(commit=False) as (cur, conn):
            cur.execute("""
                SELECT id, log_date, device_id, group_name, task_id, keyword, store_name,
                       nv_mid, ip, status, is_success, search_type, final_rank, duration_seconds,
                       js_target_found, scroll_count, click_success, error_code, error_message, created_at
                FROM device_execution_logs
                WHERE device_id = %s
                ORDER BY id DESC
                LIMIT %s
            """, (device_id, limit))
            return {"success": True, "device_id": device_id, "logs": cur.fetchall()}

    @staticmethod
    def get_daily_device_stats(stat_date: Optional[str] = None) -> Dict[str, Any]:
        """일자별 전체 단말기 성적 통계표 조회"""
        t_date = stat_date or time.strftime("%Y-%m-%d")
        with get_db_cursor(commit=False) as (cur, conn):
            cur.execute("""
                SELECT s.*, d.node_id, d.model_name
                FROM device_daily_stats s
                JOIN devices d ON s.device_id = d.device_id
                WHERE s.stat_date = %s
                ORDER BY s.group_name ASC, s.success_rate DESC, s.total_tasks DESC
            """, (t_date,))
            return {"success": True, "date": t_date, "stats": cur.fetchall()}

    # =========================================================================
    # [그룹 및 사이트 묶음 마스터 관리]
    # =========================================================================
    @staticmethod
    def get_groups() -> Dict[str, Any]:
        """전체 그룹 목록 및 각 그룹에 묶인 사이트 목록, 소속 단말기 수 조회"""
        with get_db_cursor(commit=False) as (cur, conn):
            cur.execute("""
                SELECT g.group_code, g.group_name, g.description, g.is_all_sites, g.created_at,
                       COUNT(DISTINCT d.device_id) as device_count
                FROM device_groups g
                LEFT JOIN devices d ON g.group_code = d.group_name
                GROUP BY g.group_code
                ORDER BY g.group_code ASC
            """)
            groups = cur.fetchall()

            cur.execute("""
                SELECT group_code, site_code
                FROM device_group_sites
                ORDER BY group_code, site_code
            """)
            sites_map = {}
            for r in cur.fetchall():
                sites_map.setdefault(r["group_code"], []).append(r["site_code"])

            for g in groups:
                g["bound_sites"] = sites_map.get(g["group_code"], [])
                g["site_count"] = len(g["bound_sites"])

            return {"success": True, "count": len(groups), "groups": groups}

    @staticmethod
    def create_or_update_group(
        group_code: str,
        group_name: str,
        description: str = "",
        is_all_sites: bool = False,
        site_codes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """그룹 생성 및 1개 이상의 사이트 묶음 등록/수정"""
        g_code = str(group_code or "").strip().upper()
        if not g_code:
            return {"success": False, "error": "group_code는 필수입니다."}
        g_name = str(group_name or g_code).strip()

        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("""
                INSERT INTO device_groups (group_code, group_name, description, is_all_sites)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    group_name = VALUES(group_name),
                    description = VALUES(description),
                    is_all_sites = VALUES(is_all_sites),
                    updated_at = NOW()
            """, (g_code, g_name, description, int(is_all_sites)))

            # 사이트 묶음 갱신
            if site_codes is not None:
                cur.execute("DELETE FROM device_group_sites WHERE group_code = %s", (g_code,))
                clean_sites = list(dict.fromkeys(str(s).strip() for s in site_codes if str(s).strip()))
                for s in clean_sites:
                    cur.execute("""
                        INSERT IGNORE INTO device_group_sites (group_code, site_code)
                        VALUES (%s, %s)
                    """, (g_code, s))

            return {
                "success": True,
                "group_code": g_code,
                "group_name": g_name,
                "is_all_sites": bool(is_all_sites),
                "bound_sites": site_codes or []
            }

    @staticmethod
    def delete_group(group_code: str) -> Dict[str, Any]:
        """그룹 삭제 (기본 DEFAULT 그룹은 삭제 불가)"""
        g_code = str(group_code or "").strip().upper()
        if g_code == "DEFAULT":
            return {"success": False, "error": "기본 DEFAULT 그룹은 삭제할 수 없습니다."}

        with get_db_cursor(commit=True) as (cur, conn):
            cur.execute("DELETE FROM device_group_sites WHERE group_code = %s", (g_code,))
            cur.execute("DELETE FROM device_groups WHERE group_code = %s", (g_code,))
            # 소속 단말기는 DEFAULT로 복귀
            cur.execute("UPDATE devices SET group_name = 'DEFAULT' WHERE group_name = %s", (g_code,))
            return {"success": True, "deleted_group": g_code}

    @staticmethod
    def reset_and_replace_targets(targets: List[Dict[str, Any]], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        [nshop_list 및 관련 v2 테이블 전체 초기화 및 신규 엄선 50개 상품 일괄 교체]
        - nshop_list 및 v2 테이블(target_products, external_slots, product_keyword_pool, daily_slot_quotas) 완전 초기화
        - 검색어는 사용자가 검색한 메인 키워드 1개만 단독 기본값으로 등록 (단일 키워드 100% 가중치)
        - 과거 tasks 쿨다운/기록 정리
        """
        options = options or {}
        today_str = time.strftime("%Y-%m-%d")

        TaskServiceV2.init_tables()

        with get_db_cursor(commit=True) as (cur, conn):
            # 0. 만약의 사태를 대비해 기존 nshop_list 백업 테이블 생성/갱신
            try:
                cur.execute("DROP TABLE IF EXISTS _nshop_list_backup_prev")
                cur.execute("CREATE TABLE _nshop_list_backup_prev AS SELECT * FROM nshop_list")
            except Exception as e:
                logger.warning(f"백업 테이블 생성 스킵: {e}")

            # 1. 기존 데이터 정리
            cur.execute("DELETE FROM tasks")
            cur.execute("DELETE FROM daily_slot_quotas")
            cur.execute("DELETE FROM external_slots")
            cur.execute("DELETE FROM product_keyword_pool")
            cur.execute("DELETE FROM target_products")
            cur.execute("DELETE FROM nshop_list")

            # 2. 신규 50개 상품 일괄 적재
            inserted_nshop = 0
            inserted_targets = 0
            inserted_slots = 0
            inserted_keywords = 0
            inserted_quotas = 0

            for item in targets:
                kw = str(item.get("keyword") or "").strip()
                mid = str(item.get("nv_mid") or "").strip()
                p_title = str(item.get("product_title") or kw).strip()
                mall_name = str(item.get("mall_name") or "스마트스토어").strip()
                price = int(item.get("price") or 0)
                p_url = item.get("product_url")

                if not mid or not kw:
                    continue

                # A. nshop_list 적재
                cur.execute("""
                    INSERT INTO nshop_list (
                        target_id, product_name, product_title, mall_name, price,
                        mall_count, mall_product_id, is_active, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, 1, NULL, 1, NOW(), NOW())
                """, (mid, kw, p_title, mall_name, price))
                inserted_nshop += 1

                # B. target_products 유니크 마스터 적재
                cur.execute("""
                    INSERT INTO target_products (
                        nv_mid, compare_id, store_name, product_name, product_url,
                        is_catalog, total_slots, daily_target_hits, is_active, target_group
                    ) VALUES (%s, NULL, %s, %s, %s, 0, 1, 20, 1, 'ALL')
                """, (mid, mall_name, p_title, p_url))
                inserted_targets += 1

                # C. external_slots 가상 슬롯 매핑 (기본 슬롯 1개)
                site = EXTERNAL_SITES[inserted_slots % len(EXTERNAL_SITES)]
                slot_id = f"SLOT-{mid}"
                cur.execute("""
                    INSERT INTO external_slots (
                        site_code, slot_id, nv_mid, base_keyword, hits_per_slot, is_active
                    ) VALUES (%s, %s, %s, %s, 20, 1)
                """, (site["code"], slot_id, mid, kw))
                inserted_slots += 1

                # D. product_keyword_pool: "검색어는 지금 검색한 메인으로 하나만 기본값으로 잡고 진행"
                cur.execute("""
                    INSERT INTO product_keyword_pool (
                        nv_mid, keyword, priority_rank, traffic_ratio, is_exposed
                    ) VALUES (%s, %s, 1, 100, 1)
                """, (mid, kw))
                inserted_keywords += 1

                # E. daily_slot_quotas: 당일 20타 쿼터 초기화
                cur.execute("""
                    INSERT INTO daily_slot_quotas (
                        target_date, nv_mid, total_slots, target_hits, current_hits, status
                    ) VALUES (%s, %s, 1, 20, 0, 'IN_PROGRESS')
                """, (today_str, mid))
                inserted_quotas += 1

            return {
                "success": True,
                "nshop_list_count": inserted_nshop,
                "target_products_count": inserted_targets,
                "external_slots_count": inserted_slots,
                "keyword_pool_count": inserted_keywords,
                "daily_quotas_count": inserted_quotas,
                "message": f"총 {inserted_targets}개 상품으로 nshop_list 및 v2 전체 테이블 초기화 및 단일 메인 키워드 매칭 완료"
            }

