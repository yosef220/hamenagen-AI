"""Hybrid topic classifier (spec §8.2).

Order of resolution, from most to least confident:

1. **Curated song-title override** — exact known titles (e.g. "מנוחה ושמחה"
   → שבת) even when the title carries no keyword.
2. **Curated keyword match** — a strong topic keyword appears as a token in
   the song's combined text.
3. **Local embedding model (optional)** — for songs the curated layer does
   not cover, a small local multilingual embedding model compares the song
   text with typical phrases of every topic and picks the closest one when
   it is close enough and clearly ahead. This layer is *optional*: if the
   model is not installed the classifier simply skips it, preserving
   offline-first behaviour. See :class:`EmbeddingBackend`.

The classifier returns a :class:`Classification` with the topic (or ``None``)
and the layer that produced it, which is useful both for debugging and for
deciding how much to trust the result.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import topics as topics_mod
from .text_normalize import contains_phrase, normalize


@dataclass(frozen=True)
class Classification:
    topic: str | None
    source: str          # "title" | "keyword" | "artist" | "embedding" | "none"
    confidence: float    # 0..1
    tags: tuple[str, ...] = ()  # further topics the song also belongs to


# The model the embedding layer uses, chosen by backend/scripts/benchmark_models.py
# on Hebrew song titles that no lexicon keyword catches (November 2026):
# multilingual-e5-small with typical phrases per topic beat the 0.1 model
# (paraphrase-multilingual-MiniLM-L12-v2) and the newest small models of 2026.
# Pinned to one revision so every install embeds exactly the same way.
MODELS: dict[str, dict] = {
    "intfloat/multilingual-e5-small": {
        "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
        "files": ["onnx/model.onnx", "tokenizer.json"],
        "prefix": "query: ",
        "pooling": "mean",
        "threshold": 0.91,   # similarity to the closest typical phrase
        "margin": 0.01,      # ahead of the second-best topic by at least this
    },
}
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
_HF = "https://huggingface.co/{model}/resolve/{revision}/{file}"
_EXEMPLARS_FILE = Path(__file__).with_name("data") / "topic_exemplars.json"

DownloadHook = Callable[[dict], None]


def load_exemplars() -> dict[str, list[str]]:
    """Typical phrases per topic (see data/topic_exemplars.json)."""
    try:
        return json.loads(_EXEMPLARS_FILE.read_text(encoding="utf-8"))["topics"]
    except Exception:
        return {}


def model_folder(cache_dir: str | Path, model_name: str) -> Path:
    return Path(cache_dir) / model_name.replace("/", "--")


def download_model(
    model_name: str,
    cache_dir: str | Path,
    *,
    on_progress: DownloadHook | None = None,
    timeout: float = 30.0,
) -> Path:
    """Fetch the model's files once into ``cache_dir`` (resumable, atomic).

    Used on first run when online, and by scripts/prepare_model.py to put the
    model inside the offline edition.
    """
    spec = MODELS[model_name]
    folder = model_folder(cache_dir, model_name)
    files = spec["files"]
    for n, name in enumerate(files, 1):
        target = folder / name
        if target.exists() and target.stat().st_size > 0:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        url = _HF.format(model=model_name, revision=spec["revision"], file=name)
        partial = target.with_suffix(target.suffix + ".part")
        have = partial.stat().st_size if partial.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": "hamenagen"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed host
            if have and resp.status != 206:
                have = 0  # the server ignored the range: start over
            total = int(resp.headers.get("Content-Length") or 0) + have
            mode = "ab" if have else "wb"
            done = have
            last = 0.0
            with open(partial, mode) as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if on_progress and time.time() - last > 0.5:
                        last = time.time()
                        on_progress({"file": name, "index": n, "files": len(files),
                                     "downloaded": done, "total": total})
        partial.replace(target)
    (folder / "model.json").write_text(
        json.dumps({"model": model_name, "revision": spec["revision"]}), encoding="utf-8"
    )
    return folder


class EmbeddingBackend:
    """Optional local-embedding topic backend (ONNX Runtime, no PyTorch).

    The model is a small multilingual sentence-embedding model. A song's text
    is compared with *typical phrases* of every topic (symbols, customs,
    people, liturgy — data/topic_exemplars.json) and the closest phrase
    decides, when it is close enough and clearly ahead of the next topic.
    That reaches titles such as "פך שמן קטן" or "אפיקומן" that carry no
    lexicon keyword.

    The files come with the offline edition, or download once on first run
    with a network (pinned revision); afterwards everything runs offline. If
    ONNX Runtime or the files are missing, :attr:`available` stays ``False``
    and :meth:`classify` returns ``None`` — the hybrid classifier then falls
    through to the curated lexicon, so nothing breaks offline.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        threshold: float | None = None,
        cache_dir: str | None = None,
        allow_download: bool = True,
    ):
        self.model_name = model_name
        spec = MODELS.get(model_name, {})
        self.threshold = spec.get("threshold", 0.9) if threshold is None else threshold
        self.margin = spec.get("margin", 0.0)
        self.prefix = spec.get("prefix", "")
        self.cache_dir = cache_dir
        self.allow_download = allow_download
        self._session = None
        self._tokenizer = None
        self._inputs: set[str] = set()
        self._np = None
        self._matrix = None          # (phrases, dim) normalised exemplar vectors
        self._phrase_topic: list[int] = []
        self._topics: list[str] = []
        self._lock = threading.Lock()
        self.available = False
        self.load_error: str | None = None
        self.on_download: DownloadHook | None = None

    # -- files -------------------------------------------------------------
    def _folder(self) -> Path | None:
        return model_folder(self.cache_dir, self.model_name) if self.cache_dir else None

    def _cache_has_model(self) -> bool:
        folder = self._folder()
        spec = MODELS.get(self.model_name)
        if folder is None or spec is None:
            return False
        return all((folder / f).exists() for f in spec["files"])

    # -- loading -----------------------------------------------------------
    def load(self) -> bool:
        """Load the model (downloading it once if needed and allowed)."""
        if self._session is not None:
            return True
        with self._lock:  # another thread may have loaded it while we waited
            if self._session is not None:
                return True
            try:
                if self.model_name not in MODELS:
                    raise ValueError(f"unknown model: {self.model_name}")
                if not self.cache_dir:
                    raise ValueError("no folder for the model")
                if not self._cache_has_model():
                    if not self.allow_download:
                        raise FileNotFoundError("the model is not installed")
                    download_model(self.model_name, self.cache_dir, on_progress=self.on_download)
                import numpy as np
                import onnxruntime as ort  # type: ignore
                from tokenizers import Tokenizer  # type: ignore

                folder = self._folder()
                options = ort.SessionOptions()
                options.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) // 2))
                session = ort.InferenceSession(
                    str(folder / "onnx" / "model.onnx"), options, providers=["CPUExecutionProvider"]
                )
                tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
                tokenizer.enable_truncation(256)
                self._np = np
                self._session = session
                self._tokenizer = tokenizer
                self._inputs = {i.name for i in session.get_inputs()}
                self._build_exemplars()
                self.available = True
                self.load_error = None
                return True
            except Exception as exc:  # package, files or network unavailable
                self._session = None
                self.load_error = str(exc)
                self.available = False
                return False

    def _embed(self, texts: list[str]):
        np = self._np
        out = []
        for text in texts:
            enc = self._tokenizer.encode(self.prefix + text)
            ids = np.array([enc.ids], dtype=np.int64)
            mask = np.array([enc.attention_mask], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
            feed = {k: v for k, v in feed.items() if k in self._inputs}
            hidden = self._session.run(None, feed)[0][0]
            weights = mask[0][:, None].astype(np.float32)
            vec = (hidden * weights).sum(0) / max(float(weights.sum()), 1.0)
            out.append(vec / (np.linalg.norm(vec) + 1e-9))
        return np.array(out, dtype=np.float32)

    def _build_exemplars(self) -> None:
        exemplars = load_exemplars()
        phrases, owner = [], []
        self._topics = list(exemplars)
        for t_index, topic in enumerate(self._topics):
            for phrase in exemplars[topic]:
                phrases.append(phrase)
                owner.append(t_index)
        self._matrix = self._embed(phrases) if phrases else None
        self._phrase_topic = owner

    def status(self) -> dict:
        """Report the embedding layer state without forcing a download."""
        return {
            "model": self.model_name,
            "engine": "onnxruntime",
            "loaded": self._session is not None,
            "available": self.available,
            "cached": self._cache_has_model(),
            "error": self.load_error,
        }

    # -- classifying -----------------------------------------------------------
    def topic_scores(self, text: str) -> dict[str, float]:
        """Similarity of ``text`` to the closest typical phrase of each topic."""
        if (not self.available and not self.load()) or self._matrix is None or not text.strip():
            return {}
        np = self._np
        sims = self._matrix @ self._embed([text])[0]
        scores = np.full(len(self._topics), -1.0)
        for phrase_index, t_index in enumerate(self._phrase_topic):
            if sims[phrase_index] > scores[t_index]:
                scores[t_index] = sims[phrase_index]
        return {topic: float(scores[i]) for i, topic in enumerate(self._topics)}

    def classify(self, text: str, *, threshold: float | None = None) -> Classification | None:
        threshold = self.threshold if threshold is None else threshold
        scores = self.topic_scores(text)
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        (topic, best), second = ranked[0], (ranked[1][1] if len(ranked) > 1 else -1.0)
        if best >= threshold and best - second >= self.margin:
            return Classification(topic, "embedding", round(best, 4))
        return None


class HybridClassifier:
    def __init__(self, embedding_backend: EmbeddingBackend | None = None):
        # The embedding backend is optional and never eagerly loaded.
        self.embedding = embedding_backend
        self.refresh_lexicon()

    def refresh_lexicon(self) -> None:
        """Re-read the curated tables (after a lexicon update was merged)."""
        self._titles = {normalize(k): v for k, v in topics_mod.SONG_TITLE_TOPICS.items()}
        self._artists = {normalize(k): v for k, v in topics_mod.ARTIST_TOPICS.items()}
        self._keywords = [
            (topic, [normalize(kw) for kw in kws if normalize(kw)])
            for topic, kws in topics_mod.TOPIC_KEYWORDS.items()
        ]

    def keyword_topics(self, text: str) -> list[str]:
        """Every topic whose keywords appear in ``text``, in precedence order.

        Keywords match whole words of the normalized text (so "שבתות" does not
        hit "שבת"), allowing a Hebrew prefix: "לשבת" and "בחנוכה" do hit.
        """
        norm = normalize(text)
        hits: list[str] = []
        for topic, keywords in self._keywords:
            if any(contains_phrase(norm, nkw) for nkw in keywords):
                hits.append(topic)
        return hits

    def classify(
        self,
        *,
        title: str = "",
        artist: str = "",
        album: str = "",
        filename: str = "",
        lyrics: str = "",
        use_embeddings: bool = True,
    ) -> Classification:
        combined = " ".join(p for p in (title, artist, album, filename, lyrics) if p)
        keyword_hits = self.keyword_topics(combined)

        # Layer 1: curated exact title override.
        title_topic = self._titles.get(normalize(title))
        if title_topic:
            tags = tuple(t for t in keyword_hits if t != title_topic)
            return Classification(title_topic, "title", 1.0, tags)

        # Layer 2: curated keyword match; further matches become tags.
        if keyword_hits:
            return Classification(keyword_hits[0], "keyword", 0.9, tuple(keyword_hits[1:]))

        # Layer 3: artist default (weak).
        artist_topic = self._artists.get(normalize(artist))
        if artist_topic:
            return Classification(artist_topic, "artist", 0.5)

        # Layer 4: optional local embeddings.
        if use_embeddings and self.embedding is not None:
            result = self.embedding.classify(combined)
            if result is not None:
                return result

        return Classification(None, "none", 0.0)
