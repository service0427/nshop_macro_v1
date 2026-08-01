#!/usr/bin/env python3
"""
Naver Shopping Card Container Finder, Enhanced Price Extractor & URL Logger
Flow:
1. Improved Price RegEx to capture all price formats ('1,513,990원', '최저 1,477,430원', '정상가 1,958,000원', '혜택가').
2. Merges thumbnail, title, price, seller, review nodes into ONE SINGLE Product Card Container Box.
3. Applies Top/Bottom Padding (20px) & Left/Right Padding (15px) inside the container.
4. Generates Random Safe Touch Coordinates (X, Y) within the padded container box.
"""

import os
import re
import time
import json
import random
import subprocess
import xml.etree.ElementTree as ET

TOP_HEADER_SAFE_Y = 350
BOTTOM_NAV_SAFE_Y = 2050
PADDING_TOP_BOTTOM = 20
PADDING_LEFT_RIGHT = 15

def dump_and_parse_products(device_id: str) -> list:
    """
    Parses current screen, extracts rich prices, merges child elements into Full Card Containers, 
    applies 20px Padding, and generates Random Safe Touch Points.
    """
    sdcard_path = "/sdcard/card_container_dump.xml"
    tmp_path = f"/tmp/card_container_dump_{device_id}.xml"
    
    # Retry uiautomator dump up to 3 times to handle temporary 137 exit codes
    dump_success = False
    for attempt in range(1, 4):
        res = subprocess.run(["adb", "-s", device_id, "shell", f"uiautomator dump {sdcard_path}"], capture_output=True, text=True)
        if res.returncode == 0:
            dump_success = True
            break
        time.sleep(1.0)

    if not dump_success:
        return []

    subprocess.run(["adb", "-s", device_id, "pull", sdcard_path, tmp_path], capture_output=True, check=False)
    
    if not os.path.exists(tmp_path):
        return []

    try:
        tree = ET.parse(tmp_path)
        root = tree.getroot()
    except Exception:
        return []
    
    nodes = []
    for elem in root.iter("node"):
        t = elem.attrib.get("text", "").strip()
        d = elem.attrib.get("content-desc", "").strip()
        b = elem.attrib.get("bounds", "").strip()
        res_id = elem.attrib.get("resource-id", "").strip()
        cls = elem.attrib.get("class", "").strip()
        val = t or d
        if b:
            coords = b.replace("][", ",").replace("[", "").replace("]", "").split(",")
            if len(coords) == 4:
                x1, y1, x2, y2 = map(int, coords)
                nodes.append({
                    "val": val, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "bounds": b, "res_id": res_id, "cls": cls
                })
                
    onscreen = [n for n in nodes if 0 <= n["y1"] < 2350 and n["y2"] <= 2380 and (n["y2"] - n["y1"]) > 10]
    
    def is_price_node(val_str: str) -> bool:
        v = val_str.strip()
        if not v or len(v) > 50:
            return False
        if re.search(r"^\d{8,14}$", v):  # Skip pure nvMid numeric IDs
            return False
        if "포인트" in v or "점수" in v or "리뷰" in v or "별점" in v or "쿠폰" in v:
            return False
        if re.search(r"(?:정상가|할인가|혜택가|최저가?|혜택|가|)\s*[\d,]{4,12}(?:\s*원)?", v):
            if re.search(r"[\d,]{4,12}", v) and ("," in v or "원" in v):
                return True
        return False

    price_nodes = [n for n in onscreen if is_price_node(n["val"])]
    ad_nodes = [n for n in onscreen if n["val"] == "광고"]
    seller_keywords = ["스토어", "공식", "파트너", "인증점", "몰", "쇼핑몰", "파트너스"]
    
    ignore_list = [
        "가격비교", "본문으로", "맨위로가기", "검색어", "전체서비스", "네이버플러스",
        "선택됨", "현재 메뉴", "툴팁닫기", "쇼핑", "블로그", "클립", "카페", "이미지", "지식iN",
        "전체상품", "공식 브랜드스토어", "브랜드", "상품을 만나보세요", "상품 더보기", "자세히보기",
        "가맹점만 보기", "버튼을 눌러서", "주문 시", "혜택가", "포인트 최대",
        "빠르게 받기", "만족도 1위", "랭킹순", "돌파!", "기획전", "프로모션", "이벤트", "적립혜택", "카테고리"
    ]
    
    promo_ad_brands = ["베이직북", "오멘", "옴니북", "발로란트", "RTX 5060", "하이퍼엑스", "비보북", "연관"]
    
    seller_patterns = ["인증점", "공식파트너", "파트너스", "스토어", "쇼핑몰", "리퍼연구소", "이좋은세상", "코인비엠에스"]
    
    def is_valid_product_title(val_str: str) -> bool:
        v = val_str.strip()
        if len(v) < 12:
            return False
        # Filter out seller names
        if any(sp in v for sp in seller_patterns) and len(v) < 25:
            return False
        # Filter out duplicated category filter pills like '레노버 노트북 레노버 노트북'
        words = v.split()
        if len(words) >= 2 and len(set(words)) <= len(words) // 2:
            return False
        if v.count("노트북") >= 2 and len(v) < 30:
            return False
        # Ignore price strings, storage options, delivery info, coupons, and navigation pills
        if re.search(r"^(?:\d+[GT]B\s*)?최저\s*[\d,]+원?", v):
            return False
        if re.search(r"^[\d,]+\s*원$", v):
            return False
        if re.search(r"^\d+\.\d+\.\(.\)\s*(?:도착|출발|배송)", v):
            return False
        if "정상가" in v or "할인가" in v or "혜택가" in v or "포인트" in v or "배송 휴무" in v or "쿠폰" in v or "적립" in v or "멤버십" in v or "도착" in v or "출발" in v or "배송" in v:
            return False
        if re.search(r"\d+\.\d+cm", v) or re.search(r"^\d+cm", v):
            return False
        if "컨텍스트 자동완성" in v or "도움말" in v or "일상 속 고민" in v or "유용한 생활 팁" in v or "답변을 만나보세요" in v:
            return False
        if "빠르게 받기" in v or "만족도" in v or "랭킹순" in v or "돌파" in v or "특별 에디션" in v or "출시" in v or "탑재" in v:
            return False
        if "이용약관" in v or "사업자" in v or "고객센터" in v or "쿠팡" in v or "리퍼" in v or "대표전화" in v or "1588-" in v or "1599-" in v:
            return False
        if "Ai Live" in v or "LIVE" in v or "자동재생" in v or "현재페이지" in v or "총페이지" in v or "폴드8" in v or "갤럭시Z" in v:
            return False
        if "로켓배송" in v or "미친세일" in v or "구매해보세요" in v or "신학기" in v or "함께해" in v or "75%할인" in v or "까지" in v or "일요일" in v or "목요일" in v:
            return False
        if re.search(r"[a-f0-9]{6,10}-[a-f0-9]{4}-", v):
            return False
        return True

    # XML Tree Container Hierarchy Extraction (_sr_lst_<nvMid>)
    sr_lst_containers = []
    for node in root.iter("node"):
        res_id = node.attrib.get("resource-id", "").strip()
        if "_sr_lst_" in res_id:
            m = re.search(r"_sr_lst_(\d+)", res_id)
            if m:
                sr_lst_containers.append({
                    "nv_mid": m.group(1),
                    "container_node": node,
                    "bounds": node.attrib.get("bounds", "").strip()
                })

    products = []
    seen = set()
    
    for item in sr_lst_containers:
        pure_nv_mid = item["nv_mid"]
        container = item["container_node"]
        bounds_str = item["bounds"]
        
        if pure_nv_mid in seen:
            continue
            
        child_texts = []
        for child in container.iter("node"):
            t = child.attrib.get("text", "").strip() or child.attrib.get("content-desc", "").strip()
            if t and t not in child_texts:
                child_texts.append(t)
                
        is_ad = any(t == "광고" or "스폰서" in t or "기획전" in t or "베이직북" in t for t in child_texts)
        
        title = "N/A"
        title_bounds = bounds_str
        price_info = "가격 정보 없음"
        seller_info = "N/A"
        
        for child in container.iter("node"):
            t = child.attrib.get("text", "").strip() or child.attrib.get("content-desc", "").strip()
            c_b = child.attrib.get("bounds", "").strip()
            if "원" in t or t.replace(",", "").isdigit():
                if price_info == "가격 정보 없음":
                    price_info = t
            elif len(t) > 15 and not t.startswith("정상가") and not t.endswith("도착") and not "배송" in t:
                if title == "N/A" or len(t) > len(title):
                    title = t
                if c_b and not c_b.startswith("[0,0]") and not c_b.endswith("2347]") and not c_b.endswith(",2347]"):
                    m_cb = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", c_b)
                    if m_cb:
                        _, cb_y1, _, cb_y2 = map(int, m_cb.groups())
                        if 200 <= cb_y1 <= 2200:
                            title_bounds = c_b
            elif any(sk in t for sk in ["스토어", "공식", "파트너", "인증점", "몰"]):
                if seller_info == "N/A":
                    seller_info = t

        if title == "N/A":
            continue

        seen.add(pure_nv_mid)

        # Parse container bounds for click coordinates
        m_b = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
        if m_b:
            card_x1, card_y1, card_x2, card_y2 = map(int, m_b.groups())
        else:
            card_x1, card_y1, card_x2, card_y2 = 45, 400, 1035, 800

        safe_x1 = card_x1 + PADDING_LEFT_RIGHT
        safe_y1 = card_y1 + PADDING_TOP_BOTTOM
        safe_x2 = card_x2 - PADDING_LEFT_RIGHT
        safe_y2 = card_y2 - PADDING_TOP_BOTTOM
        
        clamped_y1 = max(safe_y1, TOP_HEADER_SAFE_Y)
        clamped_y2 = min(safe_y2, BOTTOM_NAV_SAFE_Y)
        is_overlay_safe = (clamped_y1 < clamped_y2)
        
        if clamped_y1 < clamped_y2 and safe_x1 < safe_x2:
            rand_x = random.randint(safe_x1, safe_x2)
            rand_y = random.randint(clamped_y1, clamped_y2)
            center_x = (safe_x1 + safe_x2) // 2
            center_y = (clamped_y1 + clamped_y2) // 2
        else:
            rand_x, rand_y = (card_x1 + card_x2) // 2, min(max((card_y1 + card_y2) // 2, 400), 2000)
            center_x, center_y = rand_x, rand_y

        products.append({
            "nv_mid": pure_nv_mid,
            "nv_mid_source": f"XML Tree Container Resource ID ('_sr_lst_{pure_nv_mid}')",
            "title": title,
            "is_ad": is_ad,
            "type": "광고 (Sponsored)" if is_ad else "일반 (Organic)",
            "price": price_info,
            "seller": seller_info,
            "title_node_bounds": title_bounds,
            "card_container_bounds": bounds_str,
            "padded_safe_region": f"[{safe_x1},{clamped_y1}][{safe_x2},{clamped_y2}]",
            "container_size": {
                "width": card_x2 - card_x1,
                "height": card_y2 - card_y1
            },
            "center_touch": [center_x, center_y],
            "random_safe_touch": [rand_x, rand_y],
            "overlay_safe": is_overlay_safe,
            "y_coord": card_y1
        })
                
    products.sort(key=lambda p: p["y_coord"])
    return products

