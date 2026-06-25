import FinanceDataReader as fdr
import pandas as pd
import asyncio, datetime, pytz, time
import requests
import sqlite3
import os
import traceback

from scoring import (
    calculate_breakout_score,
    calculate_close_score,
    calculate_preopen_score,
    get_conviction_score,
    get_prime_score
)

from database import save_candidate, DB_PATH


MIN_PRICE = 1000
MIN_AMOUNT = 15_000_000_000
MAX_CANDIDATES = 15


# ============================================================
# Trade Plan Engine
# ============================================================

def calculate_trade_plan(price, buy_p, score, ma_gap):
    """
    목표가 / 손절가 계산

    Score 우수 + 안정 구간:
        공격 목표

    MA20 이격:
        과열도 반영
    """

    if score >= 80 and ma_gap <= 10:
        target1 = price * 1.10
        target2 = price * 1.18

    elif ma_gap <= 5:
        target1 = price * 1.08
        target2 = price * 1.15

    elif ma_gap <= 15:
        target1 = price * 1.05
        target2 = price * 1.10

    else:
        target1 = price * 1.03
        target2 = price * 1.06

    stop = buy_p * 0.95

    return int(target1), int(target2), int(stop)



# ============================================================
# JSON 안정 처리
# ============================================================

def safe_json_decode(res):
    try:
        text = res.text.strip()

        if (
            text.startswith("<")
            or "text/html" in res.headers.get(
                "Content-Type",
                ""
            ).lower()
        ):
            return None

        return res.json()

    except Exception:
        return None



# ============================================================
# KRX Universe Loader
# FDR → Naver → DB Cache
# ============================================================

def get_krx_retry():

    # ----------------------------------------
    # 1차 : FinanceDataReader
    # ----------------------------------------

    for _ in range(2):

        try:

            krx = fdr.StockListing("KRX")

            if not krx.empty:

                if "Symbol" in krx.columns:
                    krx.rename(
                        columns={
                            "Symbol": "Code"
                        },
                        inplace=True
                    )

                elif "ISU_CD" in krx.columns:
                    krx.rename(
                        columns={
                            "ISU_CD": "Code"
                        },
                        inplace=True
                    )


                if "Code" in krx.columns:

                    krx.rename(
                        columns={
                            "ChagesRatio": "ChangesRatio",
                            "ChgRate": "ChangesRatio"
                        },
                        inplace=True
                    )


                    krx = (
                        krx
                        .loc[:, ~krx.columns.duplicated()]
                        .reset_index(drop=True)
                    )


                    krx["ChangesRatio"] = pd.to_numeric(
                        krx["ChangesRatio"],
                        errors="coerce"
                    ).fillna(0)


                    return krx


        except Exception:

            time.sleep(1)



    # ----------------------------------------
    # 2차 : Naver Stock API Fallback
    # ----------------------------------------

    try:

        headers = {
            "User-Agent": "Mozilla/5.0"
        }


        df_list = []


        for market in [
            "KOSPI",
            "KOSDAQ"
        ]:

            url = (
                "https://m.stock.naver.com/api/stocks/"
                f"marketValue/{market}?page=1&pageSize=2500"
            )


            res = requests.get(
                url,
                headers=headers,
                timeout=5
            )


            data = safe_json_decode(res)


            if not data:
                continue


            stocks = data.get(
                "stocks",
                []
            )


            if not stocks:
                continue


            df = pd.DataFrame(stocks)


            df.rename(
                columns={
                    "itemCode": "Code",
                    "stockName": "Name",
                    "closePrice": "Close",
                    "fluctuationsRatio": "ChangesRatio",
                    "accumulatedTradingVolume": "Volume"
                },
                inplace=True
            )


            for col in [
                "Close",
                "Volume"
            ]:

                df[col] = (
                    df[col]
                    .astype(str)
                    .str.replace(",", "")
                )


                df[col] = pd.to_numeric(
                    df[col],
                    errors="coerce"
                ).fillna(0)



            df["ChangesRatio"] = pd.to_numeric(
                df["ChangesRatio"],
                errors="coerce"
            ).fillna(0)


            df_list.append(df)



        if df_list:

            return pd.concat(
                df_list,
                ignore_index=True
            )


    except Exception:

        pass



    # ----------------------------------------
    # 3차 : DB Cache
    # ----------------------------------------

    if os.path.exists(DB_PATH):

        try:

            conn = sqlite3.connect(
                DB_PATH
            )


            cache_df = pd.read_sql_query(
                """
                SELECT
                    code AS Code,
                    name AS Name,
                    price AS Close,
                    chg AS ChangesRatio
                FROM candidates
                WHERE date = (
                    SELECT max(date)
                    FROM candidates
                )
                """,
                conn
            )


            conn.close()


            if not cache_df.empty:

                cache_df["Volume"] = 1
                cache_df["Amount"] = cache_df["Close"]

                return cache_df


        except Exception:

            pass



    return pd.DataFrame(
        columns=[
            "Code",
            "Name",
            "Close",
            "ChangesRatio",
            "Amount",
            "Volume"
        ]
    )



