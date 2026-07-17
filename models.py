from dataclasses import dataclass

@dataclass
class PriceStructure:
    prev_pivot_high_price: float
    prev_pivot_low_price: float
    last_pivot_low_price: float
    dist_ma20: float  # 👑 전략 엔진이 애타게 찾던 20일선 이격도 속성 추가

@dataclass
class PricePattern:
    is_bull_engulfing: bool
    is_hammer: bool
    gap_survived: bool
    is_gap_up: bool

@dataclass
class Volatility:
    atr_14: float
    natr_14: float

@dataclass
class Momentum:
    rs_20d: float
    ma_20: float

@dataclass
class VolumeFlow:
    vr_20: float
    money_flow_ratio: float
    relative_vol_today: float

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
