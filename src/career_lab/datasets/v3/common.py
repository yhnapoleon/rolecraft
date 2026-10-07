"""Private pipeline utilities; public data shapes belong to contracts.v2."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile

from career_lab.contracts.v2.core import canonical, ProtocolError


def json_bytes(value):
    return (canonical(value) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def immutable_directory(target):
    """Publish only a complete directory, serialized against concurrent publishers."""
    target = Path(target).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(target.name + ".publish-lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise ProtocolError("publisher_busy", status=409) from None
    stage = None
    try:
        if target.exists() or target.is_symlink():
            raise ProtocolError("immutable_output_exists", status=409)
        stage = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
        yield stage
        os.rename(stage, target)
        stage = None
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        lock.rmdir()


FORBIDDEN_KEYS = frozenset({
    "gold", "gold_label", "label_tier", "label_ref", "acceptable_evidence_sets",
    "source_map", "answer_key", "solutions", "hidden_probes", "probe_expected",
    "authoring", "verifier_id", "annotation", "annotation_version",
})


def check_payload(value):
    """Structural leak check, including arbitrary rule-context and action arguments."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in FORBIDDEN_KEYS:
                raise ProtocolError("model_input_metadata_leak")
            check_payload(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            check_payload(child)
