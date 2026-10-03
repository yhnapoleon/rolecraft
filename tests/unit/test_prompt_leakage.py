import pytest
from pydantic import ValidationError

from career_lab.contracts.evaluation import EvidencePackage
from career_lab.evidence.serializer import seal_input, serialize_prompt


def test_prompt_hash_ignores_gold_and_rejects_tampering():
    item = EvidencePackage(item_id="x", task_type="relation", criterion="r", claim="a", as_of_seq=0, completeness="complete", candidate_evidence=[])
    sealed = seal_input(item)
    assert sealed.input_hash == seal_input(item).input_hash
    assert "gold" not in str(serialize_prompt(sealed))
    with pytest.raises(ValueError, match="hash"):
        serialize_prompt(sealed.model_copy(update={"claim": "tampered"}))
    with pytest.raises(ValidationError):
        EvidencePackage.model_validate(item.model_dump() | {"gold": {"label": "SUPPORTED"}})
