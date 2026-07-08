from dataclasses import dataclass
from typing import Optional

@dataclass
class Momentum:
    rs_1d: float
    rs_5d: float
    rs_20d: float
    rs_60d: float
    rs_120d: float
    ma_gap: float

@dataclass
class Volume:
    vr_5: float
    vr_20: float
    vr_60: float
    vol_zscore: float
    money_flow_ratio: float
    relative_vol_today: float

@dataclass
class Pattern:
    is_gap_up: bool
    gap_ratio: float
    gap_survived: bool
    is_doji: bool
    is_hammer: bool
    is_shooting_star: bool
    is_bull_engulfing: bool
    is_bear_engulfing: bool
    is_piercing: bool
    is_dark_cloud: bool

@dataclass
class Volatility:
    atr_14: int
    atr_percent: float
    atr_percentile: int

@dataclass
class PriceStructure:
    box_high: int
    box_low: int
    dist_ma20: float
    dist_ma60: float
    dist_ma120: float
    last_pivot_low_price: int
    last_pivot_low_date: str
    prev_pivot_low_price: int
    prev_pivot_low_date: str

@dataclass
class CandidateFeature:
    code: str
    name: str
    price: int
    chg: float
    mom: Momentum
    vol: Volume
    pat: Pattern
    vty: Volatility
    struc: PriceStructure
