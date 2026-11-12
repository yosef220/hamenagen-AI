"""Write the release notes and the update manifests for a tagged release.

    python scripts/release_notes.py v1.0.0 owner/repo dist

Produces, next to the built files in ``dist``:

* ``RELEASE_NOTES.md``  — the Hebrew release page, with real file sizes
* ``update.json``       — what 1.x installs check (releases/latest/download)
* ``legacy/update.json``— the old 0.1 format, so 0.1 installs see 1.0
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path


# What is new, by version (major.minor). The newest version's list goes on
# the release page; its one-line summary goes into update.json.
WHATS_NEW: dict[str, tuple[str, list[str]]] = {
    "1.2": (
        "חיפוש מדויק לפי זמר, תמונות אלבום, שמות בעברית תקינים, והורדה מיוטיוב שעובדת גם מאחורי נטפרי.",
        [
            "**חיפוש מדויק** — כל המילים בבקשה חייבות להתאים. „אלי הרצליך” מביא רק את השירים שלו "
            "(„השירים של אלי הרצליך”), ולא כל שיר שיש בו „אלי”. שגיאת כתיב קטנה עדיין נמצאת.",
            "**זמר שלא נמצא במחשב** — המנגן אומר שאין, ומציע מיוטיוב: להוריד שיר מסוים, או לבחור שירים "
            "מכל הערוץ של הזמר (הופעות ארוכות וקדימונים לא מסומנים מראש).",
            "**נטפרי** — כשהרשת חוסמת חיפוש ביוטיוב, המנגן אומר זאת בבירור, פותח את החיפוש בדפדפן, ומקבל "
            "את הקישור שהעתקת (לשיר, לפלייליסט או לערוץ). ההורדה עצמה עובדת לשירים שהרשת מתירה, "
            "ובדיקת האבטחה של החיבור נשארת פעילה.",
            "**הורדה עמידה** — מנוע ההורדה רץ בנפרד ונעצר לבד אם הוא נתקע או מתנפח; מנסה סוגי נגן "
            "חלופיים ומתעדכן כשיוטיוב משתנה. שירים יורדים כ-MP3 עם תמונה, שם השיר ושם הזמר.",
            "**תמונות אלבום** — מתוך הקבצים, מ-cover.jpg/folder.jpg שבתיקייה, ומיוטיוב בהורדות.",
            "**עברית תקינה** — שמות שנשמרו בקידוד עברי ישן ונראו כמו „øöåòä” מוצגים נכון; תגיות WMA "
            "נקראות; מספר רצועה בתחילת שם הקובץ יורד; ובמקום שם הקובץ מוצגת התיקייה. "
            "הספרייה נקראת מחדש פעם אחת אחרי העדכון.",
            "**פרטים ותמונה מהרשת** — בתפריט של כל שיר: חיפוש השיר, ובוחרים את הנכון. הפרטים נשמרים "
            "במנגן, והקובץ עצמו לא משתנה.",
        ],
    ),
    "1.1": (
        "אינדקס הידע: המנגן מכיר מאות שירים ופיוטים לפי מועד, מזהה שירים ווקאליים מהשמע, ואפשר לתקן נושא בלחיצה.",
        [
            "**אינדקס הידע** — המנגן מכיר עכשיו מאות שירים ופיוטים לפי מועד, מוויקיפדיה העברית ומספריא "
            "(„יה ריבון”, „עבדים היינו”, „אקדמות”), ואת אוצר המילים של כל מועד — כך שגם שיר שלא ראה "
            "מעולם מקבל נושא. במדידה על שמות שירים אמיתיים: 89% מקבלים נושא (ב-1.0: ‏55%), בלי טעויות. "
            "הכל בתוך התוכנה, בלי אינטרנט.",
            "**זיהוי שירים ווקאליים מהשמע** — המנגן מקשיב ברקע לשלושה קטעים קצרים מכל שיר ומזהה שירה בלי "
            "כלי נגינה. השירים שזוהו מחכים לאישור שלך בעמוד „ווקאלי”, ואז מוצעים בימי הספירה ובין המצרים.",
            "**תפריט לכל שיר** — לחיצה ימנית (או ⋯): למה השיר קיבל את הנושא שלו, בחירת נושא אחר, סימון "
            "ווקאלי, לנגן אחריו והצגה בתיקייה. התיקון שלך נשמר גם אחרי סריקה.",
            "**לומד מהאלבום ומהתיקייה** — שיר בלי שם מוכר מקבל את הנושא של רוב השירים באלבום או בתיקייה שלו.",
            "**תיקון** — שינוי נושא או הורדת שיר לא נתקעים בזמן שמודל הסיווג יורד בפעם הראשונה.",
        ],
    ),
    "1.0": (
        "עיצוב חדש, הלוח העברי בדף הבית, מועדפים, היסטוריה וטיימר שינה.",
        [
            "**עיצוב חדש לגמרי** — בהיר וכהה (או לפי Windows), גודל טקסט, ואותיות במקום תמונות.",
            "**הלוח העברי בדף הבית** — התאריך באותיות, המועד של היום וכפתור להשמעה, או ספירה לאחור למועד הבא.",
            "**מועדים חדשים** — ערב שבת, מוצאי שבת, ספירת העומר (\"היום 12 לעומר\"), ל״ג בעומר, בין המצרים, "
            "תשעה באב. בימי הספירה ובין המצרים מוצעת מוזיקה ווקאלית.",
            "**בקשות חדשות** — \"שעה של שירי שבת\", \"השירים שאהבתי\", \"מה ששמעתי לאחרונה\", \"השירים שאני הכי שומע\".",
            "**לב, היסטוריה ותור** — סימון שירים בלב, תור השמעה עם ערבוב וחזרה, וטיימר שינה שמנמיך בהדרגה.",
            "**ספרייה מלאה** — מיון, סינון לפי נושא, חיפוש, ושיר יכול להשתייך ליותר מנושא אחד.",
            "**סריקה מהירה** — קבצים שלא השתנו לא נקראים שוב; צלילי מערכת והקלטות קצרות לא נכנסים.",
            "**Windows** — כפתורי נגן בשורת המשימות, מקשי מדיה, ותצוגה בחלונית המדיה של Windows.",
            "**תיקונים** — שירים עם שמות בעברית מתנגנים בכל מקרה, ושירי חנוכה לא \"נעלמים\" כשחנוכה חל בשבת.",
        ],
    ),
}


def whats_new(version: str) -> tuple[str, str, list[str]]:
    """(major.minor, one-line summary, bullet list) for ``version``."""
    key = ".".join(version.split(".")[:2])
    summary, bullets = WHATS_NEW.get(key, WHATS_NEW[max(WHATS_NEW)])
    return key, summary, bullets


def size_text(n: int) -> str:
    mb = n / (1024 * 1024)
    return f"{mb:,.0f}MB" if mb >= 10 else f"{mb:.1f}MB"


def main(tag: str, repo: str, folder: str) -> int:
    version = tag.lstrip("v")
    dist = Path(folder)
    base = f"https://github.com/{repo}/releases/download/{tag}"
    page = f"https://github.com/{repo}/releases/tag/{tag}"

    files = {
        "portable": f"Hamenagen-{version}-Windows.zip",
        "offline": f"Hamenagen-{version}-Windows-Offline.zip",
        "setup_zip": f"Hamenagen-{version}-Setup.zip",
        "setup_exe": f"Hamenagen-{version}-Setup.exe",
    }
    sizes = {k: size_text((dist / v).stat().st_size) if (dist / v).exists() else "—" for k, v in files.items()}
    missing = [v for v in files.values() if not (dist / v).exists()]
    if missing:
        print("missing:", ", ".join(missing), file=sys.stderr)
        return 1

    minor, summary, bullets = whats_new(version)
    bullet_text = "\n".join(f"- {b}" for b in bullets)
    notes = f"""## המנגן {version}

