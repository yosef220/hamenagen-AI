"""Write the release notes and the update manifests for a tagged release.

    python scripts/release_notes.py v1.0.0 owner/repo dist

Produces, next to the built files in ``dist``:

* ``RELEASE_NOTES.md``  — the Hebrew release page, with real file sizes
* ``update.json``       — what 1.x installs check (releases/latest/download),
  with each edition's parts for the smart update (sizes and checksums of
  dist/parts/hamenagen-part-*.zip, from parts-<edition>.json)
* ``legacy/update.json``— the old 0.1 format, so 0.1 installs see 1.0
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path


# What is new, by version (major.minor, or a full version for a fix on top of
# it). The newest version's list goes on the release page; its one-line
# summary goes into update.json.
WHATS_NEW: dict[str, tuple[str, list[str]]] = {
    "1.4": (
        "בקשה בקול גם בלי אינטרנט, רדיו המנגן מהשירים שלכם, עוצמה אחידה, דיבור ושיעורים בנפרד "
        "ושם אחד לכל זמר.",
        [
            "**בקשה בקול** — לוחצים על המיקרופון שליד שורת הבקשה (או Ctrl+M) ואומרים מה לשמוע. "
            "הזיהוי בעברית נעשה במחשב עצמו, גם בלי אינטרנט, במודל של ivrit.ai. ההקלטה לא נשמרת ולא נשלחת.",
            "**רדיו המנגן** — תחנה שמתנגנת בלי סוף מהשירים שבמחשב: לפי השעה ביום (בוקר טוב, לילה רך…) "
            "ולפי הלוח העברי, או „רדיו מהשיר הזה” מתפריט השיר. שיר ששמעתם בשעות האחרונות לא חוזר, "
            "ואותו זמר לא מתנגן פעמיים ברצף.",
            "**עוצמה אחידה ודילוג על שקט** — שיר שהוקלט חזק מתנגן מעט בשקט, ושקט בתחילת שיר ובסופו לא מתנגן.",
            "**דיבור ושיעורים בנפרד** — הרצאות, שיעורים וסיפורים מזוהים מהשמע ומהשם, מקבלים לשונית בספרייה, "
            "ולא נכנסים לערבובים, לסטים ולרדיו.",
            "**„לא אהוב” ותיקיות בנפרד** — שיר שלא רוצים לשמוע בערבובים, ותיקייה (למשל שירי ילדים) "
            "שמתנגנת רק כשבוחרים בה.",
            "**שם אחד לכל זמר** — „ישי ריבו” ו-„Ishay Ribo” הם אותו זמר: מוצגים בשם אחד, והחיפוש מוצא את שניהם. "
            "כתיב מלא וחסר מוצע לאיחוד בהגדרות.",
            "**בקשות לפי אווירה** — „משהו רגוע”, „שעה של שירים שקטים”, „שירים מרגשים”, „שירי ילדים”, "
            "לפי מה שהמנגן שמע בכל שיר.",
        ],
    ),
    "1.3.1": (
        "הגרסה הניידת נפתחת מהר בהרבה ומוצעת בתיקיית התוכנות, החיפוש בגוגל נפתח בתוך חלון המנגן, "
        "והעדכון החכם מתוקן.",
        [
            "**הגרסה הניידת נפתחת מהר בהרבה** — 7-Zip פותח אותה על כל הליבות של המחשב, במקום פתיחה איטית "
            "על ליבה אחת שכתבה כל קובץ פעמיים.",
            "**בתיקיית התוכנות** — הגרסה הניידת מציעה את תיקיית התוכנות של המשתמש ב-Windows "
            "(ולא את שולחן העבודה), בלי צורך בהרשאת מנהל. קיצור דרך מופיע בשולחן העבודה, "
            "ואפשר עדיין לבחור כל תיקייה, גם בדיסק נייד.",
            "**החיפוש בגוגל בתוך המנגן** — בלי חלון נוסף: גוגל נפתח בתוך החלון, עם כפתור „חזרה למנגן”, "
            "חיפוש חדש ואחורה וקדימה. לחיצה על תוצאה מיוטיוב מחזירה את השיר למקום שממנו חיפשת.",
            "**העדכון החכם מתוקן** — ב-1.3.0 חלק מקבצי העדכון כללו קבצים זמניים של Python, והתוכנה הייתה "
            "דוחה אותם. מעכשיו כל חלק נבדק בבנייה בדיוק כמו שהתוכנה תבדוק אותו. ממחשב עם 1.3.0 העדכון "
            "ל-1.3.1 מוריד כ-60MB פעם אחת, ומשם והלאה כמה מגה-בייט.",
        ],
    ),
    "1.3": (
        "עדכון חכם שמוריד רק מה שהשתנה, כל הורדה בקובץ אחד, מצב שבת וחג, סטים לשמחות, רשימות שמורות ופרשת השבוע.",
        [
            "**עדכון חכם** — מכאן והלאה העדכון מוריד רק את החלקים שהשתנו (בדרך כלל כמה מגה-בייט), "
            "והמודל של הגרסה האופליין לא יורד שוב. „לעדכן עכשיו”, והמנגן נסגר לרגע וחוזר מעודכן. "
            "אם משהו נכשל — הגרסה הקודמת נשארת.",
            "**כל הורדה בקובץ אחד** — התקנה רגילה, התקנה עם המודל (אופליין), וגרסה ניידת (גם עם המודל) "
            "שנפתחת פעם אחת לתיקייה שבוחרים. בלי ZIP של אלפי קבצים.",
            "**מצב שבת וחג** — לפי זמני העיר: המוזיקה נחלשת ונעצרת לפני הדלקת נרות, ו„שבת שלום” מוצג עד צאת "
            "השבת או החג. הזמנים מזמנים טובא (כתר תורה), אחר כך מ-Hebcal, ובלי אינטרנט — מחישוב במחשב.",
            "**סטים** — „תפעיל לי סט שירים לברית”, „סט לשמחה”, „מוזיקה לריקודים”: סט שמתחמם, מגיע לשיא ונרגע, "
            "עם מעבר רך בין השירים. המנגן מקשיב ברקע לקצב ולאנרגיה של כל שיר. כשחסרים שירים — מיוטיוב, "
            "בסגנון של הזמרים שאתה שומע, להשמעה בלי לשמור או להורדה.",
            "**רשימות השמעה שמורות** — בשם, עם גרירה לסידור; „תשמיע את הרשימה שבת בבוקר”.",
            "**כל שיר פעם אחת** — שיר שנמצא בכמה תיקיות או פורמטים מוצג פעם אחת, בעותק הטוב ביותר.",
            "**בלוח** — פרשת השבוע (מחושבת בלי אינטרנט), ראש חודש, ט״ו בשבט ושמחת תורה.",
            "**חיפוש בגוגל בתוך המנגן** — כשהרשת חוסמת חיפוש ביוטיוב: גוגל עם „יוטיוב”, ולחיצה על תוצאה "
            "מביאה את השיר למנגן.",
            "**השלמת פרטים ותמונות לכל הספרייה** — ברקע, ורק כשההתאמה ודאית.",
        ],
    ),
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
    """(the version the list is for, one-line summary, bullet list): the
    version's own list if it has one, otherwise its major.minor's."""
    if version in WHATS_NEW:
        summary, bullets = WHATS_NEW[version]
        return version, summary, bullets
    key = ".".join(version.split(".")[:2])
    minors = [k for k in WHATS_NEW if k.count(".") == 1]
    summary, bullets = WHATS_NEW.get(key, WHATS_NEW[max(minors, key=lambda k: tuple(map(int, k.split("."))))])
    return key, summary, bullets


def earlier_list(version: str) -> tuple[str, list[str]] | None:
    """For a fix version (1.3.1), its minor version's list, shown under its own."""
    key = ".".join(version.split(".")[:2])
    if version in WHATS_NEW and key in WHATS_NEW and key != version:
        return key, WHATS_NEW[key][1]
    return None


