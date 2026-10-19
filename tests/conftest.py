import pytest

from harnessforge.corpus import build_corpus
from harnessforge.retrieval import Index


@pytest.fixture(scope="session")
def corpus():
    return build_corpus(7)


@pytest.fixture(scope="session")
def index(corpus):
    return Index(corpus.docs)
