scored_results = []
    
    for d in pre_eval_data:
        cf, plan, strats = d["cf"], d["plan"], d["strats"]
        code = cf.code
        ev = plan["sizing"].get("ev", -1.0)
        
        q_z = (QuantConfig.QUALITY_WEIGHTS["adj"] * z_dict[code]["z_adj"]) + (QuantConfig.QUALITY_WEIGHTS["rs"] * z_dict[code]["z_rs"])
        liq_z = z_dict[code]["z_tval"]
        risk_z = z_dict[code]["z_risk"]
        
        scored_results.append({
            "code": code, "name": cf.name, "price": cf.price, "chg": cf.chg, "sector": cf.sector,
            "ma20_gap": round(cf.struc.dist_ma20, 2), "trading_value": round(cf.vol.trading_value_100m, 1),
            "plan": plan, "strategies": strats,
            "decision": {
                "quality_z": q_z, "liq_z": liq_z, "risk_z": risk_z, "expected_value": ev, 
                "bayesian_win_rate": round(d["bayesian_win"], 3), 
                "true_rs": round(cf.mom.true_rs_composite, 2),
                # [추가] 텔레그램 출력용 상세 메타데이터 주입
                "dist_52w": round(cf.struc.dist_52w_high, 2),
                "atr_pct": round(cf.risk.atr_pct, 2),
                "tval": round(cf.vol.trading_value_100m, 1),
                "ma20_gap": round(cf.struc.dist_ma20, 2)
            }
        })

    valid_results = [r for r in scored_results if r["decision"]["expected_value"] >= QuantConfig.MIN_EV_THRESHOLD or is_holding_eval]
    
    if valid_results:
        df_valid = pd.DataFrame([r["decision"] for r in valid_results])
        
        qz_vals = df_valid["quality_z"].values
        qz_norms = 100.0 / (1.0 + np.exp(-qz_vals / QuantConfig.SIGMOID_TEMP))
        
        liq_vals = df_valid["liq_z"].values
        liq_norms = 100.0 / (1.0 + np.exp(-liq_vals / QuantConfig.SIGMOID_TEMP))
        
        risk_vals = df_valid["risk_z"].values
        risk_norms = 100.0 / (1.0 + np.exp(-risk_vals / QuantConfig.SIGMOID_TEMP))
        
        ev_vals = df_valid["expected_value"].values
        ev_cap = max(1.0, np.percentile(ev_vals, 95)) if len(ev_vals) > 0 else 1.5
        ev_norms = (np.clip(ev_vals, 0.0, ev_cap) / ev_cap) * 100.0
        
        w_qz = QuantConfig.FINAL_SCORE_WEIGHTS["quality_norm"]
        w_ev = QuantConfig.FINAL_SCORE_WEIGHTS["ev_norm"]
        w_risk = QuantConfig.FINAL_SCORE_WEIGHTS["risk_norm"]
        w_liq = QuantConfig.FINAL_SCORE_WEIGHTS["liq_norm"]
        
        for i, res in enumerate(valid_results):
            final_score = round((qz_norms[i] * w_qz) + (ev_norms[i] * w_ev) + (risk_norms[i] * w_risk) + (liq_norms[i] * w_liq), 2)
            if not np.isfinite(final_score): continue
            
            d = res["decision"]
            d["final_score"] = final_score
            d["percentile_rank"] = round(ev_norms[i], 1)
            
            # =========================================================================
            # [핵심 패치] 폭락장용 방어력 지표 (WatchScore) 산출 및 관찰 이유 생성
            # =========================================================================
            # 하방 경직성(RS, 신고가 근접), 유동성(tval)은 플러스, 변동성(atr)은 페널티
            w_score = (final_score * 0.4) + (d["true_rs"] * 0.4) + (max(0, 100 + d["dist_52w"]) * 0.1) + (min(500, d["tval"]) * 0.05) - (d["atr_pct"] * 2.0)
            d["watch_score"] = round(w_score, 2)
            
            reasons = []
            if d["dist_52w"] > -10.0: reasons.append("✔ 52주 신고가 근접")
            if d["true_rs"] > 10.0: reasons.append("✔ 시장 대비 RS 우수")
            if d["tval"] > 300: reasons.append("✔ 풍부한 거래대금 유지")
            if d["atr_pct"] < 3.0: reasons.append("✔ 낮은 변동성 (안정성)")
            if d["ma20_gap"] > 0: reasons.append("✔ 20일선 지지 굳건")
            
            if not reasons: reasons.append("✔ 낙폭 과대 후 반등 대기")
            d["reasons"] = reasons[:3] # 최대 3개까지만 노출

        # [핵심 패치] 시장 차단(CRASH) 상태면 WatchScore로 정렬, 아니면 FinalScore로 정렬
        if buy_blocked:
            valid_results.sort(key=lambda x: x["decision"]["watch_score"], reverse=True)
        else:
            valid_results.sort(key=lambda x: x["decision"]["final_score"], reverse=True)
