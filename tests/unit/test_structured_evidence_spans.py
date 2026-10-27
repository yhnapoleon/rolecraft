from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from career_lab.contracts import v2 as C
from career_lab.evidence.v2.assembler import product_text
from career_lab.scenarios.v2.module import ScenarioModule


@pytest.mark.parametrize("language", ["zh", "en"])
def test_saved_seven_section_work_uses_exact_same_quote_projection(language):
    sections = {
        key: (
            "拟议采集实际工时，尚未完成。"
            if language == "zh"
            else "Propose collecting actual handling time; not completed."
        )
        for key in (
            "business",
            "stakeholders",
            "need",
            "boundary",
            "solution",
            "assurance",
            "decision",
        )
    }
    payload = C.PlanPayload(sections=sections)
    actor = C.Executor(id="owner", kind="human")
    product = C.WorkProductVersion(
        product_id="prd",
        session_id="s",
        version=2,
        cycle=C.ObjectRef(session_id="s", kind="cycle", object_id="c", version=1),
        kind="plan",
        content="",
        structured_payload=payload,
        author=actor,
        executor=actor,
        created_at=datetime.now(UTC),
        content_hash=C.digest(
            {"content": "", "structured_payload": payload.model_dump(mode="json")}
        ),
    )
    text = product_text(product)
    view = SimpleNamespace(
        state=SimpleNamespace(business_seq=2),
        get=lambda _: SimpleNamespace(content=product.model_dump(mode="json")),
    )
    auth = SimpleNamespace(session_id="s")
    ref = C.EvidenceRefV2(
        session_id="s",
        kind="product",
        object_id="prd",
        version=2,
        observed_at_seq=2,
        span_start=0,
        span_end=len(text),
        quote=text,
    )
    assert ScenarioModule.check_evidence(None, view, auth, ref)
    with pytest.raises(C.ProtocolError) as error:
        ScenarioModule.check_evidence(
            None, view, auth, ref.model_copy(update={"quote": "Fabricated evidence"})
        )
    assert error.value.code == "reference_span_forbidden"
