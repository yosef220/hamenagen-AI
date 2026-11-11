#!/usr/bin/env python3
"""Measure the knowledge layers on Hebrew song titles.

Three sets:
  * topic_eval_he.json         — descriptive titles the keyword layer misses (dev; thresholds are tuned here)
  * topic_eval_he_holdout.json — new phrasings, never used for tuning
  * topic_eval_titles.json     — real song titles as they appear in file names, with neutral songs

For each set it reports top-1 (the best topic is right, ignoring thresholds)
and precision / recall of the decision the app actually makes, for:
  lexicon      — TopicLexicon alone
  index        — SongIndex alone (only meaningful on real titles)
  embedding    — the exemplar model (when --model-dir has it)
  pipeline     — the classifier as the app runs it (index → lexicon → embedding)

With --grid it also searches the lexicon thresholds on the dev set.

Usage:
    python backend/scripts/eval_knowledge.py [--model-dir DIR] [--grid]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hamenagen.classifier import EmbeddingBackend, HybridClassifier  # noqa: E402
from hamenagen.knowledge import SongIndex, TopicLexicon  # noqa: E402

SETS = {
    "dev": "topic_eval_he.json",
    "holdout": "topic_eval_he_holdout.json",
    "titles": "topic_eval_titles.json",
}


def load(name: str, *, drop_keyword_hits: bool) -> list[dict]:
    path = HERE / SETS[name]
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    if not drop_keyword_hits:
        return items
    clf = HybridClassifier()
    return [i for i in items if not clf.keyword_topics(i["text"]) and not clf._titles.get(i["text"])]


def prf(pairs: list[tuple[str | None, str | None]]) -> dict:
    """pairs of (truth, decision)."""
    tp = fp = fn = 0
    for truth, pred in pairs:
        if truth is None:
            fp += pred is not None
        elif pred == truth:
            tp += 1
        elif pred is None:
            fn += 1
        else:
            fp += 1
            fn += 1
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"P": round(p, 3), "R": round(r, 3), "wrong": fp, "n": len(pairs)}


def top1(items: list[dict], best: list[str | None]) -> float:
    topical = [(i, b) for i, b in zip(items, best) if i["topic"]]
    return round(sum(b == i["topic"] for i, b in topical) / max(1, len(topical)), 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", help="folder with the embedding model (intfloat--multilingual-e5-small)")
    ap.add_argument("--grid", action="store_true", help="search lexicon thresholds on the dev set")
    ap.add_argument("--show", action="store_true", help="print every decision")
    args = ap.parse_args()

    lexicon = TopicLexicon.load()
    index = SongIndex.load()
    backend = None
    if args.model_dir:
        backend = EmbeddingBackend(cache_dir=args.model_dir, allow_download=False)
        if not backend.load():
            print("embedding model not loaded:", backend.load_error)
            backend = None
    print(f"lexicon: {len(lexicon.topics)} topics · index: {len(index)} songs")

    if args.grid:
        items = load("dev", drop_keyword_hits=True)
        rows = []
        cache = [(i["topic"], sorted(lexicon.scores(i["text"]).items(), key=lambda kv: -kv[1])) for i in items]
        for ms in (0.0, 0.05, 0.08, 0.1, 0.12, 0.15, 0.2, 0.25, 0.3):
            for mm in (0.0, 0.02, 0.03, 0.05, 0.07, 0.1, 0.12, 0.15, 0.2):
                pairs = []
                for truth, ranked in cache:
                    (b, s1), (_, s2) = ranked[0], ranked[1]
                    pairs.append((truth, b if s1 >= ms and s1 - s2 >= mm else None))
                rows.append((ms, mm, prf(pairs)))
        ok = [r for r in rows if r[2]["P"] >= 0.9]
        for ms, mm, m in sorted(ok, key=lambda r: -r[2]["R"])[:10]:
            print(f"  min_score {ms:.2f} min_margin {mm:.2f} → P {m['P']:.2f} R {m['R']:.2f} wrong {m['wrong']}")

    for name in SETS:
        items = load(name, drop_keyword_hits=(name != "titles"))
        if not items:
            continue
        print(f"\n== {name} ({sum(1 for i in items if i['topic'])} topical, {sum(1 for i in items if not i['topic'])} neutral)")
        lex = [lexicon.classify(i["text"]) for i in items]
        lex_best = [max(lexicon.scores(i["text"]).items(), key=lambda kv: kv[1])[0] for i in items]
        print(f"  lexicon    top-1 {top1(items, lex_best)}  decision {prf([(i['topic'], r.topic) for i, r in zip(items, lex)])}")
        idx = [index.lookup(i["text"]) for i in items]
        print(f"  index      decision {prf([(i['topic'], h.topics[0] if h else None) for i, h in zip(items, idx)])}")
        if backend is not None:
            emb = [backend.classify(i["text"]) for i in items]
            print(f"  embedding  decision {prf([(i['topic'], c.topic if c else None) for i, c in zip(items, emb)])}")
        clf = HybridClassifier(backend, lexicon=lexicon, song_index=index)
        full = [clf.classify(title=i["text"]) for i in items]
        print(f"  pipeline   decision {prf([(i['topic'], c.topic) for i, c in zip(items, full)])}")
        by_src: dict[str, int] = {}
        for c in full:
            by_src[c.source] = by_src.get(c.source, 0) + 1
        print(f"             by layer {by_src}")
        if args.show:
            for i, c in zip(items, full):
                mark = "✓" if c.topic == i["topic"] else ("·" if c.topic is None else "✗")
                print(f"    {mark} {i['text']:<34} truth={i['topic']} got={c.topic} via {c.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
