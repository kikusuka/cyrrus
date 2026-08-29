"""
Extractive tool-result compression: split a tool result into
sentences, keep only the ones most relevant to the user's message,
drop the rest. Unlike summarize_tool_output (which calls the LLM and
costs an extra API call on your own key), this uses the same local
embedding model as EmbeddingRouter - zero extra API cost.

Testable in two layers, on purpose:
- The SELECTION algorithm (which sentences get kept, in what order)
  is tested with a fake, injected embedder - no network needed, see
  tests/test_compression.py.
- The actual semantic quality of what gets selected needs a real
  model - verify in Colab, same as EmbeddingRouter.
"""
import logging
import re

log = logging.getLogger("slides.compression")

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')


def split_sentences(text: str) -> list:
    """Simple regex-based sentence splitting. Known limitation: will
    mis-split on abbreviations (e.g. "Dr. Smith") - acceptable for
    tool-result text (search snippets, DB rows), not recommended for
    literary prose."""
    if not text or not text.strip():
        return []
    sentences = _SENTENCE_SPLIT_RE.split(text.strip())
    return [s.strip() for s in sentences if s.strip()]


class ExtractiveCompressor:
    def __init__(self, embedder: object = None, model_name: str = DEFAULT_MODEL):
        """embedder: anything with .embed(list[str]) -> list[vector],
        matching fastembed's TextEmbedding interface. Pass a fake one
        in tests to check the selection logic without network. If
        None, tries to load the real local model; falls back to
        returning text unmodified (compression becomes a no-op, not a
        crash) if that fails."""
        self.embedder = embedder
        self._np = None
        if embedder is None:
            self._try_load_default_embedder(model_name)
        else:
            try:
                import numpy as np
                self._np = np
            except ImportError:
                log.warning("numpy not available - compression will no-op even with a custom embedder.")

    def _try_load_default_embedder(self, model_name: str):
        try:
            from fastembed import TextEmbedding
            import numpy as np
            self.embedder = TextEmbedding(model_name=model_name)
            self._np = np
        except ImportError:
            log.warning("fastembed not installed - tool-result compression will no-op "
                        "(results pass through unmodified). Install with: pip install fastembed")
        except Exception as e:
            log.warning("Embedding model failed to load (%s) - compression will no-op.", e)

    def compress(self, text: str, query: str, max_sentences: int = 3) -> str:
        if self.embedder is None or self._np is None:
            return text  # fail-safe: no-op, never crash the caller over this

        sentences = split_sentences(text)
        if len(sentences) <= max_sentences:
            return text  # nothing to trim

        try:
            sentence_embeddings = self._np.array(list(self.embedder.embed(sentences)))
            query_embedding = self._np.array(list(self.embedder.embed([query]))[0])

            norms = self._np.linalg.norm(sentence_embeddings, axis=1) * self._np.linalg.norm(query_embedding)
            norms[norms == 0] = 1e-9
            scores = sentence_embeddings.dot(query_embedding) / norms

            top_indices = sorted(
                range(len(scores)), key=lambda i: scores[i], reverse=True
            )[:max_sentences]
            top_indices.sort()  # restore original reading order, don't shuffle the sentences

            return " ".join(sentences[i] for i in top_indices)
        except Exception as e:
            log.warning("Compression failed (%s) - returning original text uncompressed.", e)
            return text
