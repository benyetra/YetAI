"""NBA prop model training — re-exports shared train()."""

from app.services.ml.train_model import DEFAULT_HYPERPARAMS, split, train

__all__ = ["DEFAULT_HYPERPARAMS", "split", "train"]
