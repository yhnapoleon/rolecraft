"""Server registrations and scripted slot providers for the ``model-flows`` browser suite.

Every registration is ``synthetic_fixture``: constructed keyword weights (never fitted),
146's tiny random encoder, or the real XLM-R base encoder with untrained heads. They show the
receiving end working in the normal v4 entry; none is a model judgement or a quality claim.

Default phases: ``linear`` (one keyword linear return), ``fusion`` (two keyword linear returns,
alpha 0.75) and ``slots`` (the linear return plus scripted loopback JUDGE and ASSISTANT
services). Optional phases (encoder extra): ``encoder`` (146 tiny pair_aggregate return),
``hetero`` (keyword linear return x tiny encoder) and ``xlmr`` (``ROLECRAFT_XLMR_DIR``).

The keyword vocabulary holds business words only and no digits, so the time-point numbers in
the feature text never move a result: the same business fact gets the same per-sentence
conclusion in Chinese and English (157 observation).
"""

import importlib
import json
import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from career_lab.contracts.v2.core import FileRef
from career_lab.models.v3.registry import describe_registration, register_bundle, register_fusion
from scripts.smoke.xlmr_base import register as xlmr_register
from tests.support.linear_return import (
    MECHANISM_DATASET,
    constructed_model,
    selection_record,
    write_linear_return,
)
from tests.support.model_slots import reply, request_kind

DEFAULT_PHASES = ("linear", "fusion", "slots")
OPTIONAL_PHASES = ("encoder", "hetero", "xlmr")
# "有据可查" / "corroborated" read as SUPPORTED, "豁免" / "exempt" as CONTRADICTED.
KEYWORDS = {"据可": 0, "obo": 1, "豁免": 2, "xem": 3}
DATASET = {"dataset_id": MECHANISM_DATASET, "dataset_sha": "d" * 64}
JUDGE_MODEL, ASSISTANT_MODEL = "qa-loopback-judge", "qa-loopback-assistant"
_CJK = re.compile(r"[一-鿿]")


def keyword_return(root: Path, intercept: tuple[float, float, float] = (0.0, 0.0, 1.0)) -> FileRef:
    """A ``rolecraft-linear-return-v1`` return over the keyword vocabulary (constructed)."""
    model, _ = constructed_model()
    vectorizer = model["vectorizer"] | {"ngram_range": [2, 3], "vocabulary": KEYWORDS}
    arrays = {
        "idf": np.ones(len(KEYWORDS)),
        "coef": np.array([[4.0, 4.0, 0.0, 0.0], [0.0, 0.0, 4.0, 4.0], [0.0, 0.0, 0.0, 0.0]]),
        "intercept": np.array(intercept),
        "evidence_coef": np.array([3.0, 3.0, 3.0, 3.0]),
        "evidence_intercept": np.array([-1.0]),
    }
    return write_linear_return(
        root, model={"vectorizer": vectorizer}, arrays=arrays, label_tiers=["G0"], **DATASET
    )


@dataclass
class Phase:
    name: str
    registry: Path
    registration: FileRef
    drift_file: Path | None = None
    slots: bool = False
    identity: dict = field(default_factory=dict)

    def environment(self, journal: Path) -> dict[str, str]:
        return {
            "CAREER_LAB_MODEL_REGISTRY": str(self.registry),
            "CAREER_LAB_MODEL_REGISTRATION": self.registration.model_dump_json(),
            "CAREER_LAB_MODEL_JOURNAL": str(journal),
        }


def _weights(registry: Path, ref: FileRef) -> Path:
    """The first registered ``.npz`` artifact of a registration (the drift target)."""
    entry = registry / ref.path
    names = json.loads(entry.read_text())["files"]
    return entry.parent / "artifact" / next(name for name in names if name.endswith(".npz"))


def _register(registry: Path, root: Path, ref: FileRef) -> FileRef:
    return register_bundle(registry, root, ref, scope="synthetic_fixture")


def _fusion(registry: Path, left: FileRef, right: FileRef, alpha: float, out: Path) -> FileRef:
    identities = [describe_registration(registry, ref).identity() for ref in (left, right)]
    selection = out / "fusion-selection.json"
    selection.write_text(json.dumps(selection_record(*identities, alpha=alpha), indent=2))
    return register_fusion(registry, left, right, selection, scope="synthetic_fixture")


