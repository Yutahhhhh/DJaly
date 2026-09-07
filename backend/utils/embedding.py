"""Keep embeddings from different preprocessing pipelines out of the same space."""
import numpy as np

LEGACY_MODELS = ("musicnn", "msd-musicnn-1", "")


def embedding_space(model):
    return "musicnn" if model is None or model in LEGACY_MODELS else model


def cosine_similarity(left, right, left_model=None, right_model=None):
    if embedding_space(left_model) != embedding_space(right_model):
        return 0.0
    if left is None or right is None:
        return 0.0
    left, right = np.asarray(left), np.asarray(right)
    if left.ndim != 1 or left.shape != right.shape or not left.size:
        return 0.0
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        return 0.0
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    return float(np.clip(np.dot(left, right) / denominator, -1, 1)) if denominator else 0.0
