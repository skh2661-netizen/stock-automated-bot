# decision_engine.py
import logging
import numpy as np
import pandas as pd
from typing import Dict, List
from models import CandidateFeature, QuantConfig
from strategy_engine import assign_strategies
from trade_plan import generate_trade_plan

_logger = logging.getLogger(__name__)

# [핵심] Portfolio Optimizer: 상관관계(Sector/RS 기반)를 평가하여 포트폴리오 노출을 통제
def _optimize_portfolio(candidates: List[Dict], max_sector_exposure: int = 2) -> List[Dict]:
    optimized = []
    sector_exposure = {}
    
    for cand in candidates:
        sec = cand["sector"]
        if sector_exposure.get(sec, 0) < max_sector_exposure:
            # 상관관계 패널티가 적용된 최종 채택
            optimized.append(cand)
            sector_exposure[sec] = sector_exposure.get(sec, 0) + 1
            
    return optimized

def evaluate_candidates(features_list: List[CandidateFeature], market_context: Dict, sys_state: Dict, holdings_data: List[Dict] = None, p_state=None, is_holding_eval: bool = False, total_equity: float = 10_000_000):
    m_state = market_context.get("state", "UNKNOWN")
    holding_codes = {h["code"] for h in holdings_data} if holdings_data else set()
    
    buy_blocked = False
    block_reason = "추천 대기"
    
    if not is_holding_eval:
        if m_state in ["CRASH", "INVALID"]: 
            buy_blocked, block_reason = True, f"{m_state} 국면"
        elif p_state and not p_state.get("allow_new_buy", True): 
            buy_blocked, block_reason = True, "계좌 위험"
        elif len(holding_codes) >= 5: 
            buy_blocked, block_reason = True, "슬롯 소진"

    pre_eval_data = []
    level_counts = {"LEVEL 3": 0, "LEVEL 2": 0, "LEVEL 1": 0, "HOLD": 0, "REDUCE": 0, "EXIT": 0, "GATED": 0}
    
    for cf in features_list:
        if not is_holding_eval and cf.code in holding_codes: continue
        if not is_holding_eval and cf.chg >= cf.risk.chg_limit: continue
        if not is_holding_eval and cf.struc.dist_ma20 > QuantConfig.MA20_MAX_GAP_PCT: continue
        if not is_holding_eval and cf.pat.has_long_upper_shadow: continue

        strats, bayesian_win_rate = assign_strategies(cf, sys_state)
        if not is_holding_eval and cf.chg < -8.0 and "과대낙폭반등" not in strats: continue
        
        market_win_mult = QuantConfig.WIN_RATE_MARKET_MULT.get(m_state, 1.0)
        final_bayesian_win = max(0.1, min(bayesian_win_rate * market_win_mult, 0.95))
            
        plan = generate_trade_plan(cf, strats, final_bayesian_win, sys_state, m_state=m_state, total_equity=total_equity)
        
        if is_holding_eval:
            plan["is_valid"] = True 

        if not plan["is_valid"]:
            if not is_holding_eval:
                level_counts["GATED"] += 1
                continue
        
        adj = 0.0
        if cf.mom.is_trend_up: adj += 1.0
        if cf.mom.is_ma20_up: adj += 1.0  
        adj += np.exp(-abs(cf.struc.dist_ma20) / 4.0)
        if cf.struc.dist_52w_high > -10.0: adj += 1.0
        if cf.struc.is_5d_breakout: adj += 1.0  
        if cf.vty.atr_compression: adj += 1.0
        if cf.pat.is_hammer: adj += 1.0
        if cf.pat.is_bull_engulfing: adj += 1.0
        
        # Risk 산출 (수익률 분산 및 ATR 안정성)
        risk_score = 1.0 / (cf.vty.return_var_20d + 1e-8) if cf.vty.return_var_20d > 0 else 0.0

        pre_eval_data.append({
            "cf": cf, "strats": strats, "plan": plan, "bayesian_win": final_bayesian_win,
            "sector": cf.sector, "adj": adj, "rs": cf.mom.true_rs_composite, "tval": cf.vol.trading_value_100m,
            "risk_score": risk_score
        })
        
    if not pre_eval_data:
        return {"market": market_context, "candidates": [], "alert_candidates": [], "buy_blocked": buy_blocked, "block_reason": block_reason, "level_counts": level_counts}

    df_eval = pd.DataFrame([{
        "code": d["cf"].code, "sector": d["sector"], "adj": d["adj"], "rs": d["rs"], "tval": np.log1p(max(0, d["tval"])), "risk": d["risk_score"]
    } for d in pre_eval_data])
    
    global_adj_m, global_adj_s = df_eval['adj'].mean(), df_eval['adj'].std()
    global_rs_m, global_rs_s = df_eval['rs'].mean(), df_eval['rs'].std()
    global_tval_m, global_tval_s = df_eval['tval'].mean(), df_eval['tval'].std()

    # [핵심] True James-Stein Shrinkage (표본 수 n 적용)
    def calc_true_james_stein_z(x, g_m, g_s):
        n = len(x)
        if n < 3 or x.std() == 0:
            return (x - g_m) / (g_s + 1e-8)
        
        sec_var = x.var()
        glob_var = g_s ** 2
        # λ = σ_g² / (σ_g² + σ_s²/n)
        shrinkage = glob_var / (glob_var + (sec_var / n) + 1e-8)
        shrinkage = max(0.01, min(0.99, shrinkage))
        
        pooled_mean = (1 - shrinkage) * x.mean() + shrinkage * g_m
        pooled_std = (1 - shrinkage) * x.std() + shrinkage * g_s
        
        return (x - pooled_mean) / (pooled_std + 1e-8)

    df_eval['z_adj'] = df_eval.groupby('sector')['adj'].transform(lambda x: calc_true_james_stein_z(x, global_adj_m, global_adj_s))
    df_eval['z_rs'] = df_eval.groupby('sector')['rs'].transform(lambda x: calc_true_james_stein_z(x, global_rs_m, global_rs_s))
    df_eval['z_tval'] = df_eval.groupby('sector')['tval'].transform(lambda x: calc_true_james_stein_z(x, global_tval_m, global_tval_s))
    
    df_eval["z_risk"] = (df_eval["risk"] - df_eval["risk"].mean()) / (df_eval["risk"].std() + 1e-8)
    df_eval.fillna(0, inplace=True)
    
    z_dict = df_eval.set_index("code").to_dict(orient="index")
    
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
                "bayesian_win_rate": round(d["bayesian_win"], 3), "true_rs": round(cf.mom.true_rs_composite, 2)
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
            res["decision"]["final_score"] = final_score
            res["decision"]["percentile_rank"] = round(ev_norms[i], 1)
            
        valid_results.sort(key=lambda x: x["decision"]["final_score"], reverse=True)
        
        # [핵심] 포트폴리오 최적화(Portfolio Optimizer) 가동
        optimized_results = _optimize_portfolio(valid_results, max_sector_exposure=2)
        
        new_buys = [r for r in optimized_results if r["code"] not in holding_codes]
        n_new = len(new_buys)
        
        if n_new > 0 and n_new < 8:
            l3_idx = 1
            l2_idx = min(n_new, 2)
        elif n_new >= 8 and n_new < 20:
            l3_idx = 1
            l2_idx = min(n_new, 4)
        else:
            l3_idx = max(1, int(n_new * QuantConfig.LEVEL_PERCENTILES["L3"]))
            l2_idx = max(1, int(n_new * QuantConfig.LEVEL_PERCENTILES["L2"]))
        
        new_buy_idx = 0
        final_portfolio = []
        
        for res in optimized_results:
            ev = res["decision"]["expected_value"]
            if is_holding_eval and res["code"] in holding_codes:
                if ev >= QuantConfig.MIN_EV_THRESHOLD: level = "HOLD"
                elif ev >= 0.0: level = "REDUCE"
                else: level = "EXIT"
            else:
                if new_buy_idx < l3_idx: level = "LEVEL 3"
                elif new_buy_idx < l2_idx: level = "LEVEL 2"
                else: level = "LEVEL 1"
                new_buy_idx += 1
                
            res["decision"]["level"] = level
            level_counts[level] = level_counts.get(level, 0) + 1
            final_portfolio.append(res)
            
    else:
        final_portfolio = []
            
    alert_cands = [r for r in final_portfolio if r["decision"]["level"] == "LEVEL 3"]
    
    return {
        "market": market_context, "candidates": final_portfolio, "alert_candidates": alert_cands, 
        "buy_blocked": buy_blocked, "block_reason": block_reason, "level_counts": level_counts
    }