def build(name: str, out: Path) -> Phase:
    """Register the phase's model under ``out`` (a new directory)."""
    registry = out / "registry"
    if name in {"linear", "slots", "fusion", "hetero"}:
        linear = _register(registry, out / "linear", keyword_return(out / "linear"))
    if name in {"linear", "slots"}:
        phase = Phase(name, registry, linear, _weights(registry, linear), slots=name == "slots")
    elif name == "fusion":
        right = _register(registry, out / "right", keyword_return(out / "right", (0.2, 0.0, 0.8)))
        phase = Phase(name, registry, _fusion(registry, linear, right, 0.75, out))
        phase.drift_file = _weights(registry, linear)
    elif name in {"encoder", "hetero"}:
        # The tiny encoder builder needs the encoder extra (torch): loaded for these phases only.
        tiny_encoder_return = importlib.import_module(
            "tests.optional_encoder.tiny_return"
        ).tiny_encoder_return
        dataset = {
            "dataset_id": DATASET["dataset_id"],
            "dataset_manifest_sha256": DATASET["dataset_sha"],
            "label_tiers": ["G0"],
        }
        tiny = out / "tiny"
        ref = tiny_encoder_return(tiny, variant="pair_aggregate", dataset=dataset)
        encoder = _register(registry, tiny, ref)
        registration = (
            encoder if name == "encoder" else _fusion(registry, linear, encoder, 0.5, out)
        )
        phase = Phase(name, registry, registration)
    elif name == "xlmr":
        model = Path(os.environ["ROLECRAFT_XLMR_DIR"])
        out.mkdir(parents=True, exist_ok=True)
        registry, registration, _ = xlmr_register(model, model.name, "pair", out)
        phase = Phase(name, registry, registration)
    else:
        raise ValueError("unknown model-flows phase: " + name)
    phase.identity = describe_registration(phase.registry, phase.registration).identity()
    return phase


@dataclass
class Calls:
    entries: list[dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


@contextmanager
def slot_services() -> Iterator[tuple[str, Calls]]:
    """One scripted OpenAI-compatible loopback for the JUDGE and ASSISTANT slots.

    It answers by the 144 script (``tests.support.model_slots.reply``) in the language of
    the request, records the model name and kind of each call, and never sees a key.
    """
    calls = Calls()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            user = " ".join(str(m.get("content", "")) for m in payload["messages"][1:])
            language = "zh" if _CJK.search(user) else "en"
            with calls.lock:
                calls.entries.append(
                    {
                        "kind": request_kind(payload),
                        "model": payload["model"],
                        "language": language,
                        "authorization": self.headers.get("Authorization") is not None,
                    }
                )
            body = json.dumps(
                {
                    "choices": [{"message": {"content": reply(payload, language)}}],
                    "usage": {"prompt_tokens": 40, "completion_tokens": 16},
                }
            ).encode()
            self.send_response(200 if self.path == "/chat/completions" else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def slot_environment(url: str) -> dict[str, str]:
    """JUDGE and ASSISTANT on the loopback; loopback hosts need no key (144 KEY-02)."""
    environment = {}
    for slot, model in (("JUDGE", JUDGE_MODEL), ("ASSISTANT", ASSISTANT_MODEL)):
        environment |= {
            f"CAREER_LAB_{slot}_PROVIDER": "openai_compatible",
            f"CAREER_LAB_{slot}_BASE_URL": url,
            f"CAREER_LAB_{slot}_MODEL": model,
        }
    return environment


def check_slot_calls(calls: Calls) -> dict:
    """FLOW-05: generation went to the ASSISTANT slot and feedback to the JUDGE slot."""
    by_kind: dict[str, set[str]] = {}
    for entry in calls.entries:
        by_kind.setdefault(entry["kind"], set()).add(entry["model"])
    summary = {kind: sorted(models) for kind, models in by_kind.items()}
    languages = {(e["kind"], e["language"]) for e in calls.entries}
    problems = []
    if summary.get("assistant") != [ASSISTANT_MODEL]:
        problems.append("assistant generation did not use only the ASSISTANT slot")
    if summary.get("judge") != [JUDGE_MODEL]:
        problems.append("feedback Judge did not use only the JUDGE slot")
    for kind in ("assistant", "judge"):
        for language in ("zh", "en"):
            if (kind, language) not in languages:
                problems.append(f"no {kind} call in {language}")
    if any(entry["authorization"] for entry in calls.entries):
        problems.append("a loopback request carried an Authorization header")
    return {"models": summary, "calls": len(calls.entries), "problems": problems}
