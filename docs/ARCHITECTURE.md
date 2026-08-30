# ארכיטקטורה — המנגן

מסמך זה מתאר את הארכיטקטורה שמומשה בסבב הבנייה הראשון, ואת ההתאמה למודולים
שבמסמך האפיון (§5).

## תמונת-על

```
┌──────────────────────────────────────────────────────────────┐
│                        Electron (UI)                         │
│  renderer/ (RTL Hebrew)  ──IPC──►  main.js  ──►  preload.js   │
│   §7 באנר מועד · §8 שדה הוראה · §11 חלון יוטיוב · §12 נגן     │
└───────────────────────────────┬──────────────────────────────┘
                                │ JSON-RPC over stdio (no socket)
                                ▼
┌──────────────────────────────────────────────────────────────┐
│                  Python core  (hamenagen.*)                  │
│                                                              │
│  rpc.py  ──►  service.PlayerService  (orchestrator)          │
│                     │                                        │
│   ┌─────────────────┼───────────────────────────────────┐   │
│   ▼        ▼        ▼            ▼           ▼            ▼   │
│ intent   fuzzy   classifier  hebrew_    index_db      fetcher│
│ (§8 NLP) (§8.3)  (§8.2)      calendar   (SQLite §9,10) (§11) │
│                             (§7)                             │
│                     ▲                                        │
│                 scanner (§9)  ──►  models.Track (§10)        │
└──────────────────────────────────────────────────────────────┘
```

## מיפוי מודולי האפיון → קוד

| מודול (אפיון §5) | קובץ | הערות |
|------------------|------|-------|
| Core Player | `electron/renderer/app.js` | `<audio>` מובנה, תור, בקרות |
| Library Scanner | `backend/hamenagen/scanner.py` | `os.walk`, דילוג על תיקיות מערכת |
| Metadata Index | `backend/hamenagen/index_db.py` | SQLite, אינדקסים לנושא/תאריכים |
| NLP / Intent Engine | `backend/hamenagen/intent.py` | מבוסס-כללים, שקוף, אופליין |
| Topic Classifier | `backend/hamenagen/classifier.py` + `topics.py` | היברידי: מילון → Embeddings |
| Fuzzy Matcher | `backend/hamenagen/fuzzy.py` | token-set + ordered ratio, רב-שדות |
| Hebrew Calendar | `backend/hamenagen/hebrew_calendar.py` | אלגוריתם Rata Die, ללא רשת |
| Online Fetcher | `backend/hamenagen/fetcher.py` | `SourcePlugin` מתחלף; יוטיוב/yt-dlp |
| Updater | 🚧 | ראה roadmap |
| Settings | `backend/hamenagen/settings.py` | JSON נייד, ברירות מחדל לפי §16 |

## החלטות מפתח

### 1. גשר stdio במקום שרת HTTP
כדי לשמור על ניידות ולהימנע מפתיחת פורט/חומת-אש, Electron מריץ את הפייתון
כתת-תהליך ומדבר איתו ב-JSON שורה-אחר-שורה (`rpc.py` ↔ `backend_bridge.js`).

### 2. Offline-first על ספריית התקן
הליבה כולה (NLP, חיפוש, לוח עברי, סיווג בסיסי) לא דורשת אף חבילה חיצונית.
כל תלות (mutagen/rapidfuzz/yt-dlp/sentence-transformers) עטופה ב-try/except
ומתפוגגת בחן. כך הבדיקות רצות בכל סביבה, והתוכנה לא נשברת ללא רשת (§17).

### 3. סיווג נושאי היברידי (§8.2)
1. עקיפת כותרת מהמילון (ודאות מלאה) — למשל "מנוחה ושמחה" → שבת.
2. התאמת מילת-מפתח מהמילון.
3. מודל Embeddings מקומי אופציונלי — נטען עצלנית, ומדלג אם אינו מותקן.

זה נותן דיוק גבוה לתוכן מוכר, והכללה לשירים חדשים כשהמודל זמין — בלי מודל ענק.

### 4. לוח עברי אופליין
מימוש עצמאי של המרת גרגוריאני→עברי (Dershowitz & Reingold). מאומת מול עוגני
תאריך ידועים בבדיקות (`test_hebrew_calendar.py`), כולל round-trip.

## <a name="roadmap"></a>Roadmap (המשך לפי §20)

* **שלב ב׳ (המשך):** חיבור מודל ה-Embeddings בפועל; סיווג לפי מילות שיר.
* **שלב ג׳:** מימוש מלא של הורדות yt-dlp כולל התקדמות והדלקה אוטומטית (§11);
  טיפול בשגיאות מקור (חסום/הוסר).
* **שלב ד׳:** Updater (§14), רדיו מנוהל (§13), חבילת אופליין (§6.2, ראה
  [OFFLINE_PACK.md](OFFLINE_PACK.md)), אריזה ל-EXE נייד (ראה
  [PACKAGING.md](PACKAGING.md)).

## נקודות פתוחות מהאפיון (§19) שנוגעות לקוד

* בחירת מודל Embeddings עברי קטן — מוגדר כ-`EmbeddingBackend.model_name`.
* השלמת "תאריך יציאה" לשירים ותיקים — כרגע מגיע מתגיות בלבד; אפשר להשלים
  מהמילון או ממטא-דאטה של ההורדה.
* פורמט חבילת האופליין — טיוטת מבנה ב-[OFFLINE_PACK.md](OFFLINE_PACK.md).
