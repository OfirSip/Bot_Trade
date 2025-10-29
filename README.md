# PO-SignalBot — Live FX/CRYPTO Tick Signals → Pocket Option Flow

בוט טלגרם שמתחבר ל-Finnhub WS, מבצע ניתוח מוקטב-רעש multi-signal (טרנד + מומנטום + רג'ים + סטטיסטיקות),
מייצר סיגנל (UP/DOWN/WAIT) עם Confidence, ומציג ויזואליזציות (גרף/אינדיקטורים) לאימות מהיר מול Pocket Option.

## ENV
- TELEGRAM_BOT_TOKEN  — חובה (BotFather)
- TELEGRAM_CHAT_ID    — אופציונלי (לנעול לצ'אט יחיד)
- FINNHUB_API_KEY     — מומלץ (ללא מפתח: הסטטוס יוצג אך אין דאטה חי)
- SINGLETON_PORT      — אופציונלי (47653)

## תפריט
- 📊 נכס — בחר נכס (PO→Finnhub mapping)
- ⚙️ הגדרות — Expiry (M1/M3), חלון, MinConf, ועוד
- 🛰️ סטטוס — מצב דאטה + תקציר חישובים (תמיד מוצג)
- 🖼️ ויזואל — גרף PNG עם EMA, RSI, אזורי רג'ים ותצוגת חלון
- 🧠 סיגנל — החלטה + Confidence + מיני-דיאגנוסטיקה

## הערות
- אין "דמו" בבוט. אם אין מפתח — הסטטוס יוצג כ-MISSING_API_KEY, אבל בלי דאטה חי לא יהיה סיגנל משמעותי.
- הכוונונים אסטרטגיים ניתנים לשינוי מהבוט. מומלץ לבדוק על חשבון דמו של PO.
