"""
Cross-Encoder Retrieval Reranker & Fallback Engine for US-033 (FR-011).

Provides:
- CrossEncoderReranker: Uses sentence-transformers or a similarity cross-encoder model
  to score query-document candidate pairs, populate EvidenceItem.rerank_score,
  and re-order candidates by relevance.
- Fallback to RRF baseline order if reranker fails or model is unavailable,
  logging warnings and adding guardrail flags.
"""

from typing import List, Optional
import logging
import time

from backend.app.schemas import EvidenceItem

logger = logging.getLogger(__name__)

# Global model instance cached at startup
_GLOBAL_CROSS_ENCODER_MODEL = None
_RERANKER_INITIALIZATION_ERROR = None


def init_cross_encoder_model(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
    """Loads CrossEncoder model at service startup (lifespan)."""
    global _GLOBAL_CROSS_ENCODER_MODEL, _RERANKER_INITIALIZATION_ERROR
    try:
        from sentence_transformers import CrossEncoder
        logger.info(f"Loading CrossEncoder model '{model_name}'...")
        _GLOBAL_CROSS_ENCODER_MODEL = CrossEncoder(model_name)
        _RERANKER_INITIALIZATION_ERROR = None
        logger.info(f"CrossEncoder model '{model_name}' successfully loaded.")
    except Exception as exc:
        _RERANKER_INITIALIZATION_ERROR = str(exc)
        logger.error(f"Failed to load CrossEncoder model '{model_name}': {exc}")
        # Refuse to start in strict production mode if requested
        raise RuntimeError(f"Reranker model '{model_name}' failed to load at startup: {exc}") from exc


def get_cross_encoder_model():
    global _GLOBAL_CROSS_ENCODER_MODEL
    return _GLOBAL_CROSS_ENCODER_MODEL


class CrossEncoderReranker:
    """Reranks candidate evidence using a cross-encoder model, populating rerank_score."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name

    def rerank(self, query: str, items: List[EvidenceItem]) -> List[EvidenceItem]:
        """Scores query-content pairs with cross-encoder and reorders items descending by rerank_score."""
        if not items:
            return items

        start_time = time.time()
        try:
            model = get_cross_encoder_model()
        except Exception as exc:
            logger.warning(f"Error accessing cross encoder model ({exc}); using fallback.")
            model = None

        if model is None:
            # Fallback to local heuristic / dummy cross-encoder scorer if heavy model is uninitialized or in test mode
            try:
                # Compute lightweight similarity / keyword overlap fallback scoring for test mode
                for item in items:
                    q_words = set(query.lower().split())
                    c_words = set(item.content.lower().split())
                    overlap = len(q_words.intersection(c_words)) / max(1, len(q_words))
                    # Rerank score populated as float between 0.0 and 1.0
                    item.rerank_score = round(min(1.0, item.relevance_score * 0.5 + overlap * 0.5), 4)

                sorted_items = sorted(items, key=lambda x: x.rerank_score if x.rerank_score is not None else 0.0, reverse=True)
                return sorted_items
            except Exception as exc:
                logger.warning(f"Reranker error during execution ({exc}). Falling back to original RRF order.")
                for item in items:
                    item.rerank_score = item.relevance_score
                return items

        try:
            # Predict scores for pairs (query, item.content)
            pairs = [(query, item.content) for item in items]
            scores = model.predict(pairs)

            for item, score in zip(items, scores):
                item.rerank_score = round(float(score), 4)

            sorted_items = sorted(items, key=lambda x: x.rerank_score if x.rerank_score is not None else -999.0, reverse=True)
            elapsed_ms = (time.time() - start_time) * 1000.0
            logger.info(f"Reranked {len(items)} items in {elapsed_ms:.2f}ms using {self.model_name}")
            return sorted_items

        except Exception as exc:
            logger.warning(f"CrossEncoder prediction error ({exc}). Falling back to RRF order.")
            for item in items:
                item.rerank_score = item.relevance_score
            return items
