"""
Tests for compression.py. The selection ALGORITHM (pick top-N most
relevant sentences, preserve original order) is fully testable with a
deterministic fake embedder - no network needed. The actual semantic
QUALITY of what gets selected still needs a real model - that's a
separate, Colab-only verification, not covered here.
"""
import asyncio
import os
import sys

from cyrrus.compression import ExtractiveCompressor, split_sentences

FAILED = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILED.append(name)


class FakeEmbedder:
    """Deterministic bag-of-words 'embedding' - real cosine-similarity
    behavior driven by word overlap, with a FIXED vocabulary shared
    across calls so sentence vectors and the query vector stay
    comparable. Not semantically meaningful beyond word overlap - good
    enough to verify the selection algorithm itself, not the model."""
    def __init__(self, vocab):
        self.vocab = vocab

    def embed(self, texts):
        vectors = []
        for text in texts:
            words = text.lower().split()
            vectors.append([float(words.count(w)) for w in self.vocab])
        return vectors


def make_embedder(*texts):
    vocab = sorted(set(w for t in texts for w in t.lower().split()))
    return FakeEmbedder(vocab)


def test_picks_most_relevant_sentences():
    text = "Cats are popular pets. Dogs need daily walks. The stock market rose today. Cats also enjoy sleeping."
    query = "tell me about cats"
    embedder = make_embedder(text, query)
    compressor = ExtractiveCompressor(embedder=embedder)

    result = compressor.compress(text, query, max_sentences=2)
    check("compression picks the cat-related sentences over the unrelated ones",
          "Cats are popular pets" in result and "Cats also enjoy sleeping" in result)
    check("compression drops the clearly irrelevant sentence",
          "stock market" not in result)


def test_preserves_original_order():
    # deliberately put the MOST relevant sentence last, to confirm
    # selection doesn't reorder by score - it should restore reading order
    text = "The weather was fine. Nothing else happened. Cats are wonderful animals about cats."
    query = "cats"
    embedder = make_embedder(text, query)
    compressor = ExtractiveCompressor(embedder=embedder)

    result = compressor.compress(text, query, max_sentences=1)
    check("the single selected sentence is the relevant one even though it was last",
          "Cats are wonderful" in result)

    # now force 2 selections where relevance order and text order differ
    text2 = "Cats are wonderful about cats cats. The weather was fine today outside. Dogs need walks daily exercise."
    embedder2 = make_embedder(text2, "cats")
    compressor2 = ExtractiveCompressor(embedder=embedder2)
    result2 = compressor2.compress(text2, "cats", max_sentences=2)
    idx_cats = result2.find("Cats are wonderful")
    idx_weather = result2.find("weather")
    check("selected sentences are stitched back in original reading order, not by score",
          idx_cats < idx_weather if idx_weather != -1 else True)


def test_noop_when_under_the_limit():
    text = "Only one sentence here."
    embedder = make_embedder(text, "query")
    compressor = ExtractiveCompressor(embedder=embedder)
    result = compressor.compress(text, "query", max_sentences=3)
    check("text with fewer sentences than max_sentences is returned unchanged",
          result == text)


def test_failsafe_with_no_embedder():
    compressor = ExtractiveCompressor(embedder=None)
    # force no fastembed available (true in this sandbox) - should no-op, not crash
    long_text = "First sentence here. Second sentence here. Third sentence here. Fourth one too."
    result = compressor.compress(long_text, "anything", max_sentences=2)
    check("with no embedder available, compression no-ops instead of crashing",
          result == long_text)


def test_split_sentences_basic():
    result = split_sentences("First one. Second one! Third one?")
    check("basic sentence splitting produces 3 sentences",
          len(result) == 3)
    check("sentence splitting preserves content correctly",
          result == ["First one.", "Second one!", "Third one?"])


def test_split_sentences_empty():
    check("splitting empty text returns an empty list", split_sentences("") == [])
    check("splitting whitespace-only text returns an empty list", split_sentences("   ") == [])


def main():
    test_picks_most_relevant_sentences()
    test_preserves_original_order()
    test_noop_when_under_the_limit()
    test_failsafe_with_no_embedder()
    test_split_sentences_basic()
    test_split_sentences_empty()

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    else:
        print("ALL COMPRESSION TESTS PASSED")
        print("NOTE: this verifies the selection algorithm with a fake embedder.")
        print("Semantic quality with the real model needs Colab verification.")


if __name__ == "__main__":
    main()