# ============================================================
# 제외 종목 필터
# ============================================================

def remove_bad_targets(df):

    if "Name" not in df.columns:
        return df


    pattern = (
        r"스팩|ETF|ETN|우$|우[A-Z]$|"
        r"[0-9]+우[A-Z]?$|제[0-9]+호"
    )


    return df[
        ~df["Name"]
        .str.contains(
            pattern,
            regex=True,
            na=False
        )
    ]



# ============================================================
# Market Index
# ============================================================

def get_market_indices():

    try:

        kst = pytz.timezone(
            "Asia/Seoul"
        )


        start_date = (
            datetime.datetime.now(kst)
            -
            datetime.timedelta(days=40)
        ).strftime(
            "%Y-%m-%d"
        )


        kospi = fdr.DataReader(
            "KS11",
            start_date
        )


        kosdaq = fdr.DataReader(
            "KQ11",
            start_date
        )


        kp_1d = (
            (
                kospi["Close"].iloc[-1]
                /
                kospi["Close"].iloc[-2]
            )
            - 1
        ) * 100



        kd_1d = (
            (
                kosdaq["Close"].iloc[-1]
                /
                kosdaq["Close"].iloc[-2]
            )
            - 1
        ) * 100



        return (
            round(kp_1d, 2),
            round(kd_1d, 2)
        )


    except Exception:

        return 0.0, 0.0
        async def scan_market(run_type="OPEN_SCAN"):

    try:

        kst = pytz.timezone(
            "Asia/Seoul"
        )


        start_date = (
            datetime.datetime.now(kst)
            -
            datetime.timedelta(days=60)
        ).strftime(
            "%Y-%m-%d"
        )


        risk_level = 1


        # ------------------------------------------------
        # Market Context
        # ------------------------------------------------

        kp_1d, kd_1d = get_market_indices()


        krx = remove_bad_targets(
            get_krx_retry()
        )


        if (
            krx.empty
            or "Code" not in krx.columns
        ):

            return {
                "market": {
                    "mode": run_type,
                    "kospi": kp_1d,
                    "kosdaq": kd_1d
                },
                "stats": {
                    "data_error": True
                },
                "candidates": []
            }



        # ------------------------------------------------
        # Universe Normalize
        # ------------------------------------------------

        krx["Close"] = pd.to_numeric(
            krx["Close"],
            errors="coerce"
        )

        krx["Volume"] = pd.to_numeric(
            krx["Volume"],
            errors="coerce"
        )


        krx["Amount"] = (
            krx["Close"]
            *
            krx["Volume"]
        ).fillna(0)


        krx["ChangesRatio"] = pd.to_numeric(
            krx["ChangesRatio"],
            errors="coerce"
        ).fillna(0)



        stats = {

            "total": len(krx),

            "final": 0,

            "pass1": 0,

            "fail_heat": 0,

            "fail_score": 0,

            "data_error": False
        }



        # ------------------------------------------------
        # 1차 후보 필터
        # ------------------------------------------------

        if run_type == "TEST":

            candidates = krx[
                (krx["Close"] >= MIN_PRICE)
                &
                (krx["Amount"] >= MIN_AMOUNT)
            ]


        else:

            candidates = krx[
                (krx["Close"] >= MIN_PRICE)
                &
                (krx["Amount"] >= MIN_AMOUNT)
                &
                (krx["ChangesRatio"] >= 1)
                &
                (krx["ChangesRatio"] <= 18)
            ]


            candidates = (
                candidates
                .sort_values(
                    "Amount",
                    ascending=False
                )
                .head(100)
            )



        results = []



        # =================================================
        # Candidate Analysis Loop
        # =================================================

        for _, row in candidates.iterrows():


            stats["pass1"] += 1


            changes = float(
                row["ChangesRatio"]
            )


            code = str(
                row["Code"]
            ).zfill(6)



            # ------------------------------------------------
            # OHLCV History
            # ------------------------------------------------

            try:

                hist = fdr.DataReader(
                    code,
                    start_date
                )

            except Exception:

                continue



            if len(hist) < 25:

                continue



            hist = hist.copy()



            # ------------------------------------------------
            # Amount History
            # 반드시 OHLCV 계산 전에 생성
            # ------------------------------------------------

            hist["Amt"] = (
                hist["Close"]
                *
                hist["Volume"]
            )



            curr = hist.iloc[-1]



            # ------------------------------------------------
            # Technical Metrics
            # ------------------------------------------------

            ma20 = (
                hist["Close"]
                .rolling(20)
                .mean()
                .iloc[-1]
            )


            vol_ma = (
                hist["Volume"]
                .rolling(20)
                .mean()
                .iloc[-1]
            )


            vr = (
                curr["Volume"]
                /
                (vol_ma + 1)
            )



            ma_gap = (
                (
                    curr["Close"]
                    -
                    ma20
                )
                /
                ma20
                *
                100
            )



            shadow_ratio = (
                (
                    curr["High"]
                    -
                    curr["Close"]
                )
                /
                (
                    curr["High"]
                    -
                    curr["Low"]
                    +
                    0.0001
                )
            )



            cp_val = (
                (
                    curr["Close"]
                    -
                    curr["Low"]
                )
                /
                (
                    curr["High"]
                    -
                    curr["Low"]
                    +
                    0.0001
                )
                *
                100
            )



            # ------------------------------------------------
            # Heat Protection
            # ------------------------------------------------

            if run_type == "CLOSE_BET":

                is_mega_cap = (
                    row["Amount"]
                    >=
                    100_000_000_000
                )


                is_solid_candle = (
                    cp_val >= 70
                )


                heat_limit = (
                    35
                    if (
                        is_mega_cap
                        and
                        is_solid_candle
                    )
                    else
                    25
                )

            else:

                heat_limit = (
                    35
                    if row["Amount"]
                    >=
                    100_000_000_000
                    else
                    25
                )



            is_overheated = (
                ma_gap > heat_limit
            )



            # ------------------------------------------------
            # RS Relative Strength
            # ------------------------------------------------

            rs_1d = (
                changes
                -
                kp_1d
            )


            rs_5d = (
                (
                    hist["Close"].iloc[-1]
                    /
                    hist["Close"].iloc[-6]
                    -
                    1
                )
                *
                100
                -
                (
                    kp_1d
                    *
                    5
                )
            )


            rs_20d = (
                (
                    hist["Close"].iloc[-1]
                    /
                    hist["Close"].iloc[-21]
                    -
                    1
                )
                *
                100
                -
                (
                    kp_1d
                    *
                    20
                )
            )



            # ------------------------------------------------
            # Amount Strength
            # ------------------------------------------------

            amount_prev20 = (
                hist["Amt"]
                .iloc[-21:-1]
                .mean()
            )


            recent_amt = (
                hist["Amt"]
                .tail(6)
                .iloc[:-1]
                .mean()
            )


            if pd.isna(recent_amt):

                recent_amt = 0



            amount_strength = min(
                round(
                    recent_amt
                    /
                    (amount_prev20 + 1),
                    2
                ),
                5.0
            )



            # ------------------------------------------------
            # Prime Score
            # ------------------------------------------------

            prime_score = get_prime_score(
                rs_1d,
                rs_5d,
                rs_20d,
                amount_strength,
                True
            )



            # ------------------------------------------------
            # Overheat Protection
            # ------------------------------------------------

            if is_overheated:

                if prime_score < 70:

                    stats["fail_heat"] += 1

                    continue
            # ------------------------------------------------
            # Strategy Score Engine
            # ------------------------------------------------

            if run_type == "PRE_OPEN":

                score = calculate_preopen_score(
                    row["Amount"],
                    vr,
                    changes,
                    shadow_ratio,
                    cp_val,
                    rs_1d,
                    risk_level
                )


            elif "BREAKOUT" in run_type:

                score = calculate_breakout_score(
                    row["Amount"],
                    vr,
                    changes,
                    rs_1d,
                    risk_level
                )


            else:

                score = calculate_close_score(
                    row["Amount"],
                    vr,
                    changes,
                    shadow_ratio,
                    0,
                    cp_val,
                    rs_1d,
                    risk_level,
                    ma_gap
                )



            # ------------------------------------------------
            # Score Filter
            # ------------------------------------------------

            if score < 55:

                stats["fail_score"] += 1

                continue



            # ------------------------------------------------
            # Prime Final Ranking
            # Prime 50%
            # Score 30%
            # Heat 20%
            # ------------------------------------------------

            heat_score = max(
                0,
                100 - max(ma_gap, 0)
            )


            prime_final = (
                prime_score * 0.5
                +
                score * 0.3
                +
                heat_score * 0.2
            )



            # ------------------------------------------------
            # Candidate Classification
            # ------------------------------------------------

            candidate_type = "NONE"


            if is_overheated:

                # Prime 보호 종목
                # 과열 상태지만 리더 가능성 유지

                candidate_type = "WATCH"



            elif (
                score >= 55
                and
                ma_gap <= 15
            ):

                candidate_type = "ENTRY"



            elif prime_score >= 75:

                if ma_gap <= 15:

                    candidate_type = "LEADER"

                else:

                    candidate_type = "WATCH"



            elif (
                score >= 55
                and
                ma_gap > 15
            ):

                candidate_type = "WATCH"



            if (
                candidate_type == "NONE"
                and
                run_type != "TEST"
            ):

                continue



            # ------------------------------------------------
            # Entry Price Logic
            # ------------------------------------------------

            if ma_gap > 20:

                buy_p = int(
                    curr["Close"]
                    *
                    0.92
                )


            elif ma_gap > 10:

                buy_p = int(
                    curr["Close"]
                    *
                    0.96
                )


            else:

                buy_p = int(
                    curr["Close"]
                    *
                    0.985
                )



            # ------------------------------------------------
            # Trade Plan
            # ------------------------------------------------

            target_1, target_2, stop = calculate_trade_plan(
                curr["Close"],
                buy_p,
                score,
                ma_gap
            )



            # ------------------------------------------------
            # Candidate Object
            # ------------------------------------------------

            results.append({

                "code": code,

                "name": row["Name"],

                "score": score,

                "price": int(
                    curr["Close"]
                ),

                "chg": round(
                    changes,
                    2
                ),


                "buy_p": buy_p,


                "ma_gap": round(
                    ma_gap,
                    2
                ),


                "rs_1d": round(
                    rs_1d,
                    2
                ),


                "rs_5d": round(
                    rs_5d,
                    2
                ),


                "rs_20d": round(
                    rs_20d,
                    2
                ),


                "amount": int(
                    row["Amount"]
                ),


                "conviction": get_conviction_score(
                    rs_1d,
                    row["Amount"],
                    vr,
                    risk_level,
                    ma_gap,
                    cp_val
                ),


                "prime_score": prime_score,


                "prime_final": round(
                    prime_final,
                    1
                ),


                "type": candidate_type,


                "is_overheated": is_overheated,


                "target_1": target_1,


                "target_2": target_2,


                "stop_p": stop,


                "amount_strength": amount_strength,


                "pullback_price": int(
                    curr["Close"]
                    *
                    0.95
                ),


                "vr": round(
                    vr,
                    2
                ),


                "is_prime_leader": False

            })



    # =====================================================
    # Ranking / Prime Leader / Save
    # =====================================================

    type_priority = {

        "ENTRY": 3,

        "LEADER": 2,

        "WATCH": 1,

        "NONE": 0

    }



    results = sorted(
        results,
        key=lambda x: (
            type_priority.get(
                x["type"],
                0
            ),
            x["prime_final"],
            x["amount"]
        ),
        reverse=True
    )[:MAX_CANDIDATES]



    # -----------------------------------------------------
    # Prime Leader 선정
    # 정렬 후 최고 Prime Final
    # -----------------------------------------------------

    if results:

        prime = max(
            results,
            key=lambda x: x["prime_final"]
        )

        prime["is_prime_leader"] = True



    # -----------------------------------------------------
    # Database Save
    # -----------------------------------------------------

    for item in results:

        save_candidate(
            run_type,

            item["code"],

            item["name"],

            item["score"],

            item["buy_p"],

            item["target_1"],

            item["target_2"],

            item["stop_p"],

            item["price"],

            item["chg"],

            item["ma_gap"],

            item["prime_score"],

            item["prime_final"],

            item["conviction"],

            item["amount_strength"],

            item["rs_1d"],

            item["rs_5d"],

            item["rs_20d"],

            0,

            risk_level

        )



    stats["final"] = len(results)



    return {

        "market": {

            "mode": run_type,

            "kospi": kp_1d,

            "kosdaq": kd_1d

        },


        "stats": stats,


        "candidates": results

    }



except Exception:

    traceback.print_exc()


    return {

        "market": {

            "mode": run_type,

            "kospi": 0,

            "kosdaq": 0

        },


        "stats": {

            "total": 0,

            "final": 0,

            "data_error": True

        },


        "candidates": []

    }