def size_text(n: int) -> str:
    mb = n / (1024 * 1024)
    return f"{mb:,.0f}MB" if mb >= 10 else f"{mb:.1f}MB"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def parts_for(dist: Path, base: str) -> dict:
    """Every edition's parts, with the address, size and checksum of each ZIP."""
    out: dict = {}
    for manifest_file in sorted((dist / "parts").glob("parts-*.json")):
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        for name, part in manifest["parts"].items():
            z = dist / "parts" / part["file"]
            if not z.exists():
                raise SystemExit(f"missing part file: {z}")
            part.update(url=f"{base}/{part['file']}", size=z.stat().st_size, sha256=sha256_of(z))
        out[manifest["edition"]] = manifest
    return out


def main(tag: str, repo: str, folder: str) -> int:
    version = tag.lstrip("v")
    dist = Path(folder)
    base = f"https://github.com/{repo}/releases/download/{tag}"
    page = f"https://github.com/{repo}/releases/tag/{tag}"

    files = {
        "setup_exe": f"Hamenagen-{version}-Setup.exe",
        "setup": f"Hamenagen-{version}-Setup.zip",
        "setup_offline_exe": f"Hamenagen-{version}-Setup-Offline.exe",
        "setup_offline": f"Hamenagen-{version}-Setup-Offline.zip",
        "portable_exe": f"Hamenagen-{version}-Portable.exe",
        "portable": f"Hamenagen-{version}-Portable.zip",
        "offline_exe": f"Hamenagen-{version}-Portable-Offline.exe",
        "offline": f"Hamenagen-{version}-Portable-Offline.zip",
    }
    missing = [v for v in files.values() if not (dist / v).exists()]
    if missing:
        print("missing:", ", ".join(missing), file=sys.stderr)
        return 1
    sizes = {k: size_text((dist / v).stat().st_size) for k, v in files.items()}
    parts = parts_for(dist, base)

    def row(key: str, title: str, text: str) -> str:
        return (f"| **[{files[key + '_exe']}]({base}/{files[key + '_exe']})** | {title}: {text} "
                f"| {sizes[key + '_exe']} | [ZIP]({base}/{files[key]}) |")

    minor, summary, bullets = whats_new(version)
    bullet_text = "\n".join(f"- {b}" for b in bullets)
    earlier = earlier_list(version)
    if earlier:
        bullet_text += f"\n\n### ומה שנוסף ב-{earlier[0]}\n" + "\n".join(f"- {b}" for b in earlier[1])
    notes = f"""## המנגן {version}

נגן מוזיקה קהילתי חכם ל-Windows: מבין בקשות בעברית חופשית, מכיר את הלוח העברי, ועובד בלי אינטרנט.

### איזה קובץ להוריד
כל אחד מהם הוא קובץ אחד. אם סינון הרשת לא מאפשר להוריד EXE גדול — אותו קובץ בתוך ZIP.

| קובץ | למי זה מתאים | גודל | גם כ-ZIP |
| --- | --- | --- | --- |
{row("setup", "התקנה רגילה", "קיצור דרך בשולחן העבודה ובתפריט התחל, והסרה מהגדרות Windows. מודל הסיווג יורד בפעם הראשונה שיש אינטרנט (פעם אחת).")}
{row("setup_offline", "התקנה עם המודל", "למחשב בלי אינטרנט: הכל בפנים, כולל מודל הסיווג.")}
{row("portable", "גרסה ניידת", "בלי התקנה: הקובץ נפתח פעם אחת לתיקייה (מוצעת תיקיית התוכנות שלך, ואפשר לבחור כל תיקייה), והמנגן רץ ממנה. הספרייה נשמרת בתיקייה, כך שאפשר להעביר אותה.")}
{row("offline", "גרסה ניידת עם המודל", "כמו הניידת, עם מודל הסיווג בפנים — בלי אינטרנט בכלל.")}

הגרסאות המותקנות שומרות את הספרייה ב-`%APPDATA%\\Hamenagen`; הניידות — בתיקייה `data` שליד התוכנה.

### עדכונים
מגרסה 1.3 העדכון מוריד רק את החלקים של התוכנה שהשתנו — בדרך כלל כמה מגה-בייט — והמודל לא יורד שוב.
מגרסה קודמת (1.2 ומטה) מורידים את 1.3 פעם אחת בשלמותה.

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
            # Installs up to 1.2 open this address; it is one file (a ZIP
            # holding the one-file EXE of their edition).
            "downloads": {
                "portable": f"{base}/{files['portable']}",
                "offline": f"{base}/{files['offline']}",
                "setup": f"{base}/{files['setup']}",
                "setup-offline": f"{base}/{files['setup_offline']}",
            },
            # From 1.3: the parts of each edition, for the smart update.
            "parts": parts,
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
    print(f"notes + manifests for {version} written ({', '.join(sorted(parts))} with parts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
