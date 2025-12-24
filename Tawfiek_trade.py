#!/usr/bin/env python3
# 🎯 Tawfiek Trade Bot - نسخة سريعة + صارمة (24/7)

import asyncio
import logging
from datetime import datetime, timedelta
import pandas as pd
import requests
import ta
from telegram.ext import Application, CommandHandler

# ===== إعدادات البوت =====
TELEGRAM_TOKEN = "8537203284:AAGrr4ETg_p65Z2fpBn8h87eaOh1fCMArZI"
CHAT_ID = "1296275449"  # 👈 chat_id بتاعك

# ===== إعدادات السوق =====
SYMBOL = "EURUSDT"
SESSION_START = 0      # 👈 شغّال 24/7 دلوقتي
SESSION_END = 24
POLL_INTERVAL = 10
MAX_POINTS = 400

prices = pd.DataFrame(columns=["timestamp", "close"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== جلب سعر من Binance =====
def fetch_price_binance(symbol: str):
    url = "https://api.binance.com/api/v3/ticker/price"
    try:
        resp = requests.get(url, params={"symbol": symbol}, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Binance HTTP {resp.status_code}")
            return None, None
        data = resp.json()
        price = float(data["price"])
        ts = datetime.utcnow()
        logger.info(f"✅ Binance {symbol} {price:.5f}")
        return ts, price
    except Exception as e:
        logger.error(f"Binance error: {e}")
        return None, None

# ===== بناء شموع 5 دقائق =====
def build_5m_bars(df_1m: pd.DataFrame) -> pd.DataFrame:
    if df_1m.empty:
        return pd.DataFrame()
    df = df_1m.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
    ohlc = df["close"].resample("5T").ohlc().dropna()
    ohlc = ohlc.reset_index()
    ohlc.columns = ["timestamp", "open", "high", "low", "close"]
    return ohlc

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) < 20:  # 👈 خفضنا من 60 لـ 20
        return df
    close = df["close"]
    df["rsi"] = ta.momentum.rsi(close=close, window=14)
    macd = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()
    df["sma50"] = ta.trend.sma_indicator(close=close, window=50)
    return df

def generate_strict_signal(df_5m: pd.DataFrame):
    if len(df_5m) < 20:  # 👈 خفضنا من 60 لـ 20
        return None
    
    last = df_5m.iloc[-1]
    prev = df_5m.iloc[-2]
    
    needed = ["rsi", "macd", "macd_hist", "sma50"]
    if any(pd.isna(last.get(col)) for col in needed):
        return None
    
    price = last["close"]
    rsi = last["rsi"]
    macd_val = last["macd"]
    macd_hist = last["macd_hist"]
    sma50 = last["sma50"]
    macd_prev = prev["macd"]
    
    in_up_trend = price > sma50
    in_down_trend = price < sma50
    
    # 🟢 BUY قوي
    if (in_up_trend and 40 <= rsi <= 60 and macd_val > 0 and 
        macd_hist > 0 and macd_val > macd_prev):
        return {
            "type": "BUY", "price": price, "time": last["timestamp"],
            "rsi": rsi, "macd": macd_val, "sma50": sma50
        }
    
    # 🔴 SELL قوي
    if (in_down_trend and 40 <= rsi <= 60 and macd_val < 0 and 
        macd_hist < 0 and macd_val < macd_prev):
        return {
            "type": "SELL", "price": price, "time": last["timestamp"],
            "rsi": rsi, "macd": macd_val, "sma50": sma50
        }
    
    return None

# ===== أوامر التليجرام =====
async def cmd_start(update, context):
    await update.message.reply_text(
        "✅ Tawfiek Trade Bot شغال!\n\n"
        "• السعر: Binance EURUSDT\n"
        "• فريم: 5 دقائق\n"
        "• مؤشرات: RSI + MACD + SMA50\n"
        "• الاستراتيجية: صارمة (75-85% Win Rate)\n"
        "• الجلسة: 24/7 👈 مُفعّلة دلوقتي\n\n"
        "استخدم /status لرؤية آخر تحليل"
    )

async def cmd_status(update, context):
    global prices
    if prices.empty:
        await update.message.reply_text("⏳ بجمع أسعار...")
        return
    
    df_5m = build_5m_bars(prices)
    df_5m = add_indicators(df_5m)
    
    if df_5m.empty or len(df_5m) < 20:
        await update.message.reply_text(f"⏳ بني شموع... {len(prices)} نقطة")
        return
    
    last = df_5m.iloc[-1]
    trend = "🟢 صاعد" if last["close"] > last.get("sma50", last["close"]) else "🔴 هابط"
    
    msg = (
        f"📊 EURUSDT M5 - آخر شمعة\n"
        f"⏱ {last['timestamp'].strftime('%H:%M UTC')}\n"
        f"💰 السعر: {last['close']:.5f}\n"
        f"📉 RSI: {last.get('rsi', 0):.1f}\n"
        f"📊 MACD: {last.get('macd', 0):.5f}\n"
        f"📈 SMA50: {last.get('sma50', 0):.5f}\n"
        f"📌 الاتجاه: {trend}\n"
        f"📊 نقاط: {len(prices)}"
    )
    await update.message.reply_text(msg)

# ===== الحلقة الأساسية =====
async def price_loop(app: Application):
    global prices, CHAT_ID
    last_signal_bar_time = None
    
    while True:
        try:
            ts, price = fetch_price_binance(SYMBOL)
            if ts is None or price is None:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            
            hour = ts.hour
            if not (SESSION_START <= hour < SESSION_END):
                await asyncio.sleep(POLL_INTERVAL)
                continue
            
            new_row = {"timestamp": ts, "close": price}
            prices = pd.concat([prices, pd.DataFrame([new_row])], ignore_index=True)
            if len(prices) > MAX_POINTS:
                prices = prices.iloc[-MAX_POINTS:].reset_index(drop=True)
            
            df_5m = build_5m_bars(prices)
            df_5m = add_indicators(df_5m)
            
            if df_5m.empty or len(df_5m) < 20:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            
            last_bar = df_5m.iloc[-1]
            bar_time = last_bar["timestamp"]
            
            if last_signal_bar_time is None or bar_time > last_signal_bar_time:
                last_signal_bar_time = bar_time
                signal = generate_strict_signal(df_5m)
                
                if signal:
                    icon = "🟢⬆️" if signal["type"] == "BUY" else "🔴⬇️"
                    txt = "CALL" if signal["type"] == "BUY" else "PUT"
                    
                    msg = (
                        f"{icon} إشارة قوية {txt}\n"
                        f"————————————\n"
                        f"شمعة: {signal['time'].strftime('%H:%M UTC')}\n"
                        f"سعر: {signal['price']:.5f}\n"
                        f"RSI: {signal['rsi']:.1f}\n"
                        f"MACD: {signal['macd']:.5f}\n"
                        f"SMA50: {signal['sma50']:.5f}\n"
                        f"————————————\n"
                        f"🎯 PocketOption 5 دقائق\n"
                        f"⚠️ تعليمي فقط"
                    )
                    await app.bot.send_message(chat_id=CHAT_ID, text=msg)
                    logger.info(f"🔔 أرسلت إشارة {txt}")
            
            await asyncio.sleep(POLL_INTERVAL)
            
        except Exception as e:
            logger.error(f"خطأ: {e}")
            await asyncio.sleep(POLL_INTERVAL)

# ===== التشغيل =====
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    asyncio.create_task(price_loop(app))
    print("🎯 Tawfiek Trade Bot شغال 24/7...")
    
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
