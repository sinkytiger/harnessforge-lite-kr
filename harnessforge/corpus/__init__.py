"""Synthetic DART-style disclosure corpora (v1, v2: fictional companies only) and a locally built real-filing set."""

from .store import Corpus, build_corpus

__all__ = ["Corpus", "build_corpus"]
