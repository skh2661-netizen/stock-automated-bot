from html import escape
def format_holding_report(results):
    msg = "📌 <b>HOLDING ENGINE [3/3]</b>\n\n"
    if not results: return [msg + "등록된 종목 없음"]
    for r in results:
        msg += f"<b>{escape(r['name'])}</b> ({r['pnl']}%)\nEXIT: {r['exit_score']}/10 | 판정: {r['judgment']}\n" + "-"*20 + "\n"
    return [msg]

def format_scan_messages(results):
    msg = f"🎯 <b>V8.8.1 DAILY REPORT [2/3]</b>\n\n"
    for t in ["STRONG_BUY", "BUY", "SETUP", "WATCH"]:
        target = [c for c in results if c['type'] == t]
        if not target: continue
        msg += f"<b>{t}</b>\n"
        for c in target[:2]:
            msg += f"- {escape(c['name'])} (Sc:{c['score']}, MA20:{c['ma_gap']}%) \n  진입:{c['buy_p']:,} / 손절:{c['stop_p']:,}\n"
    return [msg]
