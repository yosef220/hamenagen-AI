# אריזה ל-Windows (EXE נייד)

מטרה: קובץ הפעלה **נייד** (Portable) יחיד ל-Windows, שיוצר קיצור דרך בשולחן
העבודה עם אייקון (אפיון §4, §6).

## אסטרטגיה
Electron (הממשק) + Python (הליבה). שני מסלולים אפשריים לאריזת הפייתון:

1. **Python מוטמע (embeddable)** — לצרף הפצת Python מוטמעת של Windows בתוך
   `resources/backend/` יחד עם התלויות. `backend_bridge.js` יפעיל אותה עם
   `HAMENAGEN_PYTHON` שמצביע ל-`python.exe` המצורף. יתרון: אין תלות ב-Python
   מותקן אצל המשתמש.
2. **PyInstaller** — לארוז את `hamenagen.rpc` ל-`hamenagen-backend.exe`
   נפרד, ולהפעיל אותו במקום `python -m hamenagen.rpc`.

מומלץ מסלול (1) לפשטות תחזוקה של התלויות (במיוחד `yt-dlp` שמתעדכן תכופות, §14),
והוא זה שמומש בקוד.

## שלבי בנייה (מסלול Electron portable + Python מוטמע)
על מכונת **Windows**:
```powershell
npm install
npm run build:win     # = prepare:win-python  +  dist
# פלט: dist\hamenagen-portable-0.1.0.exe
```

`npm run build:win` עושה שני דברים:
1. `scripts/prepare-win-python.ps1` — מוריד CPython "embeddable" ל-
   `build/win-python`, מפעיל `import site`, מבצע bootstrap ל-pip, ומתקין את
   `requirements.txt` לתוכו.
2. `electron-builder --win portable` — אורז הכול ל-EXE נייד יחיד.

`package.json` כבר מוגדר:
* `build.win.target = ["portable"]`, `build.win.icon = assets/icon.ico`.
* `build.extraResources` מעתיק את `backend/` (בלי tests/data) ואת
  `build/win-python` → `resources/python`.

בזמן ריצה `electron/backend_bridge.js` מזהה אוטומטית את ה-Python המוטמע תחת
`resources/python` (ונופל ל-`python` שב-PATH בפיתוח).

> הערה: הרצת `npm run dist` **לבד** מצריכה ש-`build/win-python` כבר קיים. לפיתוח
> מהיר בלי אריזה השתמש ב-`npm start` (משתמש ב-Python המערכתי).

### הטמעת מודל ה-AI בחבילה (רשות)
כדי לצרף גם את מודל הסיווג לאריזה (עבודה אופליין מלאה כבר מההתקנה):
```powershell
build\win-python\python.exe backend\scripts\prepare_model.py --out backend\data\models
```
ואז לכלול את `backend/data/models` ב-extraResources, או לספק אותו דרך
[חבילת האופליין](OFFLINE_PACK.md).

## אייקון
מקור: `assets/icon.svg` → `assets/icon.png` → `assets/icon.ico` (כולם כבר
במאגר). ליצירה מחדש:
```bash
python -c "from PIL import Image; Image.open('assets/icon.png').save('assets/icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
```

## קיצור דרך בשולחן העבודה
נוצר בהפעלה ראשונה (בגרסה ארוזה בלבד) ב-`electron/main.js`
(`ensureDesktopShortcut` → `shell.writeShortcutLink`).

## חבילת אופליין
ראה [OFFLINE_PACK.md](OFFLINE_PACK.md) — מנגנון להתקנת המודולים ללא רשת.
