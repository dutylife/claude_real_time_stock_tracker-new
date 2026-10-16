"""
盤中循環執行器：GitHub Actions 只啟動一次，程式自己在交易時段內反覆呼叫 bot.main()。

- 開盤前：先備好上市/上櫃對照、近20日均量、法人資料，開盤第一輪就能立刻掃描。
- 即時來源(證交所)正常時：約每 60 秒掃一次，訊號落後行情只有幾秒到一分鐘。
- 即時來源失敗：先略過那一輪、下一分鐘再試；連續失敗才退回 Yahoo(資料延遲約20分鐘)，改成約每 5 分鐘掃一次。
- 收盤：13:32 前結束。
"""
import time
import traceback
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import yfinance as yf

import bot  # 修正後的 bot.py

TZ = ZoneInfo("Asia/Taipei")
OPEN_T = dtime(9, 0)
CLOSE_T = dtime(13, 32)          # 13:30 收盤，多留 2 分鐘抓最後的收盤價
HOLIDAY_CHECK_T = dtime(9, 45)   # Yahoo 1分K有延遲，開盤初期查不到今天資料是正常的，所以晚一點再判斷休市
REALTIME_INTERVAL_SEC = 60       # 即時來源：每輪間隔(從「開始掃描」算起)
YAHOO_INTERVAL_SEC = 300         # Yahoo 備援：每輪間隔


def now_tw():
    return datetime.now(TZ)


def at_today(t):
    return datetime.combine(now_tw().date(), t, tzinfo=TZ)


def sleep_until(target):
    while True:
        remain = (target - now_tw()).total_seconds()
        if remain <= 0:
            return
        time.sleep(min(remain, 30))


def has_today_data():
    """用台積電 1 分 K 判斷今天有沒有開盤：休市日 Yahoo 只會回傳上一個交易日的資料。"""
    try:
        df = yf.download("2330.TW", period="1d", interval="1m", progress=False)
        if df is None or df.empty:
            return False
        return df.index[-1].tz_convert(TZ).date() == now_tw().date()
    except Exception:
        return True  # 查詢失敗時當作有開盤，不要誤殺


def main():
    n = now_tw()
    if n.weekday() >= 5:
        print("週末，結束。")
        return
    if n.time() > CLOSE_T:
        print("已過收盤時間，結束。")
        return

    # 排程會提早啟動(吸收 GitHub 的延遲)：先把開盤第一輪需要的東西備好，再等開盤
    try:
        bot.prewarm()
    except Exception:
        traceback.print_exc()
    sleep_until(at_today(OPEN_T) + timedelta(seconds=10))

    print(f"✅ 開始循環掃描，台北時間 {now_tw():%H:%M:%S}")
    holiday_checked = False
    while now_tw().time() <= CLOSE_T:
        if not holiday_checked and now_tw().time() >= HOLIDAY_CHECK_T:
            holiday_checked = True
            if not has_today_data():
                print("9:45 仍沒有今天的資料，判斷為休市日，結束。")
                return

        started = now_tw()
        print(f"\n=== 掃描 {started:%H:%M:%S} ===")
        try:
            bot.main()
        except Exception:
            traceback.print_exc()  # 單次失敗不讓整個循環掛掉

        # 即時來源(或剛略過一輪、準備重試)每分鐘一輪；退回 Yahoo 時每 5 分鐘一輪
        interval = REALTIME_INTERVAL_SEC if bot.SCAN.get('source') in ('realtime', 'skip') else YAHOO_INTERVAL_SEC
        target = max(started + timedelta(seconds=interval), now_tw())
        if target.time() > CLOSE_T:
            break
        sleep_until(target)

    print("收盤，結束。")


if __name__ == "__main__":
    main()
