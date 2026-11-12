# אריזה ושחרור

## ארבע המהדורות, כל אחת קובץ אחד

כל המהדורות כוללות את אינדקס הידע, את מודל זיהוי הווקאלי (6MB, `resources/audio-models`) ואת `ffmpeg.exe` (בנייה ב-LGPL של [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) מענף הגרסה האחרון, `resources/ffmpeg`, להורדות ב-MP3 עם תמונה). בלי ffmpeg ההורדות יוצאות M4A.

| מהדורה (`HAMENAGEN_EDITION`) | קובץ | מה בפנים |
| --- | --- | --- |
| `setup` | `Hamenagen-<v>-Setup.exe` | התקנה למשתמש הנוכחי, בלי הרשאות מנהל: קיצורי דרך, תפריט התחל, הסרה. מודל הסיווג יורד פעם אחת. הנתונים ב-`%APPDATA%\Hamenagen`. |
| `setup-offline` | `Hamenagen-<v>-Setup-Offline.exe` | אותה התקנה, עם מודל הסיווג ב-`resources/models`. |
| `portable` | `Hamenagen-<v>-Portable.exe` | קובץ שנפתח פעם אחת לתיקייה שבוחרים ([`scripts/portable.nsi`](../scripts/portable.nsi)), בלי התקנה ובלי רישום. הנתונים ב-`data` שליד התוכנה. |
| `offline` | `Hamenagen-<v>-Portable-Offline.exe` | כמו הניידת, עם מודל הסיווג. |

לכל קובץ יש גם ZIP שמכיל רק אותו, כי סינוני רשת חוסמים לפעמים הורדה של EXE גדול. ההגדרות ב-[`electron-builder.config.js`](../electron-builder.config.js). המהדורה נכתבת לתוך ה-`package.json` הארוז (`hamenagenEdition`), ומשם `electron/main.js` יודע איפה לשמור נתונים.

## העדכון החכם

1. **בבנייה**: אחרי שהתוכנה נפרשת ב-`win-unpacked`, [`scripts/parts.js`](../scripts/parts.js) (‏afterPack) כותב את `resources/parts.json`. הקובץ מתאר את חלקי התוכנה ואת טביעת התוכן של כל אחד: `runtime` (Electron), `app` (‏`app.asar`), `backend`, `python`, `ffmpeg`, `audio-models`, ובמהדורות האופליין גם `models`. ה-runtime מזוהה לפי גרסת Electron, ה-fuses והסמל, כי מספר הגרסה נכתב לתוך ה-EXE בכל בנייה. ffmpeg מזוהה לפי שורת הגרסה שלו, בלי תאריך הבנייה.
2. [`scripts/make_parts.py`](../scripts/make_parts.py) אורז כל חלק ל-ZIP דטרמיניסטי, `hamenagen-part-<שם>-<טביעה>.zip`. כך חלק משותף למהדורות הוא קובץ אחד בשחרור.
3. **בשחרור**: [`scripts/release_notes.py`](../scripts/release_notes.py) מוסיף ל-`update.json`, תחת `app.parts.<מהדורה>`, את הכתובת, הגודל וה-SHA-256 של כל חלק.
4. **בתוכנה**: [`smart_update.py`](../backend/hamenagen/smart_update.py) משווה את `parts.json` המקומי לזה שבשחרור, ומוריד רק חלקים שהטביעה שלהם השתנתה. ההורדה ממשיכה מאיפה שנעצרה. כל חלק נבדק פעמיים: SHA-256 של ה-ZIP, ואחר כך טביעת הקבצים שנפתחו. אחר כך החלק נפרש ל-`data/update/staging`.
5. **ההחלפה**: [`electron/update-apply.ps1`](../electron/update-apply.ps1) רץ אחרי שהמנגן נסגר. הוא מחכה שכל תהליך מתיקיית התוכנה ייגמר, מעביר כל חלק ישן הצידה ומכניס את החדש. אם משהו נכשל, הוא מחזיר הכל ממקומו, ובכל מקרה מפעיל את המנגן מחדש. התוצאה נשמרת ב-`result.json`, והמנגן מדווח עליה בהפעלה.
6. **כדי שחלק ישתנה רק כשבאמת השתנה**: ספריות Python נעולות ב-[`requirements-lock.txt`](../requirements-lock.txt) ומותקנות עם `--no-deps --no-compile`, ו-pip קבוע.
7. ה-CI בודק על Windows את ההחלפה ואת ההחזרה כשמשהו נכשל (בתיקייה עם שם עברי). הבדיקות של הליבה מריצות את כל השרשרת על שתי בניות קטנות, ובודקות שהחישוב ב-JavaScript ובפייתון זהה.

