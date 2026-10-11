#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_v1/src/core/profile_generator.py

완전 무작위(Full Randomization) 식별자 및 대한민국 내륙 전역 좌표 생성 모듈
- 고정 패턴 및 인위적 접두사(smartuser_ 등) 100% 영구 제거
- 실제 한국인 구글 계정 이메일 패턴(이름, 이니셜, 일상단어, 생년, 월일, 숫자 조합) 무작위 생성
- 대한민국 전역 69개 주요 내륙 도시/상권/주거 거점 기반 + 현실적 미세 지터(Jitter) 부여 (수도권 편중 탈피)
- 현실적인 GPS 오차(Accuracy), 고도(Altitude), 방위각(Bearing) 동적 생성
- 네이버 자동완성 ackey 및 검색 파라미터(sm) 동적 다변화
"""

import random
import secrets
import uuid
import hashlib
import urllib.parse
from typing import Tuple, Dict, Any, Optional

# ---------------------------------------------------------------------------
# 1. 대한민국 내륙 전역 69대 주요 거점 좌표 (바다/도서 제외, 100% 육상 도시/상권)
# ---------------------------------------------------------------------------
INLAND_KOREA_HUBS = [
    # [수도권: 서울/경기/인천 - 20곳]
    (37.4979, 127.0276, "서울 강남구 역삼동"),
    (37.5710, 126.9769, "서울 종로구 청진동"),
    (37.5158, 126.9076, "서울 영등포구 문래동"),
    (37.5133, 127.1001, "서울 송파구 신천동"),
    (37.5563, 126.9226, "서울 마포구 서교동"),
    (37.6542, 127.0568, "서울 노원구 상계동"),
    (37.4852, 126.9015, "서울 구로구 구로동"),
    (37.2636, 127.0286, "경기 수원시 팔달구 인계동"),
    (37.3827, 127.1189, "경기 성남시 분당구 서현동"),
    (37.3219, 127.0957, "경기 용인시 수지구 풍덕천동"),
    (37.2006, 127.0722, "경기 화성시 반송동 동탄"),
    (37.0232, 127.0526, "경기 평택시 고덕동"),
    (37.3943, 126.9568, "경기 안양시 동안구 범계동"),
    (37.5034, 126.7660, "경기 부천시 원미구 중동"),
    (37.6584, 126.7699, "경기 고양시 일산동구 장항동"),
    (37.7381, 127.0436, "경기 의정부시 의정부동"),
    (37.6162, 127.1594, "경기 남양주시 다산동"),
    (37.7214, 126.7589, "경기 파주시 와동동 운정"),
    (37.4920, 126.7239, "인천 부평구 부평동"),
    (37.3929, 126.6392, "인천 연수구 송도동"),

    # [충청 내륙: 대전/세종/충북/충남 - 14곳]
    (36.3504, 127.3845, "대전 서구 둔산동"),
    (36.3622, 127.3563, "대전 유성구 봉명동"),
    (36.3276, 127.4273, "대전 중구 은행동"),
    (36.4880, 127.2605, "세종시 나성동"),
    (36.5042, 127.2652, "세종시 어진동"),
    (36.6358, 127.4914, "충북 청주시 상당구 북문로"),
    (36.6372, 127.4331, "충북 청주시 흥덕구 복대동"),
    (36.9706, 127.9381, "충북 충주시 성서동"),
    (37.1326, 128.2117, "충북 제천시 중앙로"),
    (36.8198, 127.1565, "충남 천안시 동남구 신부동"),
    (36.8151, 127.1065, "충남 천안시 서북구 불당동"),
    (36.7898, 127.0018, "충남 아산시 온천동"),
    (36.4606, 127.1312, "충남 공주시 신관동"),
    (36.2023, 127.0848, "충남 논산시 취암동"),

    # [강원 내륙: 춘천/원주/홍천/횡성 - 5곳]
    (37.8813, 127.7298, "강원 춘천시 온의동"),
    (37.3325, 127.9288, "강원 원주시 무실동"),
    (37.3242, 127.9785, "강원 원주시 반곡동 혁신도시"),
    (37.6970, 127.8887, "강원 홍천군 홍천읍"),
    (37.4918, 127.9851, "강원 횡성군 횡성읍"),

    # [전라 내륙: 광주/전북/전남 - 12곳]
    (35.1532, 126.8514, "광주 서구 치평동 상무지구"),
    (35.1485, 126.9156, "광주 동구 충장로"),
    (35.1925, 126.8247, "광주 광산구 수완동"),
    (35.8183, 127.1078, "전북 전주시 완산구 효자동"),
    (35.8564, 127.1214, "전북 전주시 덕진구 송천동"),
    (35.9555, 126.9634, "전북 익산시 영등동"),
    (35.9676, 126.7188, "전북 군산시 수송동"),
    (35.5768, 126.8582, "전북 정읍시 수성동"),
    (35.4164, 127.3905, "전북 남원시 도통동"),
    (34.9582, 127.5186, "전남 순천시 조례동"),
    (35.0238, 126.7865, "전남 나주시 빛가람동 혁신도시"),
    (34.9407, 127.6958, "전남 광양시 중동"),

    # [경상 내륙: 대구/부산/울산/경북/경남 - 18곳]
    (35.8690, 128.5960, "대구 중구 동성로"),
    (35.8586, 128.6253, "대구 수성구 범어동"),
    (35.8197, 128.5376, "대구 달서구 상인동"),
    (35.1578, 129.0592, "부산 부산진구 서면"),
    (35.1631, 129.1585, "부산 해운대구 우동"),
    (35.2052, 129.0785, "부산 동래구 온천동"),
    (35.5396, 129.3336, "울산 남구 삼산동"),
    (35.5539, 129.3214, "울산 중구 성남동"),
    (35.2215, 128.6811, "경남 창원시 성산구 상남동"),
    (35.2536, 128.6224, "경남 창원시 의창구 팔용동"),
    (35.2341, 128.8654, "경남 김해시 내외동"),
    (35.1802, 128.0628, "경남 진주시 평거동"),
    (36.1195, 128.3444, "경북 구미시 원평동"),
    (36.0089, 129.3323, "경북 포항시 남구 효자동"),
    (35.8562, 129.2158, "경북 경주시 황성동"),
    (36.5684, 128.6972, "경북 안동시 옥동"),
    (36.1264, 128.1824, "경북 김천시 율곡동 혁신도시"),
    (35.3211, 129.0118, "경남 양산시 물금읍"),
]

# ---------------------------------------------------------------------------
# 2. 한국인 실제 구글 이메일 어휘 사전 (인위적 패턴 100% 제거)
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "minjun", "jihoon", "seoyeon", "soobin", "junseo", "haeun", "yoonseo", "donghyun",
    "jihye", "hyunwoo", "sangmin", "taehyung", "eunji", "daehan", "jinwoo", "sohee",
    "minho", "junhyuk", "yujin", "chaewon", "sujin", "jaewon", "seunghyun", "jiwon",
    "doyoon", "siwoo", "hayoon", "minjae", "sungho", "bohyun", "yerin", "youngwoo",
    "minseok", "kyungsoo", "dongwook", "hyejin", "eunwoo", "sungmin", "jongwoo", "yuna",
    "junyoung", "junhyeok", "seojun", "subin", "jiwoo", "chaeyeon", "sohyun", "seungwoo"
]

LAST_NAMES = [
    "kim", "lee", "park", "choi", "jung", "kang", "cho", "yoon", "jang", "lim",
    "han", "oh", "seo", "shin", "kwon", "hwang", "ahn", "song", "jeon", "hong",
    "moon", "yang", "son", "bae", "baek", "heo", "yoo", "nam", "sim", "noh"
]

INITIALS = [
    "kdh", "yjh", "swlee", "jhk", "kms", "csh", "lsh", "pjm", "kth", "jhs",
    "pjh", "cjw", "kjw", "kmj", "ysh", "ljh", "hsy", "jwh", "smk", "yjs",
    "cys", "sjh", "kjs", "hjw", "dhk", "yjk", "jwl", "hwp"
]

ENGLISH_NAMES = [
    "alex", "david", "chris", "james", "sarah", "daniel", "jason", "michael",
    "eric", "kevin", "ryan", "sam", "brian", "jennifer", "grace", "clara",
    "lucas", "ethan", "olivia", "emma", "chloe", "justin", "andrew"
]

WORDS = [
    "sky", "blue", "cloud", "star", "moon", "sunny", "coffee", "latte", "music",
    "guitar", "flower", "breeze", "clover", "spring", "autumn", "river", "dream",
    "smile", "happy", "peace", "mint", "lemon", "shadow", "echo", "forest", "dawn",
    "wind", "melody", "note", "paper", "sketch", "orange", "berry", "space", "canvas"
]

SEPARATORS = ["", "", "", ".", "_"]


def generate_realistic_google_account() -> str:
    """
    인위적 패턴(smartuser_ 등)이 일절 없는 100% 자연스러운 한국인 실사용자 구글 이메일 생성
    """
    pattern_type = random.randint(1, 6)
    sep = random.choice(SEPARATORS)

    year_2d = f"{random.randint(80, 99) if random.random() < 0.6 else random.randint(0, 6):02d}"
    year_4d = str(random.randint(1982, 2004))
    m_d = f"{random.randint(1, 12):02d}{random.randint(1, 28):02d}"
    lucky_num = random.choice(["7", "77", "88", "99", "1004", "777", "123", "01"])
    rand_3d = str(random.randint(10, 999))
    num_suffix = random.choice([year_2d, year_4d, m_d, lucky_num, rand_3d])

    if pattern_type == 1:
        # 성 + 이름 + 숫자 (예: kimminjun94, lee_seoyeon02)
        last = random.choice(LAST_NAMES)
        first = random.choice(FIRST_NAMES)
        username = f"{last}{sep}{first}{num_suffix}"
    elif pattern_type == 2:
        # 이름 + 성 + 숫자 (예: minjun.kim1992, seoyeon_park77)
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        username = f"{first}{sep}{last}{num_suffix}"
    elif pattern_type == 3:
        # 이름 + 숫자/생일 (예: jiwon1024, doyoon0518)
        first = random.choice(FIRST_NAMES)
        username = f"{first}{sep}{num_suffix}"
    elif pattern_type == 4:
        # 이니셜 + 숫자 (예: jhk0415, kms9201, swlee1023)
        init = random.choice(INITIALS)
        username = f"{init}{num_suffix}"
    elif pattern_type == 5:
        # 영문명 + 성 + 숫자 (예: alex.kim89, david_lee94, chris.park01)
        eng = random.choice(ENGLISH_NAMES)
        last = random.choice(LAST_NAMES)
        username = f"{eng}{sep}{last}{num_suffix}"
    else:
        # 일상 단어 조합 + 숫자 (예: sunnyday88, bluemoon77, coffeetime91)
        w1 = random.choice(WORDS)
        w2 = random.choice(WORDS)
        while w2 == w1:
            w2 = random.choice(WORDS)
        if random.random() < 0.5:
            username = f"{w1}{sep}{w2}{random.choice([year_2d, lucky_num, ''])}"
        else:
            username = f"{w1}{num_suffix}"

    return f"{username}@gmail.com".lower()


def generate_inland_korea_coords() -> Tuple[float, float, str]:
    """
    대한민국 전역(수도권, 충청, 강원, 전라, 경상) 69개 주요 내륙 거점 중 하나를 무작위 선택하고
    현실적인 도심 반경 지터(약 200m~400m)를 부여하여 반환 (바다 빠짐 원천 차단)
    """
    base_lat, base_lng, region = random.choice(INLAND_KOREA_HUBS)
    lat_jitter = random.uniform(-0.0035, 0.0035)
    lng_jitter = random.uniform(-0.0035, 0.0035)
    return round(base_lat + lat_jitter, 6), round(base_lng + lng_jitter, 6), region


def generate_realistic_accuracy() -> float:
    """현실적인 모바일 하드웨어 GPS 오차범위 (3.5m ~ 9.5m 사이 랜덤)"""
    return round(random.uniform(3.5, 9.5), 1)


def generate_realistic_altitude() -> float:
    """대한민국 내륙 지형에 맞춘 현실적인 고도 (18.0m ~ 75.0m 사이 랜덤)"""
    return round(random.uniform(18.0, 75.0), 1)


def generate_realistic_bearing() -> float:
    """단말기 방위각 (0.0도 ~ 359.0도)"""
    return round(random.uniform(0.0, 359.0), 1)


def generate_random_ackey() -> str:
    """네이버 검색 자동완성 세션 키(ackey) 8자리 헥사 무작위 생성"""
    return secrets.token_hex(4)


def generate_random_search_sm() -> str:
    """네이버 검색 진입 방식(sm 파라미터) 자연스러운 다변화"""
    return random.choice(["mtp_sug.top", "mtp_sug.top", "mtp_sug", "mtp_hty.top"])


def build_intent_url(keyword: str, ackey: Optional[str] = None, sm: Optional[str] = None) -> str:
    """
    자연스러운 네이버 모바일 통합검색 인텐트 URL 생성
    - query: 타겟 키워드 인코딩
    - acq: 자동완성 프리픽스 모의 (첫 1단어 또는 앞 4글자)
    - ackey: 자동완성 세션 키
    - sm: 진입 경로 파라미터
    """
    query_clean = keyword.strip()
    words = query_clean.split()
    acq = words[0] if len(words) > 1 and len(words[0]) >= 2 else query_clean[:min(4, len(query_clean))]
    used_ackey = ackey or generate_random_ackey()
    used_sm = sm or generate_random_search_sm()
    acr = 1
    enc_query = urllib.parse.quote(query_clean)
    enc_acq = urllib.parse.quote(acq)
    return f"https://m.search.naver.com/search.naver?sm={used_sm}&where=m&query={enc_query}&ackey={used_ackey}&acq={enc_acq}&acr={acr}&qdt=0"


def generate_realistic_device_lifecycle() -> Tuple[int, int, int]:
    """
    현실적인 기기 설치/업데이트/부팅 타임스탬프 생성 (밀리초 단위)
    - fake_install_time: 15~45일 전 성숙된 설치 시점
    - fake_update_time: 설치 후 3~12일 뒤 업데이트 시점
    - fake_boot_time: 현재 기준 4~28시간 전 단말기 부팅 시점
    """
    import time
    now_ms = int(time.time() * 1000)
    install_offset_days = random.randint(15, 45)
    install_time = now_ms - (install_offset_days * 86400 * 1000) + random.randint(0, 3600000)
    update_offset_days = random.randint(3, 12)
    update_time = install_time + (update_offset_days * 86400 * 1000) + random.randint(0, 3600000)
    boot_offset_hours = random.randint(4, 28)
    boot_time = now_ms - (boot_offset_hours * 3600 * 1000) + random.randint(0, 1800000)
    return install_time, update_time, boot_time


def generate_fresh_session_profile() -> Dict[str, Any]:
    """
    매 타격마다 100% 독립적이고 패턴 없는 1회용 신규 프로필 종합 발급
    """
    fresh_ssaid = secrets.token_hex(8)
    fresh_dadd = str(uuid.uuid4())
    fresh_dadv = str(uuid.uuid4())
    fresh_napp_di = hashlib.md5(fresh_ssaid.encode("utf-8")).hexdigest()
    fresh_google_account = generate_realistic_google_account()
    fresh_lat, fresh_lng, fresh_region = generate_inland_korea_coords()
    fresh_acc = generate_realistic_accuracy()
    fresh_alt = generate_realistic_altitude()
    fresh_bearing = generate_realistic_bearing()
    fake_install, fake_update, fake_boot = generate_realistic_device_lifecycle()

    return {
        "ssaid": fresh_ssaid,
        "dadd": fresh_dadd,
        "dadv": fresh_dadv,
        "napp_di": fresh_napp_di,
        "google_account": fresh_google_account,
        "lat": fresh_lat,
        "lng": fresh_lng,
        "region": fresh_region,
        "accuracy": fresh_acc,
        "altitude": fresh_alt,
        "bearing": fresh_bearing,
        "fake_install_time": fake_install,
        "fake_update_time": fake_update,
        "fake_boot_time": fake_boot
    }

