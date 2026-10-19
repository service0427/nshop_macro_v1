#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/pipeline/executor.py

Master Pipeline Coordinator (Modular & Streamlined)
Sequentially executes the 5 discrete stages:
1. Clean Launcher (step1_launcher)
2. SERP Exploration & Fast-Fail (step2_serp)
3. 50:50 Shop Navigation (step3_shop_nav)
4. Shopping Tab NEXT_DATA Strike (step4_shop)
5. Landing Verification & Dwell (step5_landing)
"""

import time
import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from config.settings import LOGS_DIR, PROJECT_ROOT as ROOT_DIR, TIMINGS
from src.pipeline.models import TaskInput, TaskResult, get_cdp_port, save_task_history
from src.device.device_selector import select_device
from src.device.adb_controller import force_stop_app, start_intent
from src.core.nnb_provider import get_nnb_packet
from src.core.profile_generator import generate_fresh_session_profile, build_intent_url
from src.device.identity_auditor import IdentityAuditor
from src.core.traffic_logger import TrafficAuditLogger

from src.pipeline.steps.step1_launcher import launch_app_and_connect_cdp
from src.pipeline.steps.step2_serp import execute_serp_stage
from src.pipeline.steps.step3_shop_nav import execute_shop_navigation
from src.pipeline.steps.step4_shop import execute_shopping_stage
from src.pipeline.steps.step5_landing import execute_landing_and_dwell
from src.pipeline.steps.step6_catalog import execute_catalog_stage
from src.monitor.fleet_state import FleetStateManager
from src.monitor.search_block_auditor import record_ip_access

logger = logging.getLogger("ConveyorExecutor")


async def execute_task_pipeline(task: TaskInput) -> Dict[str, Any]:
    """
    Modular execution pipeline coordinator.
    """
    start_time = time.time()
    task.task_start_time = start_time
    result = TaskResult(
        task_id=task.task_id,
        keyword=task.keyword,
        nv_mid=task.nv_mid,
        compare_id=task.compare_id,
        raw_keyword=task.raw_keyword,
        node_id=getattr(task, "node_id", "node-default"),
        ip_c_class=getattr(task, "ip_c_class", None)
    )
    result.store_name = task.store_name
    result.dwell_seconds = task.dwell_seconds
    result.ip = getattr(task, "ip", "unknown") or "unknown"

    # 1. Device Selection & CDP Port
    try:
        device_id = select_device(task.device_id)
        result.device_id = device_id
        cdp_port = get_cdp_port(device_id)
    except Exception as e:
        result.status = "DEVICE_SELECTION_FAILED"
        result.error_message = str(e)
        result.duration_seconds = time.time() - start_time
        return result.to_dict()

    # 2. NNB Acquisition
    if task.nnb:
        nnb_packet = {"nnb": task.nnb, "buc": task.buc or "", "source": "task_assign"}
        logger.info(f"🔑 [NNB 할당] 작업 할당 NNB 직접 사용: {task.nnb}")
    else:
        nnb_packet = get_nnb_packet(device_id=device_id, use_remote=task.use_remote_nnb, force_refresh=True)
    result.nnb = nnb_packet.get("nnb", "")

    # 3. Profile & Identity Integrity Audit
    profile = task.profile if (hasattr(task, "profile") and task.profile) else generate_fresh_session_profile()
    auditor = IdentityAuditor()
    identity_packet = {
        "ssaid": profile["ssaid"],
        "napp_di": profile.get("napp_di") or hashlib.md5(profile["ssaid"].encode("utf-8")).hexdigest(),
        "nnb": result.nnb,
        "nnb_age_seconds": int(nnb_packet.get("age_seconds", 0)),
        "buc": nnb_packet.get("buc", ""),
        "dadd": profile["dadd"],
        "dadv": profile["dadv"],
        "lat": profile["lat"],
        "lng": profile["lng"],
        "region": profile.get("region", "대한민국"),
        "google_account": profile["google_account"],
        "ip": result.ip
    }
    is_valid, audit_summary, table_text = auditor.audit_and_record(device_id, identity_packet)
    if not is_valid:
        logger.critical(f"🚨 [식별자 충돌 감지!] 직전 회차와 동일 식별자 검출로 중단\n{table_text}")
        result.status = "IDENTITY_COLLISION"
        result.error_message = "직전 회차와 동일한 식별자 충돌 감지"
        force_stop_app(device_id)
        result.duration_seconds = time.time() - start_time
        return result.to_dict()
    logger.info(f"✅ [식별자 무결성 검수 100% 통과] 직전 회차 대비 식별자 충돌 0% 확인")

    # 4. Logs Directory & Traffic Logger
    cycle_ymd = getattr(task, "cycle_ymd", None) or time.strftime("%Y%m%d")
    cycle_his = getattr(task, "cycle_his", None) or time.strftime("%H%M%S")
    if getattr(task, "session_dir", None):
        device_session_dir = Path(task.session_dir)
    else:
        device_session_dir = ROOT_DIR / "logs" / "traffic" / cycle_ymd / cycle_his / device_id
    device_session_dir.mkdir(parents=True, exist_ok=True)
    result.session_dir = str(device_session_dir)

    traffic_logger = TrafficAuditLogger(
        task_id=task.task_id,
        device_id=device_id,
        keyword=task.keyword,
        nv_mid=task.nv_mid or "Unknown",
        ip=result.ip,
        output_dir=device_session_dir,
        cycle_ymd=cycle_ymd,
        cycle_his=cycle_his
    )
    traffic_logger.set_identity(
        nnb=result.nnb,
        buc=nnb_packet.get("buc", ""),
        ssaid=profile["ssaid"],
        store_name=getattr(task, "store_name", "")
    )

    # [공인 IP 접근 이력 감사 기록]
    record_ip_access(public_ip=result.ip, device_id=device_id, keyword=task.keyword, action="TASK_START")

    serp_cdp = None
    serp_ws = None
    active_shop_cdp = None
    try:
        # [동적 데드라인 체인 탐색 키워드 풀 준비]
        deadline = start_time + getattr(TIMINGS, "DEVICE_HARD_TIMEOUT", 140.0) - 10.0
        kw_chain = [task.keyword]
        if hasattr(task, "keyword_candidates") and task.keyword_candidates:
            for item in task.keyword_candidates:
                cand_kw = item.get("keyword") if isinstance(item, dict) else str(item)
                cand_kw = (cand_kw or "").strip()
                if cand_kw and cand_kw != task.keyword and cand_kw not in kw_chain:
                    kw_chain.append(cand_kw)
        kw_chain = kw_chain[:2]  # 최대 2회차 시도 (1차 실패 시 2차 100% 완전 클린 리셋 실행)
        result.total_hops = len(kw_chain)

        for hop_idx, current_kw in enumerate(kw_chain):
            t_hop_start = time.time()
            result.hop_count = hop_idx + 1
            remaining = deadline - time.time()
            if hop_idx > 0:
                # [동적 데드라인 가드] 체류 40s + 클린 셋업 10s + 탐색 15s 보장 위해 최소 65초 이상 남았을 때만 2회차 진입
                if remaining < 65.0:
                    logger.info(f"⏳ [2회차 시도 안전 마감] 남은 시간({remaining:.1f}s < 65s) 부족 -> 추가 시도 없이 안전 마감")
                    break

                logger.info("=" * 80)
                logger.info(f"🔄 [완전 클린 리셋 2회차 진입] 1차 키워드('{kw_chain[0]}') 미노출 -> 기존 앱 완전 종료(force-stop) 후 100% 새로운 1회용 디바이스 생성!")
                logger.info(f"   ↳ 2차 대상 키워드: '{current_kw}' (남은 시간: {remaining:.1f}s)")
                logger.info("=" * 80)

                # 1. 이전 앱 완전 종료 및 세션 클린업
                force_stop_app(device_id)
                if serp_ws:
                    try:
                        await serp_ws.close()
                    except Exception:
                        pass
                    serp_ws = None
                serp_cdp = None
                await asyncio.sleep(0.5)

                # 2. 완전히 새로운 1회용 프로필 & NNB & 식별자 생성
                profile = generate_fresh_session_profile()
                nnb_packet = get_nnb_packet(device_id=device_id, force_refresh=True)
                result.nnb = nnb_packet.get("nnb", "")
                task.keyword = current_kw
                result.keyword = current_kw

                # 3. 식별자 무결성 감사
                identity_packet = {
                    "ssaid": profile["ssaid"],
                    "napp_di": profile.get("napp_di") or hashlib.md5(profile["ssaid"].encode("utf-8")).hexdigest(),
                    "nnb": result.nnb,
                    "nnb_age_seconds": int(nnb_packet.get("age_seconds", 0)),
                    "buc": nnb_packet.get("buc", ""),
                    "dadd": profile["dadd"],
                    "dadv": profile["dadv"],
                    "lat": profile["lat"],
                    "lng": profile["lng"],
                    "region": profile.get("region", "대한민국"),
                    "google_account": profile["google_account"],
                    "ip": result.ip
                }
                is_valid, audit_summary, table_text = auditor.audit_and_record(device_id, identity_packet)
                if not is_valid:
                    logger.critical(f"🚨 [2회차 식별자 충돌 감지!] 중단\n{table_text}")
                    result.status = "IDENTITY_COLLISION"
                    result.error_message = "2회차 식별자 충돌 감지"
                    break

                # 4. Traffic Logger 상태 갱신
                if traffic_logger:
                    traffic_logger.update_keyword(current_kw)
                    traffic_logger.set_identity(
                        nnb=result.nnb,
                        buc=nnb_packet.get("buc", ""),
                        ssaid=profile["ssaid"],
                        store_name=getattr(task, "store_name", "")
                    )
                    traffic_logger.record_event("SESSION_RESET", f"Reset device to 100% clean state for Attempt #{hop_idx+1}", {
                        "attempt": hop_idx + 1,
                        "keyword": current_kw,
                        "ssaid": profile["ssaid"],
                        "nnb": result.nnb
                    })

                # 이전 hop의 에러 상태 완전 리셋
                result.status = "RUNNING"
                result.error_message = None
                result.error_code = None
                result.failed_phase = None

            # [Step 1: Clean Launcher & Frida Hooking (매 회차 100% 클린 스폰)]
            FleetStateManager.update_device(
                device_id=device_id,
                state="LAUNCHING",
                keyword=current_kw,
                store_name=getattr(task, "store_name", "-"),
                target_mid=str(getattr(task, "nv_mid", "-")),
                progress=f"1회용 클린 기동 (Hop #{hop_idx+1})",
                status_msg="Frida 6대 훅 스폰 및 검증"
            )
            serp_cdp, serp_ws, launch_err = await launch_app_and_connect_cdp(
                task=task,
                device_id=device_id,
                cdp_port=cdp_port,
                nnb=result.nnb,
                buc=nnb_packet.get("buc", ""),
                profile=profile,
                traffic_logger=traffic_logger,
                result=result
            )
            if launch_err:
                logger.error(f"❌ [Hop #{hop_idx+1} 클린 기동 실패] {launch_err}")
                result.status = launch_err
                result.failed_phase = "PHASE_1_LAUNCH"
                result.error_code = launch_err
                result.error_message = f"네이버 앱 기동 실패: {launch_err}"
                FleetStateManager.update_device(device_id=device_id, state=launch_err, last_result=launch_err, progress=f"기동 실패: {launch_err}")
                force_stop_app(device_id)
                break

            result.checkpoints["p1_clean_launch"] = True
            result.checkpoints["p1_hooks_verified"] = True
            result.checkpoints["p1_net_connected"] = True

            # [Step 2: SERP Exploration & Fast-Fail]
            FleetStateManager.update_device(
                device_id=device_id,
                state="SEARCHING",
                keyword=current_kw,
                progress="통합검색 탐색 중",
                status_msg=f"SERP 오가닉 슬롯 스캔 ('{current_kw}')"
            )
            serp_res = await execute_serp_stage(
                task=task,
                result=result,
                cdp=serp_cdp,
                device_id=device_id,
                output_dir=str(device_session_dir),
                traffic_logger=traffic_logger
            )

            if serp_res.get("status") in ("NOT_SHOPPING_KEYWORD", "NOT_FOUND", "NETWORK_ERROR", "AD_CLICK_PREVENTED"):
                logger.warning(f"⚠️ [Hop #{hop_idx+1} SERP 미노출/차단] '{current_kw}' ({serp_res.get('status')}) -> 앱 완전 종료 후 다음 후보 키워드 검토")
                result.status = serp_res.get("status")
                result.failed_phase = "PHASE_2_SERP"
                result.error_code = serp_res.get("status")
                result.error_message = serp_res.get("error_message")
                force_stop_app(device_id)
                if serp_ws:
                    try:
                        await serp_ws.close()
                    except Exception:
                        pass
                    serp_ws = None
                serp_cdp = None
                continue

            if serp_res.get("status") in ("LOGIN_REQUIRED", "CAPTCHA_DETECTED", "LOGIN_CHALLENGE_DETECTED", "SERP_ACCESS_BLOCKED", "SHOPPING_ACCESS_BLOCKED"):
                logger.warning(f"🚨 [Hop #{hop_idx+1} 차단 감지] {serp_res.get('status')} -> 즉시 중단 및 Discard")
                result.status = serp_res.get("status")
                force_stop_app(device_id)
                break

            result.checkpoints["p2_serp_loaded"] = True
            result.checkpoints["p2_organic_section_found"] = True

            # Case A: 통합검색에서 타겟 클릭 완료
            if serp_res.get("hit_on_serp"):
                result.checkpoints["p2_serp_hit"] = True
                result.match_type = "SERP"
                result.search_type = "m.search"
                result.click_source = "SERP (m.search.naver.com)"
                result.click_action = "SERP_ORGANIC_TARGET"
                result.error_message = None
                result.error_code = None
                result.failed_phase = None

                rk_str = f"SERP {serp_res.get('serp_rank')}위"
                FleetStateManager.update_device(
                    device_id=device_id,
                    state="SERP_FOUND",
                    rank=rk_str,
                    progress=f"{rk_str} 타격 성공",
                    status_msg=f"SERP {rk_str} 핀포인트 조준 성공"
                )

                # 판매처 묶음(카탈로그) 상품인 경우
                if serp_res.get("is_catalog"):
                    if task.compare_id or getattr(task, "target_id", None):
                        FleetStateManager.update_device(
                            device_id=device_id,
                            state="CATALOG_NAV",
                            progress="카탈로그 판매처 탐색 중",
                            status_msg="Next.js RSC 캐시 및 판매처 정밀 터치 대기"
                        )
                        cat_res = await execute_catalog_stage(
                            task=task,
                            result=result,
                            cdp=serp_cdp,
                            device_id=device_id,
                            cdp_port=cdp_port,
                            output_dir=str(device_session_dir),
                            traffic_logger=traffic_logger
                        )
                        if not cat_res.get("success"):
                            st = cat_res.get("status", "CATALOG_STAGE_FAILED")
                            logger.warning(f"⚠️ [Hop #{hop_idx+1} 카탈로그 판매처 타격 실패] {st}")
                            result.status = st
                            result.chain_hops.append({
                                "hop": hop_idx + 1,
                                "keyword": current_kw,
                                "status": st,
                                "duration": round(time.time() - t_hop_start, 1)
                            })
                            force_stop_app(device_id)
                            continue
                        serp_cdp = cat_res.get("cdp") or serp_cdp
                    else:
                        result.status = "SUCCESS"
                        result.success = True
                        result.checkpoints["p5_landing_reached"] = True
                        result.chain_hops.append({
                            "hop": hop_idx + 1,
                            "keyword": current_kw,
                            "status": "SUCCESS",
                            "target_type": "CATALOG",
                            "duration": round(time.time() - t_hop_start, 1)
                        })
                        logger.info(f"🎯 [Hop #{hop_idx+1} 성공] 카탈로그 상품 SERP 핀포인트 타격 완결")
                        FleetStateManager.update_device(device_id=device_id, state="SUCCESS", progress="카탈로그 타격 완료")
                        force_stop_app(device_id)
                        break

                # 일반 상품: [Step 5] 랜딩 & 체류로 직행
                FleetStateManager.update_device(
                    device_id=device_id,
                    state="DWELL",
                    progress=f"체류 진행 중 ({task.dwell_seconds}s)",
                    status_msg="스마트스토어 상세페이지 비콘 및 자연 스크롤"
                )
                await execute_landing_and_dwell(
                    task=task,
                    result=result,
                    device_id=device_id,
                    cdp_port=cdp_port,
                    output_dir=str(device_session_dir),
                    traffic_logger=traffic_logger,
                    cdp=serp_cdp,
                    task_start_time=start_time
                )
                result.checkpoints["p5_landing_reached"] = bool(result.landing_url)
                result.checkpoints["p5_dwell_flushed"] = bool(result.dwell_duration_seconds > 0)
                result.chain_hops.append({
                    "hop": hop_idx + 1,
                    "keyword": current_kw,
                    "status": "SUCCESS",
                    "target_type": "GENERAL",
                    "duration": round(time.time() - t_hop_start, 1)
                })
                logger.info(f"🎯 [Hop #{hop_idx+1} 성공] 일반 상품 SERP 타격 및 체류 완결")
                FleetStateManager.update_device(device_id=device_id, state="SUCCESS", progress=f"체류 완료 ({result.dwell_duration_seconds:.1f}s)")
                force_stop_app(device_id)
                break

            # Case B: 통합검색에 타겟 없음 -> [Step 3: 쇼핑 더보기 이동]
            FleetStateManager.update_device(
                device_id=device_id,
                state="SHOP_NAV",
                progress="쇼핑 더보기 진입 중",
                status_msg="오가닉 쇼핑섹션 .more 실물 터치 대기"
            )
            nav_res = await execute_shop_navigation(
                task=task,
                result=result,
                cdp=serp_cdp,
                device_id=device_id,
                section_name=serp_res.get("section_name"),
                cdp_port=cdp_port,
                output_dir=str(device_session_dir),
                traffic_logger=traffic_logger
            )
            if not nav_res.get("success"):
                st = nav_res.get("status", "NO_SHOPPING_CATEGORY")
                logger.warning(f"⚠️ [Hop #{hop_idx+1} 쇼핑탭 이동 실패] {st} -> 앱 완전 종료 후 다음 후보 키워드 검토")
                result.status = st
                result.chain_hops.append({
                    "hop": hop_idx + 1,
                    "keyword": current_kw,
                    "status": st,
                    "duration": round(time.time() - t_hop_start, 1)
                })
                FleetStateManager.update_device(device_id=device_id, state=st, progress=f"쇼핑 이동 실패: {st}")
                force_stop_app(device_id)
                if serp_ws:
                    try:
                        await serp_ws.close()
                    except Exception:
                        pass
                    serp_ws = None
                serp_cdp = None
                if st in ("LOGIN_REQUIRED", "CAPTCHA_BLOCKED", "CAPTCHA_DETECTED", "LOGIN_CHALLENGE_DETECTED", "SHOPPING_ACCESS_BLOCKED", "SERP_ACCESS_BLOCKED"):
                    logger.warning(f"🚨 [Hop #{hop_idx+1} 로그인/차단 감지 ({st})] FDS 챌린지 즉시 종료 및 Discard")
                    break
                continue

            result.checkpoints["p3_more_btn_found"] = True
            result.checkpoints["p3_more_btn_clicked"] = True
            result.checkpoints["p3_shop_transitioned"] = True

            active_shop_cdp = nav_res.get("cdp") or serp_cdp

            # [Step 4: 쇼핑탭 NEXT_DATA 검증, 워밍업 및 CDP 스트라이크]
            FleetStateManager.update_device(
                device_id=device_id,
                state="SEARCHING",
                progress="쇼핑탭 상품 탐색 중",
                status_msg="쇼핑 검색결과(NEXT_DATA) 오가닉 매칭 중"
            )
            shop_res = await execute_shopping_stage(
                task=task,
                result=result,
                cdp=active_shop_cdp,
                device_id=device_id,
                output_dir=str(device_session_dir),
                traffic_logger=traffic_logger
            )
            if not shop_res.get("success"):
                st = shop_res.get("status", "NOT_FOUND")
                logger.warning(f"⚠️ [Hop #{hop_idx+1} 쇼핑탭 미노출] {st} -> 앱 완전 종료 후 다음 후보 키워드 검토")
                result.status = st
                result.chain_hops.append({
                    "hop": hop_idx + 1,
                    "keyword": current_kw,
                    "status": st,
                    "duration": round(time.time() - t_hop_start, 1)
                })
                force_stop_app(device_id)
                if serp_ws:
                    try:
                        await serp_ws.close()
                    except Exception:
                        pass
                    serp_ws = None
                serp_cdp = None
                if st in ("LOGIN_REQUIRED", "CAPTCHA_BLOCKED", "CAPTCHA_DETECTED", "LOGIN_CHALLENGE_DETECTED", "SHOPPING_ACCESS_BLOCKED", "SERP_ACCESS_BLOCKED"):
                    logger.warning(f"🚨 [Hop #{hop_idx+1} 로그인/차단 감지 ({st})] 화면 고착 방지 및 즉시 종료")
                    break
                continue

            result.checkpoints["p4_next_data_verified"] = bool(result.js_target_found)
            result.checkpoints["p4_dom_rendered"] = bool(result.shopping_rank)
            result.checkpoints["p4_target_clicked"] = bool(result.click_success)

            # 쇼핑탭에서도 카탈로그 상품인 경우
            if shop_res.get("is_catalog"):
                if task.compare_id or getattr(task, "target_id", None):
                    FleetStateManager.update_device(
                        device_id=device_id,
                        state="CATALOG_NAV",
                        progress="카탈로그 판매처 탐색 중",
                        status_msg="Next.js RSC 캐시 및 판매처 정밀 터치 대기"
                    )
                    cat_res = await execute_catalog_stage(
                        task=task,
                        result=result,
                        cdp=active_shop_cdp,
                        device_id=device_id,
                        cdp_port=cdp_port,
                        output_dir=str(device_session_dir),
                        traffic_logger=traffic_logger
                    )
                    if not cat_res.get("success"):
                        st = cat_res.get("status", "CATALOG_STAGE_FAILED")
                        logger.warning(f"⚠️ [Hop #{hop_idx+1} 카탈로그 판매처 타격 실패] {st}")
                        result.status = st
                        result.chain_hops.append({
                            "hop": hop_idx + 1,
                            "keyword": current_kw,
                            "status": st,
                            "duration": round(time.time() - t_hop_start, 1)
                        })
                        force_stop_app(device_id)
                        continue
                    active_shop_cdp = cat_res.get("cdp") or active_shop_cdp
                else:
                    result.status = "SUCCESS"
                    result.success = True
                    result.checkpoints["p5_landing_reached"] = True
                    result.chain_hops.append({
                        "hop": hop_idx + 1,
                        "keyword": current_kw,
                        "status": "SUCCESS",
                        "target_type": "CATALOG",
                        "duration": round(time.time() - t_hop_start, 1)
                    })
                    logger.info(f"🎯 [Hop #{hop_idx+1} 성공] 카탈로그 상품 쇼핑탭 핀포인트 타격 완결")
                    force_stop_app(device_id)
                    break

            # [수집 전용 모드 종료] target_rank == 999 인 경우 상품 클릭 없이 즉시 완료
            if task.target_rank == 999:
                result.status = "SUCCESS"
                result.success = True
                logger.info(f"💾 [{device_id}] [수집 전용 완료] __NEXT_DATA__ 덤프 완료 후 즉시 안전 종료")
                force_stop_app(device_id)
                break

            # [Step 5: 랜딩 검증 및 체류 스크롤]
            await execute_landing_and_dwell(
                task=task,
                result=result,
                device_id=device_id,
                cdp_port=cdp_port,
                output_dir=str(device_session_dir),
                traffic_logger=traffic_logger,
                cdp=active_shop_cdp,
                task_start_time=start_time
            )
            result.checkpoints["p5_landing_reached"] = bool(result.landing_url)
            result.checkpoints["p5_dwell_flushed"] = bool(result.dwell_duration_seconds > 0)
            result.chain_hops.append({
                "hop": hop_idx + 1,
                "keyword": current_kw,
                "status": "SUCCESS",
                "target_type": "GENERAL",
                "duration": round(time.time() - t_hop_start, 1)
            })
            logger.info(f"🎯 [Hop #{hop_idx+1} 성공] 일반 상품 쇼핑탭 타격 및 체류 완결")
            force_stop_app(device_id)
            break

        # 전체 체인 루프 종료 후 앱 안전 종료
        force_stop_app(device_id)

    except Exception as e:
        logger.error(f"💥 [파이프라인 실행 중 예외] {e}", exc_info=True)
        result.status = "UNHANDLED_EXCEPTION"
        result.error_message = str(e)
        force_stop_app(device_id)
    finally:
        if active_shop_cdp and active_shop_cdp != serp_cdp:
            try:
                active_shop_cdp.close()
            except Exception:
                pass
        if serp_ws:
            try:
                await serp_ws.close()
            except Exception:
                pass

        # [Post-flight Gate] 단말기 Cookies DB 실측 무결성 검증 (CookieRollbackManager 전수 상시 검사)
        try:
            from src.device.cookie_rollback_manager import CookieRollbackManager
            is_valid_db, audit_reason, db_details = CookieRollbackManager.post_flight_gate(
                device_id=device_id,
                profile=profile,
                expected_nnb=result.nnb
            )
            if not is_valid_db:
                logger.critical(f"🚨 [Post-flight 무결성 위반 감지!] (이전상태: {result.status}) {audit_reason} | DB상태: {db_details}")
                if result.success or result.status in ("SUCCESS", "LOGIN_REQUIRED"):
                    result.success = False
                    result.status = "IDENTITY_ROLLBACK_DETECTED"
                    result.error_message = audit_reason
            else:
                logger.info(f"🔒 [Post-flight 무결성 통과] (상태: {result.status}) {audit_reason}")
        except Exception as audit_err:
            logger.warning(f"⚠️ [Post-flight 무결성 검사 중 오류] {audit_err}")

        try:
            audit_path = traffic_logger.finalize(status=result.status, error_message=result.error_message)
            result.audit_log_path = audit_path
        except Exception:
            pass

    result.duration_seconds = round(time.time() - start_time, 2)
    save_task_history(result.to_dict())
    return result.to_dict()
