"""L2 registration entry for L4: register OBJECT_MODELS in both registries, mount operations()."""

from .handlers import DESIGN_OBJECT_MODELS as OBJECT_MODELS
from .handlers import design_operations as operations

__all__ = ["OBJECT_MODELS", "operations"]
