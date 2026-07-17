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
            
            # RS 20일선 및 ATR 14일선 연산
            rs_20d = float(((price / hist['Close'].iloc[-20]) - 1) * 100) if len(hist) >= 20 else 0.0
            
            high_low = hist['High'] - hist['Low']
            atr_14 = float(high_low.rolling(window=14).mean().iloc[-1]) if len(hist) >= 14 else 0.0
            
            # 모델 객체 맵핑 및 조립
            cf = CandidateFeature(
                code=code, name=name, price=price, chg=float(chg),
                struc=PriceStructure(prev_pivot_high_price=0, prev_pivot_low_price=0, last_pivot_low_price=0),
                pat=PricePattern(is_bull_engulfing=False, is_hammer=False, gap_survived=False),
                vty=Volatility(atr_14=atr_14, natr_14=0),
                mom=Momentum(rs_20d=rs_20d, ma_20=ma_20),
                vol=VolumeFlow(vr_20=100.0, money_flow_ratio=50.0)
            )
            features.append(cf)
        except Exception as e:
            logging.debug(f"Feature build failed for {item.get('code')}: {e}")
            
    return features
