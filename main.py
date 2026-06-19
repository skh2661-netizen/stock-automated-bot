async def run_pipeline():
    mode = get_mode()
    if mode is None:
        save_log("SKIP", "작전시간 아님")
        return

    scan_result = await scan_market(run_type=mode)
    candidates = scan_result.get("candidates", [])

    if not candidates:
        print("발송할 후보 없음")
        return

    # [수정 3: 중복 방지 - unique_key 사용 확인]
    # format_scan_message가 기존 DB 결과 구조를 그대로 사용하도록 함
    msg = format_scan_message(scan_result)
    await send_message(msg)
    
    # DB 마킹: unique_key는 '날짜_코드' 형식이므로 f"{datetime.now().strftime('%Y%m%d')}_{c['code']}" 사용
    today_str = datetime.now().strftime('%Y%m%d')
    unique_keys = [f"{today_str}_{c['code']}" for c in candidates]
    mark_telegram_sent(unique_keys)
