"""WNBA prop model training — re-exports shared train()."""

from app.services.ml.train_model import DEFAULT_HYPERPARAMS, train

__all__ = ["DEFAULT_HYPERPARAMS", "train"]
