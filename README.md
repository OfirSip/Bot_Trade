# PO-SignalBot — Finnhub → Signals for Pocket Option (M1/M3)

Telegram bot שמתחבר ל-Finnhub WS, מחשב סיגנלים (EMA alignment + RSI + תנודתיות + slope),
מייצר ויזואליזציות (גרף PNG) ושולח בטלגרם עם תפריט פשוט להתאמה ל-Pocket Option.

## ENV (Railway / local)
- TELEGRAM_BOT_TOKEN  — חובה (BotFather)
- TELEGRAM_CHAT_ID    — אופציונלי (לנעילה לצ'אט יחיד)
- FINNHUB_API_KEY     — חובה (WS)
- SINGLETON_PORT      — אופציונלי (47653)

## פקודות
- /start — פתיחת תפריט
- "⚙️ הגדרות" — בחירת expiry (M1/M3), גודל חלון, מינימום confidence וכו׳
- "📊 נכס" — בחר נכס (Pocket Option סימבולים נפוצים) → ממופה ל-Finnhub
- "🛰️ סטטוס" — מצב WS/טלמטריה + תקציר אינדיקטורים
- "🖼️ ויזואל" — גרף PNG של החלון הנוכחי
- "🧠 סיגנל" — החלטה UP/DOWN + confidence

## הערות
- מיפוי PO→Finnhub בסיסי לדוגמה (EUR/USD → OANDA:EUR_USD). הרחב/עדכן לפי הצורך.
- אין מסחר אוטומטי פה, רק סיגנלים וויזואליים וסט אפ להצמדה ידנית ל-PO.
