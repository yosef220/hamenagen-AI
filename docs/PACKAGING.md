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

מומלץ מסלול (1) לפשטות תחזוקה של התלויות (במיוחד `yt-dlp` שמתעדכן תכופות, §14).

## שלבי בנייה (מסלול Electron portable)
```bash
npm install
pip install -r requirements.txt          # לתוך ה-Python המוטמע שייארז
npm run dist                             # electron-builder --win portable
# פלט: dist/hamenagen-portable-0.1.0.exe
```

`package.json` כבר כולל:
* `build.win.target = ["portable"]`
* `build.extraResources` שמעתיק את `backend/` לתוך ה-EXE.
* `build.win.icon = assets/icon.ico`.

## אייקון
מקור: `assets/icon.svg` (מומר ל-`icon.png`). ליצירת `icon.ico` ל-Windows:
```bash
# דוגמה (דורש ImageMagick):
magick assets/icon.png -define icon:auto-resize=256,128,64,48,32,16 assets/icon.ico
```

## קיצור דרך בשולחן העבודה
נוצר בהפעלה ראשונה (בגרסה ארוזה בלבד) ב-`electron/main.js`
(`ensureDesktopShortcut` → `shell.writeShortcutLink`).

## חבילת אופליין
ראה [OFFLINE_PACK.md](OFFLINE_PACK.md) — מנגנון להתקנת המודולים ללא רשת.
