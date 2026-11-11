# רישיונות הנתונים בתיקייה הזו

| קובץ | מה בו | מקור | רישיון |
| --- | --- | --- | --- |
| `song_index.json` | שירים ופיוטים לפי מועד, עם כתיבים אחרים | קטגוריות של [ויקיפדיה העברית](https://he.wikipedia.org) ושמות פרקים בסידור ובהגדה של [ספריא](https://www.sefaria.org) | CC BY-SA 4.0 |
| `topic_lexicon.json` | המילים וצמדי המילים שמאפיינים כל מועד, במשקלי TF-IDF | ערכים בוויקיפדיה העברית וטקסטים של ספריא — כל מקור, גרסה ורישיון רשומים בקובץ עצמו (`sources`) | CC BY-SA 4.0 |
| `audioset_vocal.json` | מספרי המחלקות של AudioSet שזיהוי הווקאלי קורא („A capella”, כלי נגינה) | [AudioSet ontology](https://github.com/audioset/ontology), Google | CC BY-SA 4.0 |
| `topic_exemplars.json` | ביטויים טיפוסיים לכל מועד, למודל השפה | נכתב לפרויקט | כמו הפרויקט |
| `radio_seed.json` | רשימת ערוצי קול חי לגיבוי אופליין | קול חי מיוזיק | של בעליו |

שני הקבצים הראשונים נבנו ב-`backend/scripts/build_knowledge.py` ונגזרים מתוכן של ויקיפדיה, ולכן מופצים ברישיון [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.he): מותר להשתמש בהם, לשנות ולהפיץ, עם ייחוס לוויקיפדיה העברית ולספריא ובאותו רישיון. מספריא נלקחו רק גרסאות שמסומנות שם כנחלת הכלל, CC0, CC-BY או CC-BY-SA.

The two knowledge files are derived from Hebrew Wikipedia (CC BY-SA 4.0) and openly licensed Sefaria texts, and are distributed under CC BY-SA 4.0. Each source, version and licence is listed in `topic_lexicon.json` (`sources`).
