"""Reference feature text ``rolecraft-linear-text-v1`` (Python standard library only).

The RoleCraft linear loader turns every relation model input into exactly these texts
before vectorizing, so a producer must fit its TF-IDF on the same strings:

- ``relation_text(model_input)`` feeds the relation classifier;
- ``pair_text(model_input, candidate)`` feeds the evidence head, once per candidate.

``model_input`` is the JSON object stored under ``model_input`` in the dataset's
``*.inputs.jsonl`` (``{"evidence": {...}, "schema_version": 2, "task_type": "relation"}``).
Labels, audit files and the outer ``input_hash`` are never part of the text.
Check this copy against ``linear-text-v1.golden.jsonl`` with ``python3 linear_text_v1.py
<golden file>``; every line must report ``ok``.
"""

import hashlib
import json
import sys

TEMPLATE = "rolecraft-linear-text-v1"
TIME_CONTEXT = "evidence_time_context"


def _reference(package):
    context = package["rule_context"].get(TIME_CONTEXT, {})
    status = context.get("status", "undetermined")
    return f"reference time {package['as_of']['business_seq']}; temporal scope {status}"


def _validity(candidate):
    ref = candidate["ref"]
    until = ref["valid_until_seq"] if ref.get("valid_until_seq") is not None else "open"
    return (
        f"observed {ref['observed_at_seq']}; valid from {ref['valid_from_seq']}; "
        f"valid until {until}"
    )


def relation_text(model_input):
    package = model_input["evidence"]
    return (
        package["purpose"]
        + "\n"
        + package["claim"]
        + "\n"
        + _reference(package)
        + "\n"
        + "\n".join(c["text"] + "\n" + _validity(c) for c in package["candidate_evidence"])
    )


def pair_text(model_input, candidate):
    package = model_input["evidence"]
    return (
        package["claim"]
        + "\n"
        + _reference(package)
        + "\n[EVIDENCE]\n"
        + candidate["text"]
        + "\n"
        + _validity(candidate)
    )


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def check_golden(path):
    """Yield ``(sample, ok)`` for each golden vector line."""
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            model_input = row["model_input"]
            pairs = {
                c["id"]: _sha(pair_text(model_input, c))
                for c in model_input["evidence"]["candidate_evidence"]
            }
            ok = (
                _sha(relation_text(model_input)) == row["relation_text_sha256"]
                and pairs == row["pair_text_sha256"]
            )
            yield row["sample"], ok


if __name__ == "__main__":
    failed = 0
    for sample, ok in check_golden(sys.argv[1]):
        print(sample, "ok" if ok else "MISMATCH")
        failed += not ok
    raise SystemExit(1 if failed else 0)
