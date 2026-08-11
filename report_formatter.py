# [report_formatter.py 내 변경 필요한 2개 함수만 수정]

def format_holding_report(holding_evals: list, success: bool) -> str:
    msg = "=== 💼 [2/5] HOLDINGS ===\n"
    
    if not success:
        return msg + "⚠️ 보유종목 상태 불명 (데이터 로드 실패)\n"
        
    if not holding_evals:
        return msg + "보유 종목 없음\n"
        
    lines = []
    for i, item in enumerate(holding_evals, 1):
        name = item["name"]
        action = item["action"]
        rtn = item["return_rate"]
        circle_num = chr(0x2460 + i - 1) if 1 <= i <= 20 else f"{i}."
        
        lines.append(f"{circle_num} {name}")
        lines.append(f"   {rtn:+.2f}%")
        
        if action == "EXIT":
            reason = item.get("exit_reason", "판정 근거 미전달")
            lines.append(f"   🔴 EXIT\n   {reason}\n")
        elif action == "REDUCE":
            lines.append(f"   🟠 REDUCE\n   비중 축소 필요\n")
        elif action == "DATA_MISSING":
            lines.append(f"   ⚠️ DATA_MISSING\n   시세 확인 불가\n")
        else:
            lines.append(f"   🟢 HOLD\n   트레일링 스탑 대기\n")
            
    return msg + "\n".join(lines)

def format_promotion_blocks(signal_stats: dict) -> tuple[str, list]:
    # ... (기존 예외 처리 로직 동일) ...
    
    actual_signals = signal_stats["actual_signals"]
    header = "=== 🎯 [5/5] NEW RECOMMENDATIONS ===\n"
    
    if not actual_signals:
        return header + "🚫 신규 진입 후보 없음\n", []

    candidate_blocks = []
    for i, sig in enumerate(actual_signals, 1):
        name = sig["name"]
        circle_num = chr(0x2460 + i - 1) if 1 <= i <= 20 else f"{i}."
        
        # 간결하게 [신규 진입 후보] 포맷만 유지
        block = f"{circle_num} {name}\n   🆕 신규 진입 후보"
        candidate_blocks.append(block)
        
    return header, candidate_blocks
