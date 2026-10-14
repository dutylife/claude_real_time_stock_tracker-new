"""
盤中循環執行器：GitHub Actions 只啟動一次，程式自己在交易時段內每 5 分鐘呼叫一次 bot.main()。

好處：
1. 排程延遲只影響「啟動」那一次，之後的掃描節奏由程式自己控制。
2. 整段交易時間在同一個執行環境裡，alert_state.csv / avg_volume_cache.csv 一直都在，
   「同一檔今天只發一次」和日均量快取自然生效，不用另外做 cache。
3. 只安裝一次套件。
"""
import time
import traceback
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import yfinance as yf

import bot  # 修正後的 bot.py

TZ = ZoneInfo("Asia/Taipei")
OPEN_T = dtime(9, 0)
CLOSE_T = dtime(13, 35)
HOLIDAY_CHECK_T = dtime(9, 45)   # Yahoo 1分K有延遲，開盤初期查不到今天資料是正常的，所以晚一點再判斷休市
INTERVAL_MIN = 5


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


def next_slot(after):
    """下一個「分鐘為 5 的倍數」的時間點，再加 15 秒讓那根 K 棒補齊。"""
    minute = (after.minute // INTERVAL_MIN + 1) * INTERVAL_MIN
    base = after.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(minutes=minute, seconds=15)


def main():
    n = now_tw()
    if n.weekday() >= 5:
        print("週末，結束。")
        return
    if n.time() > CLOSE_T:
        print("已過收盤時間，結束。")
        return

    # 排程會提早啟動（吸收 GitHub 的延遲），先等到開盤
    sleep_until(at_today(OPEN_T) + timedelta(minutes=2))

    print(f"✅ 開始循環掃描，台北時間 {now_tw():%H:%M:%S}")
    holiday_checked = False
    while now_tw().time() <= CLOSE_T:
        if not holiday_checked and now_tw().time() >= HOLIDAY_CHECK_T:
            holiday_checked = True
            if not has_today_data():
                print("9:45 仍沒有今天的資料，判斷為休市日，結束。")
                return

        print(f"\n=== 掃描 {now_tw():%H:%M:%S} ===")
        try:
            bot.main()
        except Exception:
            traceback.print_exc()  # 單次失敗不讓整個循環掛掉

        target = next_slot(now_tw())
        if target.time() > CLOSE_T:
            break
        sleep_until(target)

    print("收盤，結束。")


if __name__ == "__main__":
    main()
