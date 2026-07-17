from models import CandidateFeature, PriceStructure, PricePattern, Volatility, Momentum, VolumeFlow
import math
import logging

def build_features(raw_data_list: list, market_context: dict) -> list:
    features = []
    for item in raw_data_list:
        try:
            code, name, chg, hist = item["code"], item["name"], item["chg"], item["hist"]
            if hist is None or len(hist) < 20: 
                continue
            
            price = float(hist['Close'].iloc[-1])
            ma_20 = float(hist['Close'].rolling(window=20).mean().iloc[-1])
            
            # 20일 상대강도(RS) 연산
            rs_20d = float(((price / hist['Close'].iloc[-20]) - 1) * 100) if len(hist) >= 20 else 0.0
            
            # 14일 ATR 연산
            high_low = hist['High'] - hist['Low']
            atr_14 = float(high_low.rolling(window=14).mean().iloc[-1]) if len(hist) >= 14 else 0.0
            
            # 👑 전략 엔진에 주입할 20일선 이격도(dist_ma20) 정밀 연산
            dist_ma20 = float(((price / ma_20) - 1) * 100) if ma_20 > 0 else 0.0
            
            cf = CandidateFeature(
                code=code, name=name, price=price, chg=float(chg),
                struc=PriceStructure(
                    prev_pivot_high_price=0.0, 
                    prev_pivot_low_price=0.0, 
                    last_pivot_low_price=0.0,
                    dist_ma20=dist_ma20  # 연산된 이격도 값 매핑
                ),
                pat=PricePattern(is_bull_engulfing=False, is_hammer=False, gap_survived=False, is_gap_up=False),
                vty=Volatility(atr_14=atr_14, natr_14=0.0),
                mom=Momentum(rs_20d=rs_20d, ma_20=ma_20),
                vol=VolumeFlow(vr_20=100.0, money_flow_ratio=50.0, relative_vol_today=1.0)
            )
            features.append(cf)
        except Exception as e:
            logging.debug(f"Feature build failed for {item.get('code')}: {e}")
            
    return features
