# 4. LEVEL 분류 (형님 지시사항: CRASH 국면 승격 시 RS20D 필수 가드레일 결속)
        if m_state == "CRASH":
            if cf.mom.rs_20d >= 35 and confidence >= 80: lvl = "LEVEL 4"
            elif cf.mom.rs_20d >= 20 and confidence >= 70: lvl = "LEVEL 3" # [교정] RS20 >= 20 가드레일 부활
            elif cf.mom.rs_20d >= 10 and confidence >= 60: lvl = "LEVEL 2" # [교정] RS20 >= 10 가드레일 부활
            else: lvl = "LEVEL 0"
        else:
            if confidence >= 80: lvl = "LEVEL 4"
            elif confidence >= 65: lvl = "LEVEL 3"
            elif confidence >= 50: lvl = "LEVEL 2"
            else: lvl = "LEVEL 1"
            
        final_results.append({
            "code": cf.code, "name": cf.name, "price": cf.price, "chg": cf.chg,
            "decision": {
                "level": lvl, "confidence": confidence, "trade_score": round(trade_score, 1),
                "pat_bonus": pat_bonus, "breadth_bonus": breadth_bonus,
                "primary_strategy": primary, "secondary_strategy": secondary, "trade_plan": plan
            },
            "raw_features": cf
        })
        
    final_results.sort(key=lambda x: x["decision"]["confidence"], reverse=True)
    
    # 5. 알림 필터 (정상화: LEVEL 3 이상만 발송)
    alert_candidates = []
    for res in final_results:
        lvl = res["decision"]["level"]
        conf = res["decision"]["confidence"]
        rs = res["raw_features"].mom.rs_20d
        
        if m_state == "CRASH":
            if lvl in ["LEVEL 3", "LEVEL 4"]: alert_candidates.append(res)
        else:
            if lvl in ["LEVEL 3", "LEVEL 4"]: alert_candidates.append(res)
            elif lvl == "LEVEL 2" and conf >= 55 and rs >= 15: alert_candidates.append(res)
            
    # ✅ 6. [디버그 뷰포트] 형님 지시사항: 모든 팩터를 해부하여 한 줄로 강제 병합 출력
    print("=" * 80)
    print(f"\n[ALL CANDIDATES (Top 15)]")
    for r in final_results[:15]:
        dec = r["decision"]
        rs20_val = r["raw_features"].mom.rs_20d
        print(
            f"{r['name']:<8} | "
            f"Trade={dec['trade_score']:>5.1f} | "
            f"Pat={dec['pat_bonus']:>2} | "
            f"Brd={dec['breadth_bonus']:>3} | "
            f"RS20={rs20_val:>6.2f} | "
            f"Conf={dec['confidence']:>4.1f} | "
            f"{dec['level']:<7} | "
            f"Str={dec['primary_strategy']}"
        )

    print("\n[ALERT CANDIDATES (Telegram)]")
    if not alert_candidates:
        print("(없음)")
    for a in alert_candidates:
        dec = a["decision"]
        rs20_val = a["raw_features"].mom.rs_20d
        print(
            f"- {a['name']:<8} | "
            f"RS20={rs20_val:>6.2f} | "
            f"Conf={dec['confidence']:<4.1f} | "
            f"{dec['level']:<7} | "
            f"Str={dec['primary_strategy']}"
        )
    print("\n" + "=" * 80)
            
    return {"market": market_context, "candidates": final_results, "alert_candidates": alert_candidates}
