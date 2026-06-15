import FinanceDataReader as fdr
import asyncio
import datetime
import pytz
import time

from scoring import calculate_score
from risk import get_market_risk
from database import save_candidate


MIN_PRICE = 2000
MIN_AMOUNT = 10_000_000_000
MAX_CANDIDATES = 10


def get_krx_retry():

    for i in range(3):
        try:
            krx = fdr.StockListing("KRX")

            if "ChagesRatio" in krx.columns:
                krx.rename(
                    columns={"ChagesRatio":"ChangesRatio"},
                    inplace=True
                )

            elif "ChgRate" in krx.columns:
                krx.rename(
                    columns={"ChgRate":"ChangesRatio"},
                    inplace=True
                )

            return krx

        except Exception as e:
            print(f"KRX 연결 실패 {i+1}/3 : {e}")
            time.sleep(5)

    raise Exception("KRX 데이터 연결 실패")


def remove_bad_targets(df):

    pattern = '스팩|ETF|ETN|우$|우[A-Z]$|제[0-9]+호'

    return df[
        ~df['Name'].str.contains(
            pattern,
            regex=True,
            na=False
        )
    ]


def calculate_candle_position(row):

    high_low = row['High'] - row['Low']

    if high_low <= 0:
        return 0

    return (
        (row['Close'] - row['Low'])
        / high_low
        * 100
    )


def calculate_upper_shadow(row):

    max_oc = max(
        row['Open'],
        row['Close']
    )

    if row['Close'] <= 0:
        return 0

    return (
        (row['High'] - max_oc)
        / row['Close']
        * 100
    )


async def scan_market(run_type="OPEN_SCAN"):

    kst = pytz.timezone("Asia/Seoul")

    now = datetime.datetime.now(kst)

    start_date = (
        now -
        datetime.timedelta(days=60)
    ).strftime("%Y-%m-%d")


    # 시장 위험도

    risk = get_market_risk(start_date)

    risk_level = risk["level"]


    if risk_level == 0:
        min_score = 75

    elif risk_level == 1:
        min_score = 80

    else:
        min_score = 85



    # 코스피 RS 기준

    try:

        market_hist = fdr.DataReader(
            "KS11",
            start_date
        )

        market_change = (
            market_hist['Close'].iloc[-1]
            /
            market_hist['Close'].iloc[-6]
            -1
        ) * 100


    except Exception:

        market_change = 0



    krx = get_krx_retry()


    total_count = len(krx)



    krx['Amount'] = (
        krx['Close']
        *
        krx['Volume']
    )


    krx = remove_bad_targets(krx)



    krx['Upper_Shadow'] = (
        krx.apply(
            calculate_upper_shadow,
            axis=1
        )
    )



    condition = (

        (krx['Close'] >= MIN_PRICE)

        &
        (krx['Amount'] >= MIN_AMOUNT)

        &
        (krx['ChangesRatio'] >= 3)

        &
        (krx['ChangesRatio'] <= 18)

        &
        (krx['Upper_Shadow'] <= 5)

    )



    candidates = (
        krx[condition]
        .sort_values(
            "Amount",
            ascending=False
        )
        .head(30)
    )


    results = []



    for _, row in candidates.iterrows():

        code = str(row['Code']).zfill(6)


        await asyncio.sleep(0.15)


        try:


            hist = fdr.DataReader(
                code,
                start_date
            )


            if len(hist) < 25:
                continue



            ma20 = (
                hist['Close']
                .rolling(20)
                .mean()
                .iloc[-1]
            )


            ma_gap = (
                row['Close']
                -
                ma20
            ) / ma20 * 100



            if ma_gap < 0:
                continue



            five_change = (

                hist['Close'].iloc[-1]
                /
                hist['Close'].iloc[-6]
                -1

            ) * 100



            vol_ma = (

                hist['Volume']
                .rolling(20)
                .mean()
                .iloc[-1]

            )


            if vol_ma <= 0:
                continue



            vol_ratio = (
                row['Volume']
                /
                vol_ma
            )


            if vol_ratio < 1.3:
                continue



            rs = (
                five_change
                -
                market_change
            )



            upper_shadow = row['Upper_Shadow']


            candle_position = calculate_candle_position(row)



            score = calculate_score(

                row['Amount'],

                vol_ratio,

                row['ChangesRatio'],

                upper_shadow,

                ma_gap,

                candle_position,

                rs,

                five_change,

                risk_level

            )



            if score < min_score:
                continue



            buy_p = int(row['Close'] * 0.985)

            target1 = int(row['Close'] * 1.023)

            target2 = int(row['Close'] * 1.063)

            stop = int(row['Close'] * 0.970)



            save_candidate(

                run_type,

                code,

                row['Name'],

                score,

                buy_p,

                target1,

                target2,

                stop

            )



            results.append({

                "code":code,

                "name":row['Name'],

                "score":score,

                "price":int(row['Close']),

                "buy_p":buy_p,

                "target1":target1,

                "target2":target2,

                "stop":stop,

                "rs":round(rs,2),

                "ma_gap":round(ma_gap,2),

                "vol_ratio":round(vol_ratio,2)

            })



        except Exception as e:

            print(
                f"{code} 처리 오류 : {e}"
            )

            continue



    results = sorted(
        results,
        key=lambda x:x['score'],
        reverse=True
    )[:MAX_CANDIDATES]



    return {

        "market":{

            "kospi":
            round(
                market_change,
                2
            )

        },


        "stats":{

            "total":
            total_count,

            "final":
            len(results)

        },


        "candidates":
        results

    }
