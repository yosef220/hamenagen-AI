# אריזה ושחרור

## שלוש המהדורות

כל המהדורות כוללות את אינדקס הידע ואת מודל זיהוי הווקאלי (6MB, `resources/audio-models`).

| מהדורה | קובץ | מה בפנים |
| --- | --- | --- |
| ניידת | `Hamenagen-<v>-Windows.zip` | התוכנה + Python מוטמע + ספריות הליבה. מודל הסיווג יורד פעם אחת. הנתונים ב-`data` שליד התוכנה. |
| אופליין | `Hamenagen-<v>-Windows-Offline.zip` | כמו הניידת, ובנוסף מודל הסיווג ב-`resources/models`. |
| התקנה | `Hamenagen-<v>-Setup.zip` (ובתוכו `Setup.exe`) | התקנה למשתמש הנוכחי, בלי הרשאות מנהל: קיצורי דרך, תפריט התחל, הסרה. הנתונים ב-`%APPDATA%\Hamenagen`. |

ההגדרות ב-[`electron-builder.config.js`](../electron-builder.config.js); המהדורה נבחרת במשתנה `HAMENAGEN_EDITION` ונכתבת לתוך ה-`package.json` הארוז (`hamenagenEdition`), ומשם `electron/main.js` יודע איפה לשמור נתונים.

## שחרור גרסה

1. מעדכנים את המספר ב-`package.json` וב-`backend/hamenagen/__init__.py`, ומוסיפים פסקה ל-`CHANGELOG.md`.
2. ממזגים ל-`main`, ואז אחת משתיים: מוסיפים תגית (`git tag v1.0.1 && git push origin v1.0.1`), או מריצים ידנית את התהליך „בדיקה, בנייה ושחרור” על `main` עם הסימון „לפרסם גרסה” — והתגית נוצרת לבד לפי `package.json`.
3. התהליך [`release.yml`](../.github/workflows/release.yml) רץ לבד:
   - בדיקות הליבה ובדיקת הממשק (התוכנה האמיתית מול ספריית דוגמה, שתי הערכות);
   - בנייה של שלוש המהדורות על Windows, ובכל אחת בדיקה שהליבה הארוזה עונה; באופליין גם שהמודל נטען בלי רשת;
   - פרסום כגרסה האחרונה ב-GitHub, עם הערות בעברית ו-`update.json`;
   - עדכון `update.json` של גרסת 0.1 הישנה, כדי שמי שעדיין משתמש בה יקבל הודעה על הגרסה החדשה.

התגית חייבת להתאים לגרסה ב-`package.json`, אחרת הבנייה נעצרת.

## בדיקת עדכונים בתוכנה

כל גרסה בודקת את `https://github.com/yosef220/hamenagen-AI/releases/latest/download/update.json` (בהפעלה, אם „לבדוק עדכונים” דלוק, או ידנית בהגדרות). הקובץ מכיל את מספר הגרסה, תיאור קצר וקישור הורדה לכל מהדורה, כך שמשתמש בגרסת האופליין מקבל את גרסת האופליין. התוכנה לא מתעדכנת לבד — היא מציעה להוריד.

## בנייה מקומית (על Windows)

```powershell
npm ci
npm run prepare:win-python          # Python 3.11 מוטמע + ספריות הליבה ב-build\win-python
build\win-python\python.exe backend\scripts\prepare_audio_model.py --out build\audio-models
npm run dist                        # dist\Hamenagen-<v>-Windows.zip

# גרסת אופליין:
build\win-python\python.exe backend\scripts\prepare_model.py --out build\models
$env:HAMENAGEN_EDITION = "offline"; npm run dist

# התקנה:
$env:HAMENAGEN_EDITION = "setup"; npm run dist
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
