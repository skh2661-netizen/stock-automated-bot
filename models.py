# models.py
import os
from dataclasses import dataclass
from typing import Dict, Any

class QuantConfig:
    QUALITY_WEIGHTS = {"adj": 0.40, "rs": 0.30, "liq": 0.30}
    # [핵심] Risk와 Liquidity를 독립 팩터로 승격시킨 4원화 Final Score
    FINAL_SCORE_WEIGHTS = {"quality_norm": 0.40, "ev_norm": 0.35, "risk_norm": 0.15, "liq_norm": 0.10}
    
    LEVEL_PERCENTILES = {"L3": 0.05, "L2": 0.15, "L1": 0.30}
    MAX_WEIGHTS = {"NORMAL": 0.30, "CAUTION": 0.20, "WEAK": 0.15, "CRASH": 0.05, "UNKNOWN": 0.20}
    
    # [수정] 하드코딩 폐기. SystemState 인스턴스를 통해 DB에서 실시간 업데이트 받음
    DEFAULT_PRIOR_ALPHA = 50.0
    DEFAULT_PRIOR_BETA = 50.0
    PRIOR_WEIGHT_K = 100.0  
    
    STRAT_SCORES = {
        "시초/갭돌파": 5, "신고가돌파": 4, "눌림목(HL)": 4, "주도주(RS)": 3,
        "단기돌파": 3, "상승장악": 3, "과대낙폭반등": 2, "수급/종가베팅": 1
    }
    WIN_RATE_MARKET_MULT = {"NORMAL": 1.05, "CAUTION": 0.95, "WEAK": 0.85, "CRASH": 0.70, "UNKNOWN": 1.0}
    
    SIGMOID_TEMP = 0.60          
    T2_DECAY_FACTOR = 0.15       
    
    FEE_SLIPPAGE_COST = 0.015  
    KELLY_FRACTION_MULT = 0.5  
    KELLY_MAX_CAP = 0.25         
    VOLATILITY_TARGET_PCT = 2.0  
    
    # [핵심] ADV + Spread + Slippage를 고려한 유동성 참여율(Participation Rate) 캡
    ADV_PARTICIPATION_RATE = 0.005 
    
    MIN_EV_THRESHOLD = 0.05
    
    STOP_MIN_ATR_MULT = 0.5
    TARGET1_ATR_MULT = 2.0
    TARGET2_MULT_BREAKOUT = 4.0
    TARGET2_MULT_PULLBACK = 2.5
    TARGET2_MULT_REVERSAL = 2.0
    TARGET2_MARKET_MULT = {"NORMAL": 1.0, "CAUTION": 0.8, "WEAK": 0.6, "CRASH": 0.5, "UNKNOWN": 0.8}
    
    MIN_TRADING_VALUE_100M = 100.0
    GAP_CHASE_MAX_PCT = 5.0
    MA20_MAX_GAP_PCT = 12.0
    ATR_MIN_PCT = 0.005
    HH_BREAKOUT_ATR_MULT = 0.5
    DOJI_BODY_ATR_MULT = 0.2
    UPPER_SHADOW_ATR_MULT = 1.2
    UPPER_SHADOW_CLOSE_POS = 0.4
    MAX_STOP_LOSS_PCT = 0.15
    MIN_EXPECTED_RR = 1.2

    # =========================================================================
    # [V9 계약 확장] 기존 상수는 절대 수정하지 않음 — contracts.py가 요구하는
    # 새 이름들을 위 원본 값을 그대로 가리키는 별칭(alias)으로만 추가한다.
    # 값을 다시 정의하지 않고 참조만 하므로, 원본이 바뀌면 이 별칭도 자동으로 같이 바뀐다.
    # =========================================================================
    MAX_WEIGHTS_RATIO = {"NORMAL": 0.30, "CAUTION": 0.20, "WEAK": 0.15, "CRASH": 0.05}  # [의도] UNKNOWN 미포함 = Fail-Closed
    MAX_STOP_LOSS_RATIO = MAX_STOP_LOSS_PCT
    FEE_SLIPPAGE_COST_R = FEE_SLIPPAGE_COST
    KELLY_MAX_CAP_RATIO = KELLY_MAX_CAP
    VOLATILITY_TARGET_RATIO = VOLATILITY_TARGET_PCT
    ADV_PARTICIPATION_RATIO = ADV_PARTICIPATION_RATE
    ATR_MIN_RATIO = ATR_MIN_PCT  # [수정] 100배 축소 오류 정정 — 원본과 동일한 값을 그대로 사용

    # [신규] trade_plan.py에 하드코딩돼 있던 값들을 이름 붙여 옮긴 것 (계산 결과는 원본과 동일)
    EXPECTED_RR_T1_WEIGHT = 0.6   # generate_trade_plan()의 (0.6 * rr1) 그대로
    EXPECTED_RR_T2_WEIGHT = 0.4   # generate_trade_plan()의 (0.4 * ...) 그대로
    T2_DEFAULT_PROBABILITY = 0.45  # generate_trade_plan()의 markov 기본값 0.45 그대로
    ATR_TO_LIQUIDITY_MULT = 10.0   # generate_trade_plan()의 atr_pct * 10.0 그대로

    # [신규] Consumer 독립 검증용 허용오차 — 통계적 근거가 필요한 값이 아니라
    # 부동소수점 계산 오차만 흡수하면 되는 값이므로 작게 고정
    TOL_PRICE_ABS = 0.001
    TOL_RATIO_ABS = 0.01
    TOL_RR_ABS = 0.02
    TOL_PROB_ABS = 0.01
    TOL_EV_ABS = 0.005
    TOL_AMT_ABS = 1.0

@dataclass(frozen=True)
class PriceStructure:
    last_pivot_high_price: float
    prev_pivot_high_price: float
    prev_pivot_low_price: float
    last_pivot_low_price: float
    dist_ma20: float  
    dist_52w_high: float
    high_stay_days: int
    is_5d_breakout: bool
    is_higher_high: bool

@dataclass(frozen=True)
class PricePattern:
    is_bull_engulfing: bool
    is_hammer: bool
    gap_survived: bool
    is_gap_up: bool
    has_long_upper_shadow: bool

@dataclass(frozen=True)
class Volatility:
    atr_14: float
    natr_14: float
    atr_compression: bool
    adr_20: float
    return_var_20d: float  # [핵심 추가] 실제 수익률 분산 (Merton Kelly 연산용)

@dataclass(frozen=True)
class Momentum:
    rs_10d: float    
    rs_25d: float
    rs_60d: float
    rs_120d: float
    true_rs_composite: float
    ma_20: float
    ma_gap: float  
    is_trend_up: bool
    is_ma20_up: bool

@dataclass(frozen=True)
class VolumeFlow:
    vr_20: float
    money_flow_ratio: float
    relative_vol_today: float
    trading_value_100m: float
    adv_100m: float
    is_vol_dry_up: bool

@dataclass(frozen=True)
class RiskProfile:
    atr_pct: float
    chg_limit: float
    max_gap_allowed: float

@dataclass(frozen=True)
class CandidateFeature:
    code: str
    name: str
    sector: str  
    price: float
    chg: float
    struc: PriceStructure
    pat: PricePattern
    vty: Volatility
    mom: Momentum
    vol: VolumeFlow
    risk: RiskProfile