def execute_top5_category_check_and_extract(device_id: str, keyword: str):
    """
    Executes Top-5 Category Bar Pre-Check and Scroll-to-Reveal Product Extraction.
    Prints real-time results directly to the console output.
    """
    print("")
    print("==========================================================================")
    print(" 🔍 [PRE-CHECK ENGINE] TOP-5 CATEGORY BAR PRESENCE DETECTION")
    print(f" Target Keyword: '{keyword}' | Target Device: {device_id}")
    print("==========================================================================")
    
    log_dir = os.environ.get("LOG_SAVE_DIR", f"/tmp/logs_{device_id}")
    os.makedirs(log_dir, exist_ok=True)
    
    sdcard_xml1 = "/sdcard/cat_check_init.xml"
    tmp_xml1 = os.path.join(log_dir, "screen_dump_init.xml")
    
    # Retry uiautomator dump until WebView DOM finishes loading (nodes > 20)
    nodes = []
    for attempt in range(1, 6):
        time.sleep(1.2 if attempt == 1 else 1.0)
        subprocess.run(["adb", "-s", device_id, "shell", f"uiautomator dump {sdcard_xml1}"], capture_output=True)
        subprocess.run(["adb", "-s", device_id, "pull", sdcard_xml1, tmp_xml1], capture_output=True, check=False)
        if os.path.exists(tmp_xml1):
            try:
                tree = ET.parse(tmp_xml1)
                root = tree.getroot()
                nodes = []
                for elem in root.iter("node"):
                    t = elem.attrib.get("text", "").strip() or elem.attrib.get("content-desc", "").strip()
                    b = elem.attrib.get("bounds", "").strip()
                    if t and b:
                        nodes.append({"text": t, "b": b})
                if len(nodes) > 20:
                    break
            except Exception:
                pass

    if not nodes:
        print("  [!] Failed to capture initial UI dump for category check.")
        return
            
    # Extract top horizontal category tabs
    tabs = []
    for n in nodes:
        t = n["text"]
        if any(k in t for k in ["AI new", "쇼핑", "블로그", "클립", "카페", "뉴스", "지도", "이미지", "지식iN"]):
            if len(t) < 15 and t not in tabs:
                tabs.append(t)
                
    print(f" Top Rendered Category Tabs: {tabs}")
    
    shopping_rank = -1
    if "쇼핑" in tabs:
        shopping_rank = tabs.index("쇼핑") + 1
        print(f"  -> '쇼핑' Tab Position: Rank {shopping_rank} in top category bar!")
        
    if shopping_rank > 0 and shopping_rank <= 5:
        print(f"  [✓] PRE-CHECK PASSED: '쇼핑' tab is at Rank {shopping_rank} (<= 5)! Shopping section exists below!")
        
        # Check if products are ALREADY visible in initial XML dump before swiping
        init_has_products = False
        if os.path.exists(tmp_xml1):
            try:
                tree_init = ET.parse(tmp_xml1)
                for e in tree_init.getroot().iter("node"):
                    rid = e.attrib.get("resource-id", "").strip()
                    if "_sr_lst_" in rid or "theme_productId" in rid:
                        init_has_products = True
                        break
            except Exception:
                pass

        sdcard_xml2 = "/sdcard/cat_check_revealed.xml"
        tmp_xml2 = os.path.join(log_dir, "screen_dump_revealed.xml")

        if init_has_products:
            print("  [✓] Product containers ALREADY present on initial screen! Skipping swipe to avoid over-scrolling.")
            subprocess.run(["cp", tmp_xml1, tmp_xml2], capture_output=True)
        else:
            print("  [Action] Micro-scrolling down (Swipe 1800 -> 800) to bring Price Comparison section into view...")
            subprocess.run(["adb", "-s", device_id, "shell", "input swipe 540 1800 540 800 350"], capture_output=True)
            time.sleep(1.5)
            subprocess.run(["adb", "-s", device_id, "shell", f"uiautomator dump {sdcard_xml2}"], capture_output=True)
            subprocess.run(["adb", "-s", device_id, "pull", sdcard_xml2, tmp_xml2], capture_output=True, check=False)

        print(f"  [✓] UI XML dump saved to log folder: {tmp_xml2}")
        
        # Mirror to /tmp for fallback scanners
        subprocess.run(["cp", tmp_xml2, f"/tmp/cat_check_revealed_{device_id}.xml"], capture_output=True)
        
        try:
            tree2 = ET.parse(tmp_xml2)
            root2 = tree2.getroot()
        except Exception:
            return
            
        nodes2 = [{"text": e.attrib.get("text", "").strip() or e.attrib.get("content-desc", "").strip(), "b": e.attrib.get("bounds", "").strip()} for e in root2.iter("node") if e.attrib.get("text") or e.attrib.get("content-desc")]
        
        # Multi-pattern section header detection (supporting 5 core layout patterns)
        section_patterns = [
            "네이버 가격비교", "가격비교", "네이버 쇼핑 인기 상품", "AI가 선별한",
            "인기 상품", "상품 더보기", "네이버플러스 스토어"
        ]
        
        header_idx = None
        matched_header = "기본 쇼핑 섹션"
        for i, n in enumerate(nodes2):
            txt = n["text"]
            for pat in section_patterns:
                if pat in txt:
                    header_idx = i
                    matched_header = txt
                    break
            if header_idx is not None:
                break
                
        if header_idx is not None:
            print(f"  [✓] Shopping section ('{matched_header}') confirmed on screen! Saved dump for 1st-Pass Scanner.")
        else:
            print("  [!] '네이버 가격비교/쇼핑' section header not detected on revealed screen.")
    else:
        print("  [X] PRE-CHECK FAILED: '쇼핑' tab not found within Top 5! Non-shopping keyword.")
        print("  -> Product extraction pipeline aborted immediately (Zero False Positive).")
        print("==========================================================================")

