"""Tests for semantic deduplication via OpenAI embeddings."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from newsletter_agent.utils import (
    _content_hash,
    _cosine_similarity,
    compute_embeddings_batch,
    find_semantic_duplicates,
)


def test_cosine_similarity_identical() -> None:
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert _cosine_similarity(a, a) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal() -> None:
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert _cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector() -> None:
    a = np.array([1.0, 2.0], dtype=np.float32)
    b = np.array([0.0, 0.0], dtype=np.float32)
    assert _cosine_similarity(a, b) == 0.0


def test_content_hash_deterministic() -> None:
    assert _content_hash("hello") == _content_hash("hello")
    assert _content_hash("hello") == _content_hash("  Hello  ")


def test_find_semantic_duplicates_marks_later_index() -> None:
    """When two titles are very similar, the later index should be marked as duplicate."""
    # Mock embeddings: make index 0 and 2 nearly identical
    embeddings = [
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0, 0.0], dtype=np.float32),
        np.array([0.99, 0.01, 0.0], dtype=np.float32),
    ]

    with patch("newsletter_agent.utils.compute_embeddings_batch", return_value=embeddings):
        dups = find_semantic_duplicates(
            ["Article A", "Article B", "Article A revised"],
            threshold=0.95,
        )

    assert 2 in dups
    assert 0 not in dups
    assert 1 not in dups


def test_find_semantic_duplicates_no_duplicates() -> None:
    embeddings = [
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
    ]

    with patch("newsletter_agent.utils.compute_embeddings_batch", return_value=embeddings):
        dups = find_semantic_duplicates(["A", "B"], threshold=0.9)

    assert len(dups) == 0


def test_find_semantic_duplicates_single_title() -> None:
    dups = find_semantic_duplicates(["Only one"], threshold=0.9)
    assert len(dups) == 0


def test_compute_embeddings_batch_caches_to_store() -> None:
    """Embeddings should be cached in the state store."""
    mock_store = MagicMock()
    mock_store.get_cached_embedding.return_value = None

    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1, 0.2, 0.3]

    mock_response = MagicMock()
    mock_response.data = [mock_embedding]

    with (
        patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
        patch("openai.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.embeddings.create.return_value = mock_response

        results = compute_embeddings_batch(
            ["test title"],
            state_store=mock_store,
            cache_enabled=True,
        )

    assert len(results) == 1
    assert mock_store.cache_embedding.call_count == 1


def test_compute_embeddings_batch_uses_cache() -> None:
    """Cached embeddings should be returned without API call."""
    cached_vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    mock_store = MagicMock()
    mock_store.get_cached_embedding.return_value = cached_vec.tobytes()

    with (
        patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
        patch("openai.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        results = compute_embeddings_batch(
            ["test title"],
            state_store=mock_store,
            cache_enabled=True,
        )

    assert len(results) == 1
    np.testing.assert_array_equal(results[0], cached_vec)
    mock_client.embeddings.create.assert_not_called()


def test_compute_embeddings_batch_no_api_key() -> None:
    """Should raise when OPENAI_API_KEY is not set."""
    with (
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(ValueError, match="OPENAI_API_KEY"),
    ):
        compute_embeddings_batch(["test"])