נגן מוזיקה קהילתי חכם ל-Windows: מבין בקשות בעברית חופשית, מכיר את הלוח העברי, ועובד בלי אינטרנט.

### איזה קובץ להוריד

| קובץ | למי זה מתאים | גודל |
| --- | --- | --- |
| **[{files['portable']}]({base}/{files['portable']})** | הגרסה הניידת — בלי התקנה. מחלצים את ה-ZIP לתיקייה ומריצים `Hamenagen.exe`. בפעם הראשונה שיש אינטרנט היא מורידה את מודל הסיווג (פעם אחת). | {sizes['portable']} |
| **[{files['offline']}]({base}/{files['offline']})** | למחשב בלי אינטרנט בכלל: הכל בפנים, כולל מודל הסיווג. מחלצים ומריצים. | {sizes['offline']} |
| **[{files['setup_zip']}]({base}/{files['setup_zip']})** | התקנה רגילה: קיצור דרך בשולחן העבודה ובתפריט התחל, והסרה מהגדרות Windows. בתוך ה-ZIP נמצא קובץ ההתקנה. | {sizes['setup_zip']} |
| [{files['setup_exe']}]({base}/{files['setup_exe']}) | אותה התקנה ישירות כקובץ EXE (סינון רשת עלול לחסום הורדה של EXE גדול — אז ה-ZIP). | {sizes['setup_exe']} |

הגרסה הניידת שומרת את הספרייה בתיקייה `data` שליד התוכנה, כך שאפשר להעביר אותה עם התיקייה. הגרסה המותקנת שומרת ב-`%APPDATA%\\Hamenagen`.

### מה חדש ב-{minor}
{bullet_text}

### בהפעלה הראשונה
התוכנה אינה חתומה דיגיטלית, ולכן Windows עשוי להציג "Windows הגן על המחשב שלך". לוחצים **מידע נוסף** ← **הפעל בכל זאת**.
"""
    (dist / "RELEASE_NOTES.md").write_text(notes, encoding="utf-8")

    manifest = {
        "app": {
            "version": version,
            "published": date.today().isoformat(),
            "notes": summary,
            "page": page,
            "downloads": {
                "portable": f"{base}/{files['portable']}",
                "offline": f"{base}/{files['offline']}",
                "setup": f"{base}/{files['setup_zip']}",
            },
        }
    }
    (dist / "update.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    legacy = dist / "legacy"
    legacy.mkdir(exist_ok=True)
    (legacy / "update.json").write_text(json.dumps({
        "version": version,
        "build": version,
        "zip_url": f"{base}/{files['portable']}",
        "notes": f"גרסה {version} יצאה. {summary}",
    }, ensure_ascii=False), encoding="utf-8")
    print(f"notes + manifests for {version} written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
