"""One singer, one name: the spellings of the same singer, unified.

Song files name their singer in many ways: "ישי ריבו", "Ishay Ribo",
"ישי ריבו." or "שוואקי" and "Yaakov Shwekey". The library groups them so a
singer appears once, the radio does not play the "same" singer twice in a
row, and a search for one spelling finds the songs under every other.

Two kinds of groups:

* **sure** — the spellings differ only in punctuation, spaces, case and
  niqqud, or all of them are names of the same known singer (the list
  below, Hebrew and English). These are unified by themselves.
* **likely** — the spellings differ in the vowel letters only (כתיב מלא and
  חסר: "שטיינמץ" and "שטינמץ"; "Yossi" and "Yosi"). These are suggested;
  the listener decides (settings: "שמות של זמרים").

The listener can always choose another spelling or keep a group apart.
Nothing is written into the files; only the name shown changes.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .text_normalize import normalize

# Known singers: the Hebrew name first, then other spellings people use.
# Our own list (public names), kept short and sure.
KNOWN: tuple[tuple[str, ...], ...] = (
    ("מרדכי בן דוד", "Mordechai Ben David", "MBD", "מ.ב.ד", "מב\"ד", "מרדכי בן-דוד"),
    ("אברהם פריד", "Avraham Fried", "Avrohom Fried", "Abraham Fried"),
    ("ישי ריבו", "Ishay Ribo", "Ishai Ribo", "Yishai Ribo"),
    ("מוטי שטיינמץ", "Motty Steinmetz", "Moti Steinmetz", "Motti Steinmetz"),
    ("ליפא שמעלצער", "Lipa Schmeltzer", "ליפא שמלצר"),
    ("בני פרידמן", "Benny Friedman"),
    ("יעקב שוואקי", "Yaakov Shwekey", "Shwekey", "שוואקי", "Yaakov Shweky"),
    ("חיים ישראל", "Haim Israel", "Chaim Israel"),
    ("דדי גראוכר", "Dedi Graucher", "דדי גרויכר"),
    ("יונתן רזאל", "Yonatan Razel", "Jonathan Razel"),
    ("אהרן רזאל", "Aharon Razel", "אהרון רזאל"),
    ("עמירן דביר", "Amiran Dvir"),
    ("אוהד מושקוביץ", "Ohad Moskowitz"),
    ("שולי רנד", "Shuli Rand"),
    ("עובדיה חממה", "Ovadia Hamama"),
    ("חנן בן ארי", "Hanan Ben Ari"),
    ("אביתר בנאי", "Evyatar Banai"),
    ("עמיר דדון", "Amir Dadon"),
    ("אודי דוידי", "Udi Davidi"),
    ("שלמה קרליבך", "Shlomo Carlebach", "Carlebach", "קרליבך", "ר' שלמה קרליבך"),
    ("בערי וובר", "Beri Weber"),
    ("יוסי גרין", "Yossi Green"),
    ("דודו פישר", "Dudu Fisher"),
    ("שלומי גרטנר", "Shloime Gertner"),
    ("שמילי אונגר", "Shmueli Ungar"),
    ("בנצי שטיין", "Benzi Stein"),
    ("שמחה פרידמן", "Simcha Friedman"),
    ("אברימי רוט", "Avremi Roth"),
    ("פיני איינהורן", "Pini Einhorn"),
    ("יהודה גרין", "Yehuda Green"),
    ("ישראל דגן", "Israel Dagan"),
    ("ישי לפידות", "Ishay Lapidot", "Yishai Lapidot"),
    ("ברוך לוין", "Baruch Levine"),
    ("מקהלת מלכות", "Malchus Choir"),
    ("מקהלת שירה", "Shira Choir"),
    ("גד אלבז", "Gad Elbaz"),
    ("מרדכי שפירא", "Mordechai Shapiro"),
    ("ג'ואי ניוקום", "Joey Newcomb"),
    ("איתן כץ", "Eitan Katz"),
    ("לוי פלקוביץ", "Levy Falkowitz"),
    ("זושא", "Zusha"),
    ("נפתלי קמפה", "Naftali Kempeh"),
    ("אהרל'ה סמט", "Ahrele Samet"),
    ("איצי ולדנר", "Itzy Waldner"),
)

_PUNCT = re.compile(r"[^\w]+", re.UNICODE)
_HEB_VOWEL_LETTERS = set("וי")
_DOUBLE = re.compile(r"(.)\1+")


def sure_key(name: str) -> str:
    """Spellings that differ only in punctuation, spaces, case and niqqud
    share this key ("ר' שלמה" and "ר שלמה", "ISHAY RIBO" and "Ishay Ribo")."""
    return _PUNCT.sub("", normalize(name or ""))


def _skeleton_word(w: str) -> str:
    if not w:
        return ""
    if any("א" <= ch <= "ת" for ch in w):
        rest = "".join(ch for ch in w[1:] if ch not in _HEB_VOWEL_LETTERS and ch != "א")
        out = w[0] + rest
    else:
        out = w[0] + re.sub(r"[aeiouy]", "", w[1:])
        out = out.replace("ck", "k").replace("ch", "h")
    return _DOUBLE.sub(r"\1", out)


def likely_key(name: str) -> str:
    """Spellings that differ in vowel letters too (כתיב מלא/חסר, Yossi/Yosi).
    Only names with enough letters left get one, so short names never pair."""
    words = [w for w in _PUNCT.sub(" ", normalize(name or "")).split() if w]
    key = " ".join(_skeleton_word(w) for w in words)
    return key if len(key.replace(" ", "")) >= 5 and len(words) >= 2 else ""


_KNOWN_BY_KEY: dict[str, str] = {}
_ALIASES: dict[str, tuple[str, ...]] = {}
_EXTRA: tuple[tuple[str, ...], ...] = ()      # the listener's own list (1.5)


def _index_known() -> None:
    _KNOWN_BY_KEY.clear()
    _ALIASES.clear()
    # The listener's list first: where it names a singer differently, it wins.
    for names in (*_EXTRA, *KNOWN):
        head = next((_KNOWN_BY_KEY[k] for k in map(sure_key, names) if k in _KNOWN_BY_KEY), names[0])
        for n in names:
            _KNOWN_BY_KEY.setdefault(sure_key(n), head)
        _ALIASES[head] = tuple(dict.fromkeys((*_ALIASES.get(head, (head,)), *names)))


_index_known()


def known(name: str) -> str | None:
    """The Hebrew name of a known singer (None when not on the list)."""
    return _KNOWN_BY_KEY.get(sure_key(name))


def known_aliases(name: str) -> tuple[str, ...]:
    """Every spelling on the list of the singer called ``name``."""
    heb = known(name)
    return _ALIASES.get(heb, ()) if heb else ()


def set_extra(lists) -> int:
    """Use the listener's own list of singers along with ours. Each entry is
    the name to show, then other spellings of the same singer."""
    global _EXTRA
    clean = []
    for names in lists or ():
        names = tuple(dict.fromkeys(str(n).strip()[:120] for n in names if str(n).strip()))
        if names and sure_key(names[0]):
            clean.append(names)
    _EXTRA = tuple(clean[:20000])
    _index_known()
    return len(_EXTRA)


def extra() -> tuple[tuple[str, ...], ...]:
    return _EXTRA


def parse_list(text: str) -> list[tuple[str, ...]]:
    """A list of singers the listener brings, as a CSV/TSV/plain text file
    (on each line: the name to show, then other spellings, separated by
    commas, tabs, ``|`` or ``=``) or JSON (a list of lists, or
    ``{"name": ["spelling", ...]}``). Lines that name the same spelling
    become one singer; the first name seen is the one shown."""
    import csv
    import io
    import json

    text = (text or "").lstrip("\ufeff")
    rows: list[list[str]] = []
    stripped = text.strip()
    if stripped[:1] in "[{":
        data = json.loads(stripped)
        if isinstance(data, dict):
            for k, v in data.items():
                rows.append([k, *(v if isinstance(v, list) else [v])])
        elif isinstance(data, list):
            for v in data:
                if isinstance(v, list):
                    rows.append([str(x) for x in v])
                elif isinstance(v, dict):
                    name = v.get("name") or v.get("שם")
                    rows.append([name, *(v.get("aliases") or v.get("spellings") or [])])
                elif isinstance(v, str):
                    rows.append([v])
    else:
        first = stripped.splitlines()[0] if stripped else ""
        delim = max(("\t", ",", "|", "=", ";"), key=first.count) if first else ","
        for row in csv.reader(io.StringIO(text), delimiter=delim):
            rows.append(row)
    # Join rows that share a spelling (a list of "spelling,name" pairs, too).
    groups: list[list[str]] = []
    where: dict[str, int] = {}
    for row in rows:
        names = [str(n).strip().strip('"') for n in row if n and str(n).strip()]
        names = [n for n in names if sure_key(n) and len(n) <= 120]
        if not names or names[0].lower() in {"name", "שם", "singer", "זמר", "source", "מקור"}:
            continue
        hits = sorted({where[sure_key(n)] for n in names if sure_key(n) in where})
        if hits:
            g = hits[0]
            for other in hits[1:]:
                groups[g].extend(groups[other])
                for n in groups[other]:
                    where[sure_key(n)] = g
                groups[other] = []
        else:
            g = len(groups)
            groups.append([])
        for n in names:
            groups[g].append(n)
            where[sure_key(n)] = g
    out = []
    for g in groups:
        names = list(dict.fromkeys(g))
        if names:
            out.append(tuple(names))
    return out


@dataclass
class Group:
    key: str                    # stable id of the group (for the listener's choices)
    name: str                   # the name shown
    variants: list[tuple[str, int]] = field(default_factory=list)   # (spelling, songs)
    sure: bool = True
    applied: bool = True        # False: a suggestion waiting for the listener
    known: bool = False

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "sure": self.sure, "applied": self.applied,
                "known": self.known, "variants": [{"name": n, "count": c} for n, c in self.variants],
                "songs": sum(c for _, c in self.variants)}


def _best_spelling(variants: list[tuple[str, int]]) -> str:
    """The most common spelling; on a tie, Hebrew, then the cleaner one."""
    def rank(v):
        name, count = v
        heb = any("א" <= ch <= "ת" for ch in name)
        return (-count, not heb, sum(not ch.isalnum() and ch != " " for ch in name), len(name))
    return sorted(variants, key=rank)[0][0]


def build(counts: dict[str, int], choices: dict | None = None) -> tuple[dict[str, str], list[Group]]:
    """From ``{spelling: songs}`` in the library and the listener's
    ``choices`` (``{group key: {"name": str|None, "apart": bool}}``), return
    the map spelling → shown name (only spellings that change) and every
    group with more than one spelling."""
    choices = choices or {}
    # 1. sure groups: the same singer on the known list, or the same sure key.
    sure: dict[str, list[tuple[str, int]]] = {}
    for name, count in counts.items():
        if not name or not name.strip():
            continue
        heb = known(name)
        key = f"k:{sure_key(heb)}" if heb else f"s:{sure_key(name)}"
        if key in ("s:", "k:"):
            continue
        sure.setdefault(key, []).append((name, count))
    # 2. likely groups: sure groups with a spelling of the same skeleton
    #    (a known singer brings every spelling on the list).
    parent = {k: k for k in sure}

    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    first_by_skel: dict[str, str] = {}
    for key, variants in sure.items():
        names = [v[0] for v in variants] + list(known_aliases(variants[0][0]))
        for skel in {likely_key(n) for n in names} - {""}:
            other = first_by_skel.setdefault(skel, key)
            if other != key:
                parent[root(key)] = root(other)
    clusters: dict[str, list[str]] = {}
    for key in sure:
        clusters.setdefault(root(key), []).append(key)

    groups: list[Group] = []
    mapping: dict[str, str] = {}
    merged_into: dict[str, str] = {}
    for keys in clusters.values():
        if len(keys) < 2:
            continue
        keys.sort()
        gkey = "l:" + "|".join(keys)
        variants = sorted((v for k in keys for v in sure[k]), key=lambda v: -v[1])
        choice = choices.get(gkey) or {}
        is_known = any(k.startswith("k:") for k in keys)
        name = choice.get("name") or next((known(v[0]) for v in variants if known(v[0])), None) or _best_spelling(variants)
        applied = bool(choice.get("merge")) and not choice.get("apart")
        groups.append(Group(gkey, name, variants, sure=False, applied=applied, known=is_known))
        if applied:
            for k in keys:
                merged_into[k] = name
    for key, variants in sure.items():
        variants.sort(key=lambda v: -v[1])
        choice = choices.get(key) or {}
        is_known = key.startswith("k:")
        name = merged_into.get(key) or choice.get("name") or (known(variants[0][0]) if is_known else None) \
            or _best_spelling(variants)
        apart = bool(choice.get("apart")) and key not in merged_into
        if len(variants) > 1:
            groups.append(Group(key, name, variants, sure=True, applied=not apart, known=is_known))
        if apart:
            continue
        # A known singer whose files all use one English spelling keeps it,
        # unless the listener chose a name: only spellings that differ unify.
        if len(variants) == 1 and key not in merged_into and not choice.get("name"):
            continue
        for spelling, _ in variants:
            if spelling != name:
                mapping[spelling] = name
    groups.sort(key=lambda g: (g.applied, -sum(c for _, c in g.variants)))
    return mapping, groups


def expand_query(query: str, mapping: dict[str, str], shown: set[str] | frozenset = frozenset()) -> str:
    """A search for one spelling of a singer, written as the name shown in
    the library (``shown``), so it finds the songs under every spelling:
    "Ishay Ribo" → "ישי ריבו", and the other way when the files are in
    English."""
    norm_q = f" {normalize(query)} "

    def swap(spelling: str, name: str) -> None:
        nonlocal norm_q
        n, to = normalize(spelling), normalize(name)
        if n and n != to and f" {n} " in norm_q:
            norm_q = norm_q.replace(f" {n} ", f" {to} ")

    for spelling, name in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        swap(spelling, name)
    by_key = {sure_key(n): n for n in shown}
    for names in KNOWN:
        here = next((by_key[sure_key(n)] for n in names if sure_key(n) in by_key), None)
        if here is None:
            continue
        for alias in sorted(names, key=len, reverse=True):
            swap(alias, here)
    return norm_q.strip()


def counts_of(names) -> dict[str, int]:
    return dict(Counter(n for n in names if n))