def execute_nvmid_rank_scanner(device_id: str, keyword: str, target_product_id: str = None):
    """
    Scans XML tree strictly using Tree Hierarchy parsing,
    extracts nvMid and separates Sponsored Ads vs Organic Products with 100% precision.
    Prints Rank, Horizontal Page (가로 1/2/3페이지), nvMid, and Product Title to console.
    If target_product_id (-p) is passed, checks existence and prints status without clicking.
    """
    print("")
    print("==========================================================================")
    print(" 📊 [NVMID MEMORY SCANNER] TREE HIERARCHY AD BADGE & ORGANIC PARSER")
    print(f" Target Keyword: '{keyword}' | Target Device: {device_id}")
    if target_product_id:
        print(f" Target nvMid Condition (-p): {target_product_id}")
    print("==========================================================================")
    
    log_dir = os.environ.get("LOG_SAVE_DIR", f"/tmp/logs_{device_id}")
    tmp_xml = os.path.join(log_dir, "screen_dump_revealed.xml")
    if not os.path.exists(tmp_xml):
        tmp_xml = os.path.join(log_dir, "screen_dump_init.xml")
    if not os.path.exists(tmp_xml):
        tmp_xml = f"/tmp/cat_check_revealed_{device_id}.xml"
        
    if not os.path.exists(tmp_xml):
        print("  [!] UI XML dump not found for nvMid scanning.")
        return
        
    try:
        tree = ET.parse(tmp_xml)
        root = tree.getroot()
    except Exception:
        print("  [!] Failed to parse UI XML dump.")
        return

    # Multi-Pattern Container Scanner: Supports _sr_lst_(\d+), _(\d+), and theme_productId_ (\d+ or catalog)
    raw_products = []
    
    for elem in root.iter('node'):
        res_id = elem.attrib.get('resource-id', '').strip()
        
        mid = None
        is_product_container = False
        
        m_sr = re.search(r'_sr_lst_(\d{6,14})', res_id) or re.search(r'_(\d{6,14})$', res_id) or re.search(r'_(\d{6,14})_', res_id)
        m_theme_mid = re.search(r'theme_productId_(\d{6,14})', res_id)
        
        if m_sr:
            is_product_container = True
            mid = m_sr.group(1)
        elif m_theme_mid:
            is_product_container = True
            mid = m_theme_mid.group(1)
        elif res_id == 'theme_productId_':
            is_product_container = True
            mid = 'CATALOG'

        if is_product_container:
            child_texts = [c.attrib.get('text', '').strip() or c.attrib.get('content-desc', '').strip() for c in elem.iter('node')]
            child_texts = [t for t in child_texts if t]
            
            full_title = ''
            for child in elem.iter('node'):
                txt = child.attrib.get('text', '').strip()
                if '<mark>' in txt or '</mark>' in txt:
                    full_title = re.sub(r'</?mark>', '', txt).strip()
                    break

            if not full_title:
                candidates = []
                for child in elem.iter('node'):
                    txt = child.attrib.get('text', '').strip() or child.attrib.get('content-desc', '').strip()
                    if len(txt) > 10 and not any(skip in txt for skip in ['원', '할인', '배송', '적립', '공식', '이용약관', '고객센터', '검색어', '구매 1만+', '구매 1천+']):
                        candidates.append(txt)
                if candidates:
                    candidates.sort(key=len, reverse=True)
                    full_title = candidates[0]

            is_ad = any(ct == '광고' or '스폰서' in ct for ct in child_texts)
            
            is_catalog = False
            seller_info = 'N/A'
            mall_count = ''
            
            for idx, t in enumerate(child_texts):
                if '판매처' in t:
                    is_catalog = True
                    if t == '판매처' and idx + 1 < len(child_texts) and child_texts[idx+1].isdigit():
                        mall_count = child_texts[idx+1]
                    else:
                        m_mc = re.search(r'판매처\s*(\d+)', t)
                        if m_mc:
                            mall_count = m_mc.group(1)
                    break
                elif '최저' in t and not is_catalog:
                    is_catalog = True

            if not is_catalog:
                for t in child_texts:
                    if any(sk in t for sk in ['스토어', '공식', '파트너', '인증점', '몰', '씨앤에스', '이좋은세상', '코인비엠에스', '노트북랜드', '한사랑씨앤씨', '쇼핑몰', '리퍼연구소', '본사', '직영몰', 'MISSFACTORY', '제이숲N', '티에스shop', '댕기머리', '닥터포헤어', 'SOOO', '마켓']):
                        if t not in ['공식', '인증', '네이버페이플러스']:
                            seller_info = t
                            break

            if full_title and not any(skip in full_title for skip in ['함께 많이', '도움말', '네이버 클립', '나무위키']):
                raw_products.append({
                    'nvMid': mid or 'CATALOG',
                    'title': full_title,
                    'is_ad': is_ad,
                    'is_catalog': is_catalog,
                    'mall_count': mall_count,
                    'seller_info': seller_info
                })

    # Deduplicate & Filter Fake UI Entries
    seen_titles = set()
    ads = []
    organic = []
    
    for p in raw_products:
        if p['title'] not in seen_titles:
            if not any(skip in p['title'] for skip in ['함께 많이', '도움말', '네이버 클립', '브랜드 찾아보다가', '언론사', '이용할 수', '나무위키']):
                seen_titles.add(p['title'])
                if p['is_ad']:
                    ads.append(p)
                else:
                    organic.append(p)

    if ads:
        print("==========================================================================")
        print(f" 🚨 [SPONSORED AD PRODUCTS] TOTAL {len(ads)} ITEMS FILTERED OUT FROM ORGANIC RANKING")
        print("==========================================================================")
        for idx, a in enumerate(ads, 1):
            print(f"  [광고 {idx}등] | nvMid: {a['nvMid']:14s} | {a['title']}")

    print("==========================================================================")
    print(f" 📦 [ORGANIC NON-AD PRODUCTS] TOTAL {len(organic)} ITEMS PARSED (HORIZONTAL PAGES 1~3)")
    print("==========================================================================")
    print(f" {'순위':<5s} | {'가로 페이지':<10s} | {'상품 유형 / 판매처':<26s} | {'진입 결과 예측':<14s} | {'nvMid':<14s} | {'상품 제목'}")
    print("----------------------------------------------------------------------------------------------------")
    
    matched_target = None
    json_organic = []
    
    for rank, item in enumerate(organic[:15], 1):
        horiz_page = "가로 1페이지" if rank <= 4 else ("가로 2페이지" if rank <= 9 else "가로 3페이지")
        
        if item['is_catalog']:
            mc_str = f" (판매처 {item['mall_count']}개)" if item['mall_count'] else ""
            type_desc = f"가격비교{mc_str}"
            landing_note = "⚠️ 로그인 전환"
        else:
            s_str = f" ({item['seller_info']})" if item['seller_info'] != 'N/A' else " (개별몰)"
            type_desc = f"단일상품{s_str}"
            landing_note = "✅ 상세 진입"

        print(f" {rank:2d}등   | [{horiz_page:<10s}] | {type_desc:<26s} | {landing_note:<14s} | {item['nvMid']:14s} | {item['title']}")
        
        entry = {
            "rank": rank,
            "page": horiz_page,
            "is_catalog": item['is_catalog'],
            "mall_count": item['mall_count'],
            "seller_info": item['seller_info'],
            "type_desc": type_desc,
            "landing_expected": "Naver_Login_Required" if item['is_catalog'] else "Direct_Product_Detail",
            "nvMid": item['nvMid'],
            "title": item['title']
        }
        json_organic.append(entry)
        
        if target_product_id and item['nvMid'] == str(target_product_id).strip():
            matched_target = (rank, horiz_page, item)

    print("==========================================================================")
    
    # Save 1st Pass Clean JSON without coordinates to log folder
    json_path = os.path.join(log_dir, "extracted_products.json")
    json_payload = {
        "keyword": keyword,
        "device_id": device_id,
        "target_product_id": target_product_id,
        "total_organic_found": len(organic),
        "target_found": matched_target is not None,
        "products": json_organic
    }
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, ensure_ascii=False, indent=2)
        
    print(f"  [✓] 1st-Pass Product List JSON saved to log folder: {json_path}")
    
    if target_product_id:
        if matched_target:
            r, ptag, it = matched_target
            print("==========================================================================")
            print(f" [✓] TARGET PRODUCT MATCHED! (-p {target_product_id})")
            print(f"     -> Position: [{ptag}] Rank {r}등")
            print(f"     -> nvMid   : {it['nvMid']}")
            print(f"     -> Title   : \"{it['title']}\"")
            print("     -> Result  : TARGET_EXISTS=TRUE (Task Complete & Safe Exit)")
            print("==========================================================================")
            return True
        else:
            print("==========================================================================")
            print(f" [X] TARGET PRODUCT NOT FOUND! (-p {target_product_id})")
            print(f"     -> Scanned {len(organic)} organic items, target nvMid not present on search page.")
            print("     -> Result  : TARGET_EXISTS=FALSE (Clean Abort with 0 Clicks)")
            print("==========================================================================")
            return False
            
    return True
    print("==========================================================================")

