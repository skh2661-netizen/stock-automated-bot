# models.py
import os
from dataclasses import dataclass
from typing import Dict, Any

class QuantConfig:
    QUALITY_WEIGHTS = {"adj": 0.40, "rs": 0.30, "liq": 0.30}
    FINAL_SCORE_WEIGHTS = {"quality_norm": 0.40, "ev_norm": 0.35, "risk_norm": 0.15, "liq_norm": 0.10}
    
    LEVEL_PERCENTILES = {"L3": 0.05, "L2": 0.15, "L1": 0.30}
    
    DEFAULT_PRIOR_ALPHA = 50.0
    DEFAULT_PRIOR_BETA = 50.0
    PRIOR_WEIGHT_K = 100.0  
    
    STRAT_SCORES = {
        "시초/갭돌파": 5, "신고가돌파": 4, "눌림목(HL)": 4, "주도주(RS)": 3,
        "단기돌파": 3, "상승장악": 3, "과대낙폭반등": 2, "수급/종가베팅": 1
    }
    
    # [수정] 윈레이트 시장 배수는 평가용이므로 UNKNOWN 유지
    WIN_RATE_MARKET_MULT = {"NORMAL": 1.05, "CAUTION": 0.95, "WEAK": 0.85, "CRASH": 0.70, "UNKNOWN": 1.0}
    SIGMOID_TEMP = 0.60          
    
    # =========================================================================
    # [계약 수식 중앙화 및 단위 명확화 (RATIO = 0.05 -> 5%)]
    # =========================================================================
    VOLATILITY_TARGET_RATIO = 0.02   # 기존 2.0 (%)
    ATR_MIN_RATIO = 0.00005          # 기존 0.005 (%)
    MAX_STOP_LOSS_RATIO = 0.15       # 기존 0.15
    
    ADV_PARTICIPATION_RATIO = 0.005  # 기존 0.005
    ATR_TO_LIQUIDITY_MULT = 1000.0   # 유동성 슬리피지 승수 중앙화
    
    EXPECTED_RR_T1_WEIGHT = 0.6
    EXPECTED_RR_T2_WEIGHT = 0.4
    T2_DEFAULT_PROBABILITY = 0.45    # [추가] 기본 확률 중앙화
    T2_DECAY_FACTOR = 0.15           # RR 격차에 따른 T2 감쇠율
    
    FEE_SLIPPAGE_COST_R = 0.015      # 기존 FEE_SLIPPAGE_COST
    MIN_EV_THRESHOLD = 0.05
    MIN_EXPECTED_RR = 1.2
    
    KELLY_FRACTION_MULT = 0.5  
    KELLY_MAX_CAP_RATIO = 0.25       # 기존 KELLY_MAX_CAP
    
    # [계약] UNKNOWN은 삭제 (미정의 시장 상태 시 매수 차단 = Fail-Closed)
    MAX_WEIGHTS_RATIO = {"NORMAL": 0.30, "CAUTION": 0.20, "WEAK": 0.15, "CRASH": 0.05}
    TARGET2_MARKET_MULT = {"NORMAL": 1.0, "CAUTION": 0.8, "WEAK": 0.6, "CRASH": 0.5}
    
    # =========================================================================
    # [추가] Consumer 독립 검증 시 사용할 허용 오차 (Tolerance)
    # =========================================================================
    TOL_PRICE_ABS = 0.001
    TOL_RATIO_ABS = 0.01
    TOL_RR_ABS = 0.02
    TOL_PROB_ABS = 0.01
    TOL_EV_ABS = 0.005
    TOL_AMT_ABS = 1.0

    # 기존 상수들 유지
    MIN_TRADING_VALUE_100M = 100.0
    GAP_CHASE_MAX_PCT = 5.0
    MA20_MAX_GAP_PCT = 12.0
    HH_BREAKOUT_ATR_MULT = 0.5
    DOJI_BODY_ATR_MULT = 0.2
    UPPER_SHADOW_ATR_MULT = 1.2
    UPPER_SHADOW_CLOSE_POS = 0.4
    STOP_MIN_ATR_MULT = 0.5
    TARGET1_ATR_MULT = 2.0
    TARGET2_MULT_BREAKOUT = 4.0
    TARGET2_MULT_PULLBACK = 2.5
    TARGET2_MULT_REVERSAL = 2.0

# =========================================================================
# 하단부 데이터 클래스 원본 100% 동일
# =========================================================================

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
    return_var_20d: float

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
