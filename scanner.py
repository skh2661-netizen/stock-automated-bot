async def scan_market(run_type="OPEN_SCAN"):
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(kst)
    start_date = (now - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    risk = get_market_risk(start_date)
    
    krx = remove_bad_targets(get_krx_retry())
    krx['Amount'] = krx['Close'] * krx['Volume']
    krx = krx.loc[~krx.index.duplicated(keep='first')]
    krx['Upper_Shadow'] = (krx['High'] - krx[['Open','Close']].max(axis=1)) / krx['Close'] * 100
    
    condition = (krx['Close'] >= MIN_PRICE) & (krx['Amount'] >= MIN_AMOUNT) & (krx['ChangesRatio'] >= 3)
    candidates = krx[condition].sort_values('Amount', ascending=False).head(100)
    
    results = []
    for _, row in candidates.iterrows():
        try:
            hist = fdr.DataReader(str(row['Code']).zfill(6), start_date)
            if len(hist) < 25: continue
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            if (row['Close'] - ma20) / ma20 * 100 < 0: continue
            vol_ma = hist['Volume'].rolling(20).mean().iloc[-1]
            if (row['Volume'] / vol_ma) < 1.3: continue
            
            score = calculate_score(row['Amount'], (row['Volume']/vol_ma), row['ChangesRatio'], row['Upper_Shadow'], 0, 0, 0, 0, 0)
            if score < 75: continue
            
            save_candidate(str(row['Code']).zfill(6), row['Name'], score, int(row['Close']), 0, 0, 0, 0, 0, 0)
            results.append({"code": str(row['Code']).zfill(6), "name": row['Name'], "score": score})
        except: continue
    
    # [수정] risk_pct 추가하여 KeyError 방지
    return {
        "market": {"kospi": 0, "kosdaq": 0, "mode": "🟢 V8.4.2 정상", "risk_pct": 0}, 
        "stats": {"total": len(krx), "final": len(results)}, 
        "candidates": sorted(results, key=lambda x: x['score'], reverse=True)
    }