גרסה בלי `parts.json` (‏1.2 ומטה), גרסת פיתוח או תיקייה בלי הרשאת כתיבה, מקבלות את ההורדה המלאה כמו קודם.

## שחרור גרסה

1. מעדכנים את המספר ב-`package.json`, ב-`backend/hamenagen/__init__.py` וב-`electron/renderer/build-info.js`, ומוסיפים פסקה ל-`CHANGELOG.md` ול-`WHATS_NEW` ב-`scripts/release_notes.py`.
2. ממזגים ל-`main`, ואז אחת משתיים. אפשר להוסיף תגית (`git tag v1.3.1 && git push origin v1.3.1`). אפשר גם להריץ ידנית את התהליך „בדיקה, בנייה ושחרור” על `main` עם הסימון „לפרסם גרסה”, והתגית תיווצר לבד לפי `package.json`.
3. התהליך [`release.yml`](../.github/workflows/release.yml) רץ לבד:
   - בדיקות הליבה ובדיקת הממשק (התוכנה האמיתית מול ספריית דוגמה, בשתי הערכות);
   - בנייה של ארבע המהדורות על Windows. בכל אחת נבדק שהליבה הארוזה עונה. במהדורות האופליין נבדק גם שהמודל נטען בלי רשת, ובניידות שהקובץ נפתח בשקט לתיקייה;
   - חלקי העדכון החכם, ובדיקת ההחלפה וההחזרה;
   - פרסום כגרסה האחרונה ב-GitHub, עם הערות בעברית, `update.json` וחלקי העדכון;
   - עדכון `update.json` של גרסת 0.1 הישנה.

התגית חייבת להתאים לגרסה ב-`package.json`, אחרת הבנייה נעצרת.

## בנייה מקומית (על Windows)

```powershell
npm ci
npm run prepare:win-python          # Python 3.11 מוטמע + ספריות הליבה ב-build\win-python
build\win-python\python.exe backend\scripts\prepare_audio_model.py --out build\audio-models
$env:HAMENAGEN_EDITION = "setup"; npm run dist          # dist\Hamenagen-<v>-Setup.exe

# עם המודל:
build\win-python\python.exe backend\scripts\prepare_model.py --out build\models
$env:HAMENAGEN_EDITION = "setup-offline"; npm run dist

# ניידת: התיקייה, ואז הקובץ האחד (NSIS):
$env:HAMENAGEN_EDITION = "portable"; npm run dist        # dist\win-unpacked
makensis /NOCD /DVERSION=1.3.0 /DSRCDIR=dist\win-unpacked /DOUTFILE=dist\Hamenagen-1.3.0-Portable.exe /DICON=assets\icon.ico "/DLABEL=גרסה ניידת" scripts\portable.nsi
```

הפייתון המוטמע של Windows מתעלם מ-`PYTHONPATH`, ולכן `backend_bridge.js` מפעיל את הליבה עם `-c` שמוסיף את תיקיית הליבה ל-`sys.path` בעצמו.

## אינדקס הידע

`data/song_index.json` ו-`data/topic_lexicon.json` נבנים פעם אחת ונשמרים במאגר, כך שהבנייה של התוכנה לא תלויה ברשת:

```bash
python backend/scripts/build_knowledge.py          # מוריד בנימוס (ומטמין ב-build/knowledge-cache) ובונה
python backend/scripts/build_knowledge.py --offline  # בנייה מחדש מהמטמון בלבד
python backend/scripts/eval_knowledge.py --grid      # מדידה, וחיפוש ספים על מבחן הכיול
```

רשימת הערכים, הקטגוריות והטקסטים לכל מועד נמצאת בראש הסקריפט. מספריא נלקחות רק גרסאות ברישיון פתוח, והמקור והרישיון של כל טקסט נרשמים בקובץ.

## האייקון

המקור הוא [`assets/icon.svg`](../assets/icon.svg) — האות מ׳ ב-Frank Ruhl Libre על קטיפת תכלת עם פס רקמה בזהב. `npm run icons` מייצר ממנו את `icon.png`, את `icon.ico` (כל גודל מצויר בנפרד, כדי שהקטנים יישארו חדים) ואת כפתורי הנגן לשורת המשימות.

## חבילת אופליין (`.pack`)

למחשב שכבר מותקנת בו התוכנה ואין בו אינטרנט, אפשר להעביר רכיבים בקובץ `.pack` שמניחים ליד התוכנה — ראו [OFFLINE_PACK.md](OFFLINE_PACK.md). למחשב חדש בלי אינטרנט פשוט יותר להוריד את גרסת האופליין.
