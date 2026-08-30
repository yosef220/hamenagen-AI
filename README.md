# המנגן — נגן מוזיקה קהילתי חכם

> Smart Community Music Player — an **offline-first** desktop player that
> understands free-text Hebrew requests ("תשמיע לי שירים של שבת"), builds
> playlists from the entire local library, and — when online — completes
> missing songs from an external source (YouTube, via a pluggable adapter).

**סטטוס:** תשתית ראשונה עובדת (שלב א׳ + חלקים משלבים ב׳/ג׳). מבוסס על
[מסמך האפיון](docs/SPEC.md).

---

## מה כבר עובד (this bootstrap)

| יכולת | מצב | היכן |
|-------|-----|------|
| סריקת מאגר + אינדקס SQLite | ✅ | `backend/hamenagen/scanner.py`, `index_db.py` |
| מנוע הוראות בשפה טבעית (עברית) | ✅ | `backend/hamenagen/intent.py` |
| חיפוש חכם רב-שדות + סובלנות לשגיאות | ✅ | `backend/hamenagen/fuzzy.py` |
| סיווג נושאי היברידי (מילון + Embeddings אופציונלי) | ✅ | `backend/hamenagen/classifier.py`, `topics.py` |
| לוח עברי + הצעות לפי מועד (אופליין מלא) | ✅ | `backend/hamenagen/hebrew_calendar.py` |
| מודל נתונים לשיר (§10) | ✅ | `backend/hamenagen/models.py` |
| השלמה מקוונת מלאה (יוטיוב, yt-dlp) — חיפוש→בחירה→הורדה→הוספה→הדלקה | ✅ | `backend/hamenagen/fetcher.py`, `service.py` |
| התקדמות הורדה בזמן אמת (אירועי RPC) | ✅ | `rpc.py`, `electron/backend_bridge.js` |
| מודל סיווג AI מקומי מחובר (Embeddings) + סיווג לפי מילות שיר | ✅ | `classifier.py`, `scripts/prepare_model.py` |
| ממשק Electron RTL בעברית + נגן | ✅ | `electron/` |
| גשר JSON-RPC בין Electron ל-Python | ✅ | `electron/backend_bridge.js`, `backend/hamenagen/rpc.py` |
| אריזה ל-EXE נייד ל-Windows + Python מוטמע | ✅ | `scripts/prepare-win-python.ps1`, `package.json` |
| **רדיו חי — לשונית ערוצי קול חי מיוזיק (HLS)** | ✅ | `backend/hamenagen/radio.py`, `electron/renderer/app.js` |
| **עדכונים (§14) — manifest מרכזי, עדכון yt-dlp/מילון** | ✅ | `backend/hamenagen/updater.py` |
| **חבילת אופליין (§6.2) — בנייה/אימות/התקנה של `*.pack`** | ✅ | `backend/hamenagen/offline_pack.py` |
| בדיקות יחידה לליבה | ✅ 41 בדיקות | `backend/tests/` |

---

## הרצה מהירה

### הליבה בלבד (ללא ממשק גרפי) — עובד בכל מקום

```bash
cd backend
python -m hamenagen.cli scan ~/Music              # בונה אינדקס
python -m hamenagen.cli ask "תשמיע לי שירים של שבת"
python -m hamenagen.cli ask "תשמיע אמת של שמוליק סוכות"
python -m hamenagen.cli suggest                   # הצעה לפי התאריך העברי
python -m hamenagen.cli classifier                # מצב מודל הסיווג המקומי
python -m hamenagen.cli reclassify                # סיווג מחדש של כל המאגר
```

### היישום המלא (Electron)

```bash
npm install
# מומלץ להתקין את התלויות האופציונליות של הפייתון:
pip install -r requirements.txt
npm start
```

> ה-`main` של Electron מריץ אוטומטית `python -m hamenagen.rpc`. אפשר לכוון את
> נתיב הפייתון עם משתנה הסביבה `HAMENAGEN_PYTHON`.

### בדיקות

```bash
cd backend && python -m pytest -q      # 28 passed
```

---

## התקנה ובדיקה מפורטת

### דרישות מקדימות
- **Node.js 18+** ו-**Python 3.10+**.
- (אופציונלי) **ffmpeg** — נדרש להמרת אודיו בהורדות מיוטיוב.

### מצב פיתוח (להרצה ובדיקה מהירה)
```bash
npm install                       # Electron + hls.js (~300–500MB ל-node_modules)
pip install -r requirements.txt   # mutagen, rapidfuzz, yt-dlp (~30–60MB)
npm start                         # מריץ את היישום
```

### בדיקות
```bash
cd backend && python -m pytest -q     # 41 עוברות
```

### עדכונים וחבילת אופליין
```bash
python -m hamenagen.cli update-check                 # דורש שרת עדכונים מוגדר
python -m hamenagen.cli update-apply ytdlp           # עדכון עצמי של yt-dlp
python -m hamenagen.cli pack-install assets.pack     # התקנה אופליין
```

### גדלים משוערים
| רכיב | גודל |
|------|------|
| `node_modules` (פיתוח בלבד) | ~300–500MB |
| תלויות Python | ~30–60MB |
| מודל ה-AI (אופציונלי) | ~120–420MB |
| EXE נייד סופי (Windows, עם Python מוטמע) | ~150–250MB |

לאריזת ה-EXE הנייד ראה [docs/PACKAGING.md](docs/PACKAGING.md).

## עיצוב לפי עקרונות האפיון

* **Offline-first** — כל הליבה (חיפוש, NLP, לוח עברי, סיווג) רצה על ספריית
  התקן של פייתון בלבד. כל תלות חיצונית (`mutagen`, `rapidfuzz`, `yt-dlp`,
  `sentence-transformers`) היא **אופציונלית** ומתפוגגת בחן אם חסרה.
* **מקור חיצוני מתחלף** — `fetcher.py` מגדיר `SourcePlugin`; יוטיוב הוא רק
  המימוש הנוכחי, וקל להחליפו במקור מורשה (§18).
* **נייד** — אין שרת ואין פורט; ה-Electron מדבר עם הפייתון דרך stdio בלבד.

ראו את [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) לפירוט הארכיטקטורה, ואת
[docs/SPEC.md](docs/SPEC.md) למסמך האפיון המלא.

## הערה משפטית

הורדת תוכן מיוטיוב עלולה להתנגש בתנאי השימוש ובזכויות יוצרים (§18 באפיון).
הארכיטקטורה תוכננה עם מקור מתחלף כדי לאפשר מעבר קל למקור מורשה.
