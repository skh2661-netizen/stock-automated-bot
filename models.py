from dataclasses import dataclass

@dataclass
class PriceStructure:
    prev_pivot_high_price: float
    prev_pivot_low_price: float
    last_pivot_low_price: float
    dist_ma20: float  
    dist_52w_high: float
    high_stay_days: int

@dataclass
class PricePattern:
    is_bull_engulfing: bool
    is_hammer: bool
    gap_survived: bool
    is_gap_up: bool
    has_long_upper_shadow: bool  # [핵심] 장대 윗꼬리(매도세) 감지 필드

@dataclass
class Volatility:
    atr_14: float
    natr_14: float
    atr_compression: bool

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

@dataclass
class VolumeFlow:
    vr_20: float
    money_flow_ratio: float
    relative_vol_today: float
    trading_value_100m: float  # [핵심] 거래대금 (단위: 억원) 추가

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
