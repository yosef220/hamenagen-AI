#!/usr/bin/env python3
"""Compare embedding models on the classifier's real job: placing Hebrew song
titles that no lexicon keyword catches (topic_eval_he.json).

For every model it reports
  * top-1 accuracy — the nearest topic prototype is the right topic;
  * the best operating point — the similarity threshold with the highest F1,
    counting a wrong topic and any topic on a neutral song as errors;
  * the threshold for precision ≥ 0.9 and the recall left at it;
  * size on disk and the time to embed one title on this CPU.

Two kinds of runner:
  st:<hf-id>     sentence-transformers (PyTorch) with the model's own pooling
  onnx:<hf-id>:<file>:<pooling>   onnxruntime + tokenizers, as the app runs it

Usage:
    python benchmark_models.py st:intfloat/multilingual-e5-small onnx:ibm-granite/...
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hamenagen.classifier import HybridClassifier  # noqa: E402

# Prefixes some models expect (symmetric use: the same on both sides unless
# the model distinguishes queries from documents).
QUERY_PREFIX = {
    "intfloat/multilingual-e5-small": "query: ",
    "intfloat/multilingual-e5-base": "query: ",
    "intfloat/multilingual-e5-large": "query: ",
}
DOC_PREFIX = {
    "intfloat/multilingual-e5-small": "query: ",
    "intfloat/multilingual-e5-base": "query: ",
    "intfloat/multilingual-e5-large": "query: ",
}
# The 0.1 method: one descriptive sentence per topic (kept to compare against).
PROTOTYPES_01 = {
    "שבת": "שיר לשבת קודש, זמירות שבת, מנוחה, קבלת שבת",
    "ראש השנה": "שיר לראש השנה, תקיעת שופר, שנה טובה ומתוקה, יום הדין",
    "יום כיפור": "שיר ליום הכיפורים, תפילת נעילה, סליחה ומחילה",
    "חנוכה": "שיר לחנוכה, נרות, מכבים, נס פך השמן",
    "אלול": "שיר לחודש אלול, סליחות, תשובה, התעוררות רוחנית",
    "סוכות": "שיר לחג הסוכות, סוכה, ארבעת המינים, שמחת בית השואבה",
    "פסח": "שיר לחג הפסח, יציאת מצרים, הגדה, ליל הסדר",
    "פורים": "שיר לפורים, מגילת אסתר, משתה ושמחה",
    "שבועות": "שיר לחג השבועות, מתן תורה",
    "ל״ג בעומר": "שיר לל״ג בעומר, רבי שמעון בר יוחאי, מירון והדלקה",
    "חתונה": "שיר לחתונה ולשמחות, חתן וכלה, ריקודים",
    "ירושלים": "שיר על ירושלים עיר הקודש והכותל",
    "אמונה": "שיר על אמונה וביטחון בהשם ותפילה",
}
INSTRUCT = "Instruct: Classify which Jewish holiday or theme a Hebrew song title belongs to\nQuery: "


EVAL_FILE = "topic_eval_he.json"


def load_items() -> list[dict]:
    data = json.loads((HERE / EVAL_FILE).read_text(encoding="utf-8"))
    clf = HybridClassifier()
    kept, dropped = [], []
    for item in data["items"]:
        hits = clf.keyword_topics(item["text"])
        (dropped if hits else kept).append((item, hits))
    for item, hits in dropped:
        print(f"  (skipped, the lexicon already catches it: {item['text']} → {hits})")
    return [i for i, _ in kept]


class STRunner:
    def __init__(self, model_id: str):
        from sentence_transformers import SentenceTransformer

        self.model_id = model_id
        t0 = time.time()
        self.model = SentenceTransformer(model_id, device="cpu", trust_remote_code=False)
        self.load_s = time.time() - t0
        prompts = getattr(self.model, "prompts", {}) or {}
        self.query_prompt = None
        self.doc_prompt = None
        for name in ("classification", "Classification", "query"):
            if name in prompts:
                self.query_prompt = prompts[name]
                break
        for name in ("document", "passage"):
            if name in prompts:
                self.doc_prompt = prompts[name]
                break
        if "qwen3" in model_id.lower() or "harrier" in model_id.lower():
            self.query_prompt = INSTRUCT
            self.doc_prompt = ""
        self.size_mb = folder_size_mb(self.model)

    def embed(self, texts: list[str], *, doc: bool) -> np.ndarray:
        prefix = (DOC_PREFIX if doc else QUERY_PREFIX).get(self.model_id, "")
        prompt = self.doc_prompt if doc else self.query_prompt
        texts = [prefix + t for t in texts]
        return self.model.encode(texts, prompt=prompt or None, normalize_embeddings=True, convert_to_numpy=True)


class ONNXRunner:
    def __init__(self, model_id: str, onnx_file: str, pooling: str):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        self.model_id = model_id
        t0 = time.time()
        path = hf_hub_download(model_id, onnx_file)
        try:
            hf_hub_download(model_id, onnx_file + "_data")
        except Exception:
            pass
        tok_path = hf_hub_download(model_id, "tokenizer.json")
        self.tokenizer = Tokenizer.from_file(tok_path)
        self.tokenizer.enable_truncation(256)
        self.session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.pooling = pooling
        self.load_s = time.time() - t0
        self.size_mb = round(Path(path).stat().st_size / 1e6)

    def embed(self, texts: list[str], *, doc: bool) -> np.ndarray:
        prefix = (DOC_PREFIX if doc else QUERY_PREFIX).get(self.model_id, "")
        out = []
        for t in texts:
            enc = self.tokenizer.encode(prefix + t)
            ids = np.array([enc.ids], dtype=np.int64)
            mask = np.array([enc.attention_mask], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            feed = {k: v for k, v in feed.items() if k in self.inputs}
            hidden = self.session.run(None, feed)[0]
            if hidden.ndim == 2:  # already pooled
                vec = hidden[0]
            elif self.pooling == "cls":
                vec = hidden[0, 0]
            else:
                m = mask[0][:, None].astype(np.float32)
                vec = (hidden[0] * m).sum(0) / max(m.sum(), 1.0)
            out.append(vec / (np.linalg.norm(vec) + 1e-9))
        return np.array(out)


def folder_size_mb(model) -> int:
    try:
        path = Path(model._model_card_vars.get("model_path", "")) if hasattr(model, "_model_card_vars") else None
    except Exception:
        path = None
    try:
        from huggingface_hub import scan_cache_dir

        info = scan_cache_dir()
        for repo in info.repos:
            if repo.repo_id == model.model_card_data.base_model or repo.repo_id in str(getattr(model, "_first_module")()):
                return round(repo.size_on_disk / 1e6)
    except Exception:
        pass
    return -1


EXEMPLARS = json.loads((HERE.parent / "hamenagen" / "data" / "topic_exemplars.json").read_text(encoding="utf-8"))["topics"]
METHOD = "exemplars"  # or "prototype": one descriptive sentence per topic (0.1 behaviour)


def evaluate(runner, items: list[dict], method: str = METHOD) -> dict:
    t0 = time.time()
    vecs = runner.embed([i["text"] for i in items], doc=False)
    per_item_ms = (time.time() - t0) / len(items) * 1000
    if method == "prototype":
        keys = list(PROTOTYPES_01)
        protos = runner.embed([PROTOTYPES_01[k] for k in keys], doc=True)
        sims = vecs @ protos.T
    else:
        keys = list(EXEMPLARS)
        sims = np.zeros((len(items), len(keys)))
        for j, k in enumerate(keys):
            ex = runner.embed(EXEMPLARS[k], doc=True)
            sims[:, j] = (vecs @ ex.T).max(1)
    best = sims.argmax(1)
    best_sim = sims.max(1)
    truth = [i["topic"] for i in items]
    topical = [n for n, t in enumerate(truth) if t]
    top1 = sum(keys[best[n]] == truth[n] for n in topical) / len(topical)

    def score(th):
        tp = fp = fn = 0
        for n, t in enumerate(truth):
            assigned = keys[best[n]] if best_sim[n] >= th else None
            if t is None:
                fp += assigned is not None
            elif assigned == t:
                tp += 1
            elif assigned is None:
                fn += 1
            else:
                fp += 1
                fn += 1
        prec = tp / (tp + fp) if tp + fp else 1.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        return prec, rec, f1

    grid = np.round(np.arange(0.0, 1.0, 0.01), 2)
    scored = [(th, *score(th)) for th in grid]
    best_th, bp, br, bf = max(scored, key=lambda r: r[3])
    safe = [r for r in scored if r[1] >= 0.9]
    safe_th, sp, sr, _ = max(safe, key=lambda r: r[2]) if safe else (None, 0, 0, 0)
    return {
        "top1": round(top1, 3),
        "best_f1": round(bf, 3), "best_th": float(best_th), "best_p": round(bp, 3), "best_r": round(br, 3),
        "p90_th": safe_th, "p90_recall": round(sr, 3),
        "ms_per_title": round(per_item_ms, 1),
        "load_s": round(runner.load_s, 1),
        "size_mb": runner.size_mb,
    }


def main(specs: list[str]) -> int:
    global METHOD
    if specs and specs[0].startswith("--method="):
        METHOD = specs.pop(0).split("=", 1)[1]
    if specs and specs[0].startswith("--set="):
        global EVAL_FILE
        EVAL_FILE = specs.pop(0).split("=", 1)[1]
    items = load_items()
    print(f"{len(items)} items ({sum(1 for i in items if i['topic'])} topical, {sum(1 for i in items if not i['topic'])} neutral)\n")
    rows = []
    for spec in specs:
        kind, rest = spec.split(":", 1)
        try:
            if kind == "st":
                runner = STRunner(rest)
            else:
                model_id, onnx_file, pooling = rest.split(":")
                runner = ONNXRunner(model_id, onnx_file, pooling)
            res = evaluate(runner, items)
        except Exception as exc:  # keep going with the other models
            print(f"{spec}: FAILED — {exc}")
            continue
        rows.append((spec, res))
        print(spec, json.dumps(res, ensure_ascii=False), flush=True)
    print("\nmodel | top-1 | best F1 (th, P, R) | recall @P≥0.9 (th) | ms/title | MB")
    for spec, r in sorted(rows, key=lambda x: -x[1]["best_f1"]):
        print(f"{spec} | {r['top1']:.2f} | {r['best_f1']:.2f} ({r['best_th']}, {r['best_p']:.2f}, {r['best_r']:.2f}) | "
              f"{r['p90_recall']:.2f} ({r['p90_th']}) | {r['ms_per_title']} | {r['size_mb']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
