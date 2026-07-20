from typing import Dict, List, Any

def format_market_report(market_stats: Dict[str, Any]) -> str:
    state_emoji = "🟢" if market_stats["state"] == "NORMAL" else ("🟡" if market_stats["state"] == "CAUTION" else "🔴")
    
    report = (
        f"📊 <b>Market Health: {market_stats['state']}</b> {state_emoji}\n"
        f"Score: {market_stats['score']} | Source: {market_stats['source']}\n"
        f"Reason: {market_stats['reason']}\n\n"
        f"📈 <b>Index (1D)</b>\n"
        f"KOSPI: {market_stats['kospi_1d']}% | KOSDAQ: {market_stats['kosdaq_1d']}%\n\n"
        f"🔄 <b>Market Breadth</b>\n"
        f"상승: {market_stats['total_up']} | 하락: {market_stats['total_down']} | 보합: {market_stats['total_same']}\n"
        f"Advance Ratio: {market_stats['advance_ratio']}%\n"
    )
    return report

def format_signal_report(decision_results: Dict[str, Any]) -> str:
    if decision_results.get("buy_blocked"):
        return f"🛑 <b>신규 매수는 차단되었습니다.</b>\n사유: {decision_results['block_reason']}"
        
    alerts = decision_results.get("alert_candidates", [])
    if not alerts:
        return "🕵️‍♂️ 조건에 부합하는 강력한 시그널이 없습니다."
        
    lines = []
    for idx, s in enumerate(alerts[:5]):
        plan = s["plan"]
        strats_str = ", ".join(s["strategies"])
        dec = s["decision"]
        
        rr_val = plan.get('rr_ratio', -1.0)
        rr_str = f"{rr_val}" if rr_val > 0 else "N/A"
        
        # [수정] 거래대금 출력 추가
        lines.append(
            f"<b>{idx+1}위. {s['name']}</b> ({s['chg']}%)\n"
            f"💡 <b>전략: {strats_str}</b>\n"
            f"⭐ Rank: {dec['adj_score']}점 (Raw {dec['raw_score']} * {dec['multiplier']})\n"
            f"🔥 True RS: {dec['true_rs']} | 대금: {s['trading_value']}억 | 20MA 이격: {s['ma20_gap']}%\n"
            f"💰 <b>권장 매수가:</b> {plan['entry']:,}원\n"
            f"🎯 <b>목표가:</b> {plan['target1']:,}원 / {plan['target2']:,}원\n"
            f"🛡️ <b>손절가:</b> {plan['stop_loss']:,}원 (손익비: {rr_str})\n"
            f"⚖️ <b>권장 비중:</b> {plan['sizing']['weight_pct']}% ({plan['sizing']['amount']:,}원 / {plan['sizing']['qty']:,}주)\n"
        )
    return "\n".join(lines)

def format_holding_report(holding_evals: List[Dict[str, Any]]) -> str:
    if not holding_evals:
        return "📁 현재 보유 중인 종목이 없습니다."
        
    lines = []
    for h in holding_evals:
        alert_emoji = "⚠️" if h["action"] in ["STOP_LOSS", "WEAK_HOLD"] else ("🔥" if h["action"] in ["TAKE_PROFIT", "TAKE_PROFIT_EARLY"] else "✅")
        lines.append(
            f"{alert_emoji} <b>{h['name']}</b> (평단 {h['entry_price']:,}원)\n"
            f"현재가: {h['current_price']:,}원 (수익률 {h['return_pct']}%)\n"
            f"판단: <b>{h['action']}</b> | 사유: {h['reason']}\n"
        )
    return "\n".join(lines)
