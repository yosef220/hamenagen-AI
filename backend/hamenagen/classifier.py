"""Hybrid topic classifier (spec §8.2).

Order of resolution, from most to least confident:

1. **Curated song-title override** — exact known titles (e.g. "מנוחה ושמחה"
   → שבת) even when the title carries no keyword.
2. **Curated keyword match** — a strong topic keyword appears as a token in
   the song's combined text.
3. **Local embedding model (optional)** — for songs the curated layer does
   not cover, a small local multilingual embedding model compares the song
   text against a prototype sentence per topic and picks the closest one
   above a similarity threshold. This layer is *optional*: if the model is
   not installed the classifier simply skips it, preserving offline-first
   behaviour. See :class:`EmbeddingBackend`.

The classifier returns a :class:`Classification` with the topic (or ``None``)
and the layer that produced it, which is useful both for debugging and for
deciding how much to trust the result.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import topics as topics_mod
from .text_normalize import contains_phrase, normalize


@dataclass(frozen=True)
class Classification:
    topic: str | None
    source: str          # "title" | "keyword" | "artist" | "embedding" | "none"
    confidence: float    # 0..1
    tags: tuple[str, ...] = ()  # further topics the song also belongs to


class EmbeddingBackend:
    """Optional local-embedding topic backend (light ONNX via fastembed).

    Loads a small multilingual ONNX model lazily (no PyTorch), downloading it
    once on first run with a network and using it offline thereafter. If
    fastembed or the model is unavailable, :attr:`available` stays ``False``
    and :meth:`classify` returns ``None`` — the hybrid classifier then falls
    through to the curated lexicon, so nothing breaks offline.
    """

    #: A short natural-language "prototype" per topic. Similarity is measured
    #: against these rather than against the bare topic word.
    PROTOTYPES: dict[str, str] = {
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

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        *,
        threshold: float = 0.5,
        cache_dir: str | None = None,
    ):
        import threading

        self.model_name = model_name
        self.threshold = threshold
        self.cache_dir = cache_dir
        self._model = None
        self._proto = None          # (topics, dim) L2-normalised prototype matrix
        self._proto_keys: list[str] = []
        self._np = None
        self._lock = threading.Lock()  # serialize the (one-time) model download
        self.available = False
        self.load_error: str | None = None

    def _cache_has_model(self) -> bool:
        if not self.cache_dir:
            return False
        try:
            from pathlib import Path as _P

            return any(_P(self.cache_dir).glob("models--*")) or any(
                _P(self.cache_dir).rglob("*.onnx")
            )
        except Exception:
            return False

    def _prefix(self, text: str) -> str:
        # paraphrase-MiniLM needs no instruction prefix (unlike the e5 family).
        return text

    def load(self) -> bool:
        """Load the local ONNX embedding model, downloading it once if needed.

        Uses fastembed (onnxruntime) — light (~50MB of libs) and no PyTorch.
        The first call with a network connection downloads a small model
        (~120MB) into ``cache_dir``; afterwards it runs fully offline.
        """
        if self._model is not None:
            return True
        with self._lock:  # another thread may have loaded it while we waited
            if self._model is not None:
                return True
            try:  # pragma: no cover - depends on optional dependency + download
                import os

                if self._cache_has_model():
                    os.environ.setdefault("HF_HUB_OFFLINE", "1")

                import numpy as np
                from fastembed import TextEmbedding  # type: ignore

                self._np = np
                model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
                keys = list(self.PROTOTYPES)
                vecs = np.array(list(model.embed([self._prefix(self.PROTOTYPES[k]) for k in keys])))
                norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
                self._proto = vecs / norms
                self._proto_keys = keys
                self._model = model
                self.available = True
                self.load_error = None
                return True
            except Exception as exc:  # package or model unavailable / offline
                self.load_error = str(exc)
                self.available = False
                return False

    def status(self) -> dict:
        """Report the embedding layer state without forcing a download."""
        return {
            "model": self.model_name,
            "engine": "onnx/fastembed",
            "loaded": self._model is not None,
            "available": self.available,
            "cached": self._cache_has_model(),
            "error": self.load_error,
        }

    def classify(self, text: str, *, threshold: float | None = None) -> Classification | None:
        threshold = self.threshold if threshold is None else threshold
        if not self.available and not self.load():
            return None
        if not text.strip():  # pragma: no cover
            return None
        np = self._np
        q = np.array(list(self._model.embed([self._prefix(text)]))[0])  # type: ignore[union-attr]
        q = q / (np.linalg.norm(q) + 1e-9)
        sims = self._proto @ q  # cosine similarity against every prototype
        idx = int(np.argmax(sims))
        best = float(sims[idx])
        if best >= threshold:
            return Classification(self._proto_keys[idx], "embedding", round(best, 4))
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
