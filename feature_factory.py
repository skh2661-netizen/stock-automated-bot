import pandas as pd
import numpy as np
import datetime, pytz
from models import CandidateFeature, Momentum, Volume, Pattern, Volatility, PriceStructure

def build_features(raw_data, market_context) -> list[CandidateFeature]:
    features_list = []
    
    now = datetime.datetime.now(pytz.timezone('Asia/Seoul'))
    market_open = now.replace(hour=9, minute=0, second=0)
    elapsed_mins = max(1, (now - market_open).total_seconds() / 60)
    if elapsed_mins > 390: elapsed_mins = 390 
    
    kp_1d, kp_5d, kp_20d = market_context["kospi_1d"], market_context["kospi_5d"], market_context["kospi_20d"]
    
    for item in raw_data:
        code, name, chg, hist = item["code"], item["name"], item["chg"], item["hist"]
        curr, prev = hist.iloc[-1], hist.iloc[-2]
        close_s, high_s, low_s, vol_s, open_s = hist['Close'], hist['High'], hist['Low'], hist['Volume'], hist['Open']
        
        vol_20_mean = vol_s.rolling(20).mean().iloc[-2]
        ma120 = close_s.rolling(120).mean().iloc[-1]
        
        # NaN 방어: 신규 상장주 등 데이터가 부족해 이평선이 그려지지 않으면 즉시 패스
        if pd.isna(vol_20_mean) or pd.isna(ma120):
            continue
            
        # 1. Momentum
        ma20 = close_s.rolling(20).mean().iloc[-1]
        ma60 = close_s.rolling(60).mean().iloc[-1]
        
        # ✅ [필수 수정] 인덱스 아웃오브바운드 방어 로직 (배열 길이가 짧으면 0번 인덱스 사용)
        idx_60 = -61 if len(close_s) > 60 else 0
        idx_120 = -121 if len(close_s) > 120 else 0
        
        rs_1d = round(chg - kp_1d, 2)
        rs_5d = round((((curr['Close'] / close_s.iloc[-6]) - 1) * 100) - kp_5d, 2)
        rs_20d = round((((curr['Close'] / close_s.iloc[-21]) - 1) * 100) - kp_20d, 2)
        rs_60d = round((((curr['Close'] / close_s.iloc[idx_60]) - 1) * 100), 2)
        rs_120d = round((((curr['Close'] / close_s.iloc[idx_120]) - 1) * 100), 2)
        ma_gap = round(((curr['Close'] - ma20) / ma20 * 100), 2) if ma20 > 0 else 0
        
        mom = Momentum(rs_1d, rs_5d, rs_20d, rs_60d, rs_120d, ma_gap)
        
        # 2. Volatility 
        tr1 = high_s - low_s
        tr2 = (high_s - close_s.shift(1)).abs()
        tr3 = (low_s - close_s.shift(1)).abs()
        atr_series = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
        atr_14 = int(atr_series.iloc[-1])
        atr_pct = round((atr_14 / curr['Close']) * 100, 2)
        
        pct_rank = atr_series.tail(120).rank(pct=True).iloc[-1]
        if pct_rank <= 0.2: atr_p_val = 20
        elif pct_rank <= 0.4: atr_p_val = 40
        elif pct_rank <= 0.6: atr_p_val = 60
        elif pct_rank <= 0.8: atr_p_val = 80
        else: atr_p_val = 100
        vty = Volatility(atr_14, atr_pct, atr_p_val)
        
        # 3. Volume
        vol_20_std = max(vol_s.rolling(20).std().iloc[-2], 1e-6)
        
        vr_5 = round(curr['Volume'] / (vol_s.rolling(5).mean().iloc[-2] + 1), 2)
        vr_20 = round(curr['Volume'] / (vol_20_mean + 1), 2)
        vr_60 = round(curr['Volume'] / (vol_s.rolling(60).mean().iloc[-2] + 1), 2)
        vol_zscore = round((curr['Volume'] - vol_20_mean) / vol_20_std, 2)
        
        expected_vol = max((vol_20_mean / 390) * elapsed_mins, 1)
        rvt = round(curr['Volume'] / expected_vol, 2)
        
        amt_s = close_s * vol_s
        mfr = min(round((amt_s.tail(6).iloc[:-1].mean() / (amt_s.iloc[-21:-1].mean() + 1)), 2), 5.0)
        vol = Volume(vr_5, vr_20, vr_60, vol_zscore, mfr, rvt)
        
        # 4. Pattern
        is_gap = curr['Open'] > prev['High']
        gap_ratio = round(((curr['Open'] - prev['High']) / prev['High'] * 100), 2) if is_gap else 0.0
        gap_survived = is_gap and (curr['Low'] >= prev['High'])
        
        body = abs(curr['Close'] - curr['Open'])
        c_range = curr['High'] - curr['Low'] if (curr['High'] - curr['Low']) > 0 else 1
        u_wick = curr['High'] - max(curr['Open'], curr['Close'])
        d_wick = min(curr['Open'], curr['Close']) - curr['Low']
        
        is_doji = body <= c_range * 0.1
        is_hammer = (d_wick >= body * 2) and (u_wick <= c_range * 0.1) and (curr['Close'] > ma20)
        is_shooting_star = (u_wick >= body * 2) and (d_wick <= c_range * 0.1)
        
        prev_body = prev['Close'] - prev['Open']
        curr_body_signed = curr['Close'] - curr['Open']
        is_bull_engulf = (prev_body < 0) and (curr_body_signed > 0) and (curr['Close'] > prev['Open']) and (curr['Open'] < prev['Close'])
        is_bear_engulf = (prev_body > 0) and (curr_body_signed < 0) and (curr['Close'] < prev['Open']) and (curr['Open'] > prev['Close'])
        is_piercing = (prev_body < 0) and (curr_body_signed > 0) and (curr['Open'] < prev['Low']) and (curr['Close'] > prev['Open'] - abs(prev_body)/2)
        is_dark_cloud = (prev_body > 0) and (curr_body_signed < 0) and (curr['Open'] > prev['High']) and (curr['Close'] < prev['Open'] + abs(prev_body)/2)
        
        pat = Pattern(is_gap, gap_ratio, gap_survived, is_doji, is_hammer, is_shooting_star, is_bull_engulf, is_bear_engulf, is_piercing, is_dark_cloud)
        
        # 5. Price Structure 
        dist_ma20 = round(((curr['Close'] - ma20) / ma20 * 100), 2) if ma20 > 0 else 0
        dist_ma60 = round(((curr['Close'] - ma60) / ma60 * 100), 2) if ma60 > 0 else 0
        dist_ma120 = round(((curr['Close'] - ma120) / ma120 * 100), 2) if ma120 > 0 else 0
        
        is_swing_low = (low_s.shift(2) < low_s.shift(3)) & (low_s.shift(2) < low_s.shift(4)) & (low_s.shift(2) < low_s.shift(1)) & (low_s.shift(2) < low_s)
        swing_lows = hist[is_swing_low]
        
        last_pl_price, last_pl_date, prev_pl_price, prev_pl_date = 0, "1900-01-01", 0, "1900-01-01"
        if len(swing_lows) >= 2:
            last_pl_price = int(swing_lows['Low'].iloc[-1])
            last_pl_date = swing_lows.index[-1].strftime("%Y-%m-%d")
            prev_pl_price = int(swing_lows['Low'].iloc[-2])
            prev_pl_date = swing_lows.index[-2].strftime("%Y-%m-%d")
            
        struc = PriceStructure(
            box_high=int(high_s.rolling(20).max().iloc[-1]),
            box_low=int(low_s.rolling(20).min().iloc[-1]),
            dist_ma20=dist_ma20, dist_ma60=dist_ma60, dist_ma120=dist_ma120,
            last_pivot_low_price=last_pl_price, last_pivot_low_date=last_pl_date,
            prev_pivot_low_price=prev_pl_price, prev_pivot_low_date=prev_pl_date
        )
        
        features_list.append(CandidateFeature(code, name, int(curr['Close']), chg, mom, vol, pat, vty, struc))
        
    return features_list
