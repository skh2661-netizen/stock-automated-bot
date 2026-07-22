# models.py
from dataclasses import dataclass

@dataclass
class PriceStructure:
    prev_pivot_high_price: float
    prev_pivot_low_price: float
    last_pivot_low_price: float
    dist_ma20: float  
    dist_52w_high: float
    high_stay_days: int
    is_5d_breakout: bool  # [추가] 최근 5일 고점 돌파 여부

@dataclass
class PricePattern:
    is_bull_engulfing: bool
    is_hammer: bool
    gap_survived: bool
    is_gap_up: bool
    has_long_upper_shadow: bool

@dataclass
class Volatility:
    atr_14: float
    natr_14: float
    atr_compression: bool
    adr_20: float  # [추가] 20일 평균 일변동률(ADR)

@dataclass
class Momentum:
    rs_20d: float
    rs_60d: float
    rs_120d: float
    rs_250d: float
    true_rs_composite: float
    ma_20: float
    ma_gap: float  
    is_trend_up: bool
    is_ma20_up: bool  # [추가] 20일선 상승 기울기 여부

@dataclass
class VolumeFlow:
    vr_20: float
    money_flow_ratio: float
    relative_vol_today: float
    trading_value_100m: float
    is_vol_dry_up: bool  # [추가] 눌림목 거래량 급감 여부

@dataclass
class CandidateFeature:
    code: str
    name: str
    price: float
    chg: float
    struc: PriceStructure
    pat: PricePattern
    vty: Volatility
    mom: Momentum
    vol: VolumeFlow
