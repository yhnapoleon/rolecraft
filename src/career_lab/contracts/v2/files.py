"""Portable file-only bundles. Loading verifies bytes and never executes entrypoints."""

from pathlib import Path
import json
from pydantic import BaseModel
from .core import FileRef, read_file, ProtocolError


def load_bundle(root: Path, ref: FileRef, model):
    obj = model.model_validate_json(read_file(root, ref))

    def verify(value):
        if isinstance(value, FileRef):
            read_file(root, value)
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                verify(getattr(value, name))
        elif isinstance(value, (list, tuple)):
            for x in value:
                verify(x)
        elif isinstance(value, dict):
            for x in value.values():
                verify(x)

    verify(obj)
    return obj
