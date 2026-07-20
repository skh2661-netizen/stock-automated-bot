from typing import Dict, List, Any

def format_market_report(market_stats: Dict[str, Any]) -> str:
    state_emoji = "🟢" if market_stats["state"] == "NORMAL" else ("🟡" if market_stats["state"] == "CAUTION" else "🔴")
    report = (
        f"📊 <b>Market Health: {market_stats['state']}</b> {state_emoji}\n"
        f"Score: {market_stats.get('score', 0)} | KOSPI: {market_stats.get('kospi_1d', 0.0)}% | KOSDAQ: {market_stats.get('kosdaq_1d', 0.0)}%\n"
        f"Advance Ratio: {market_stats.get('advance_ratio', 0.0)}%\n"
    )
    return report

def format_signal_report(decision_results: Dict[str, Any]) -> str:
    if decision_results.get("buy_blocked"):
        return f"⏸️ <b>신규 진입 보류</b>\n사유: {decision_results['block_reason']}"
        
    alerts = decision_results.get("alert_candidates", [])
    if not alerts:
        return "🕵️‍♂️ 조건에 부합하는 강력한 매수 시그널이 없습니다."
        
    lines = []
    for idx, s in enumerate(alerts[:3]): # 최상위 3개만 브리핑
        plan = s["plan"]
        dec = s["decision"]
        
        reasons_str = "\n".join([f"✓ {r}" for r in s.get("reasons", [])])
        risks_str = "\n".join([f"△ {r}" for r in s.get("risks", [])])
        if not risks_str: risks_str = "△ 특이사항 없음"
        
        lines.append(
            f"★★★★★\n"
            f"<b>매수추천 : YES</b>\n\n"
            f"종목 : <b>{s['name']}</b> ({s['chg']}%)\n"
            f"추천강도 : {dec['adj_score']}점 (True RS: {dec['true_rs']})\n\n"
            f"[추천 사유]\n{reasons_str}\n\n"
            f"[리스크]\n{risks_str}\n\n"
            f"[행동 지침]\n"
            f"▶ 1차 타점 50% 진입 (권장가: {plan['entry']:,}원)\n"
            f"▶ 돌파 확인 후 50% 추가 진입\n"
            f"▶ 손절선: {plan['stop_loss']:,}원\n"
            f"▶ 목표가: {plan['target1']:,}원 / {plan['target2']:,}원\n"
            f"▶ 권장비중: {plan['sizing']['weight_pct']}% ({plan['sizing']['amount']:,}원)\n"
            f"--------------------------"
        )
    return "\n".join(lines)

def format_holding_report(holding_evals: List[Dict[str, Any]]) -> str:
    if not holding_evals:
        return "📁 현재 보유 중인 종목이 없습니다."
        
    lines = ["🚨 <b>보유종목 특별감시 (실시간 독립평가)</b>\n"]
    for h in holding_evals:
        alert_emoji = "⚠️" if h["action"] in ["STOP_LOSS", "WEAK_HOLD"] else ("🔥" if h["action"] in ["TAKE_PROFIT", "TAKE_PROFIT_EARLY"] else "✅")
        lines.append(
            f"{alert_emoji} <b>{h['name']}</b> (평단 {h['entry_price']:,}원)\n"
            f"현재가: {h['current_price']:,}원 (수익률 {h['return_pct']}%)\n"
            f"판단: <b>{h['action']}</b> | 사유: {h['reason']}\n"
        )
    return "\n".join(lines)
