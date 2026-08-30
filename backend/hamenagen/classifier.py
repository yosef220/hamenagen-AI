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
from .text_normalize import normalize, token_set


@dataclass(frozen=True)
class Classification:
    topic: str | None
    source: str          # "title" | "keyword" | "artist" | "embedding" | "none"
    confidence: float    # 0..1


class EmbeddingBackend:
    """Optional local-embedding topic backend.

    Tries to load a small ``sentence-transformers`` model lazily. If the
    package or model is unavailable, :attr:`available` stays ``False`` and
    :meth:`classify` returns ``None`` — the hybrid classifier then just falls
    through, so nothing breaks offline.
    """

    #: A short natural-language "prototype" per topic. Similarity is measured
    #: against these rather than against the bare topic word.
    PROTOTYPES: dict[str, str] = {
        "שבת": "שיר לשבת קודש, זמירות שבת, מנוחה, קבלת שבת",
        "חנוכה": "שיר לחנוכה, נרות, מכבים, נס פך השמן",
        "אלול": "שיר לחודש אלול, סליחות, תשובה, התעוררות רוחנית",
        "סוכות": "שיר לחג הסוכות, סוכה, ארבעת המינים, שמחת בית השואבה",
        "פסח": "שיר לחג הפסח, יציאת מצרים, הגדה, ליל הסדר",
        "פורים": "שיר לפורים, מגילת אסתר, משתה ושמחה",
        "שבועות": "שיר לחג השבועות, מתן תורה",
        "חתונה": "שיר לחתונה ולשמחות, חתן וכלה, ריקודים",
        "ירושלים": "שיר על ירושלים עיר הקודש והכותל",
        "אמונה": "שיר על אמונה וביטחון בהשם ותפילה",
    }

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        *,
        threshold: float = 0.45,
        cache_dir: str | None = None,
    ):
        self.model_name = model_name
        self.threshold = threshold
        self.cache_dir = cache_dir
        self._model = None
        self._proto_vecs: dict[str, "object"] = {}
        self.available = False
        self.load_error: str | None = None

    def _cache_has_model(self) -> bool:
        if not self.cache_dir:
            return False
        try:
            from pathlib import Path as _P

            return any(_P(self.cache_dir).glob("models--*"))
        except Exception:
            return False

    def load(self) -> bool:
        if self._model is not None:
            return True
        try:  # pragma: no cover - depends on optional heavy dependency
            import os

            # If the model is already cached (e.g. shipped in the offline
            # bundle), force offline mode so it never tries to reach the network.
            if self._cache_has_model():
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

            from sentence_transformers import SentenceTransformer, util  # type: ignore

            self._util = util
            self._model = SentenceTransformer(self.model_name, cache_folder=self.cache_dir)
            keys = list(self.PROTOTYPES)
            vecs = self._model.encode(
                [self.PROTOTYPES[k] for k in keys], convert_to_tensor=True
            )
            self._proto_vecs = dict(zip(keys, vecs))
            self.available = True
            return True
        except Exception as exc:  # model / package not present
            self.load_error = str(exc)
            self.available = False
            return False

    def status(self) -> dict:
        """Report whether the embedding layer is usable, without forcing a load."""
        return {
            "model": self.model_name,
            "loaded": self._model is not None,
            "available": self.available,
            "error": self.load_error,
        }

    def classify(self, text: str, *, threshold: float | None = None) -> Classification | None:
        threshold = self.threshold if threshold is None else threshold
        if not self.available and not self.load():
            return None
        if not text.strip():  # pragma: no cover
            return None
        query = self._model.encode(text, convert_to_tensor=True)  # type: ignore[union-attr]
        best_topic, best_score = None, 0.0
        for topic, vec in self._proto_vecs.items():
            score = float(self._util.cos_sim(query, vec)[0][0])
            if score > best_score:
                best_topic, best_score = topic, score
        if best_topic is not None and best_score >= threshold:
            return Classification(best_topic, "embedding", round(best_score, 4))
        return None


class HybridClassifier:
    def __init__(self, embedding_backend: EmbeddingBackend | None = None):
        # The embedding backend is optional and never eagerly loaded.
        self.embedding = embedding_backend

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
        # Layer 1: curated exact title override.
        norm_title = normalize(title)
        if norm_title in _NORMALIZED_TITLE_TOPICS:
            return Classification(_NORMALIZED_TITLE_TOPICS[norm_title], "title", 1.0)

        combined = " ".join(p for p in (title, artist, album, filename, lyrics) if p)
        toks = token_set(combined)

        # Layer 2: curated keyword match. Multi-word keywords are checked as
        # substrings of the normalized text; single words against the token set.
        norm_combined = normalize(combined)
        for topic, keywords in topics_mod.TOPIC_KEYWORDS.items():
            for kw in keywords:
                nkw = normalize(kw)
                if not nkw:
                    continue
                if " " in nkw:
                    if nkw in norm_combined:
                        return Classification(topic, "keyword", 0.9)
                elif nkw in toks:
                    return Classification(topic, "keyword", 0.9)

        # Layer 3: artist default (weak).
        norm_artist = normalize(artist)
        if norm_artist in _NORMALIZED_ARTIST_TOPICS:
            return Classification(_NORMALIZED_ARTIST_TOPICS[norm_artist], "artist", 0.5)

        # Layer 4: optional local embeddings.
        if use_embeddings and self.embedding is not None:
            result = self.embedding.classify(combined)
            if result is not None:
                return result

        return Classification(None, "none", 0.0)


_NORMALIZED_TITLE_TOPICS = {
    normalize(k): v for k, v in topics_mod.SONG_TITLE_TOPICS.items()
}
_NORMALIZED_ARTIST_TOPICS = {
    normalize(k): v for k, v in topics_mod.ARTIST_TOPICS.items()
}
