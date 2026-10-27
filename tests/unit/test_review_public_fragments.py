"""Review candidates keep the source's public fragment boundaries and original offsets."""

from dataclasses import fields, replace
from hashlib import sha256
from types import SimpleNamespace

import pytest

from career_lab.api.vertical_reads import public_material_resolver
from career_lab.contracts import v2 as C
from career_lab.evidence.v2.assembler import EvidenceAssemblerV2
from career_lab.evidence.v2.ports import CriterionPolicy, RuleSnapshot, SourceRecord, VerifiedFact
from career_lab.scenarios.v2.evaluation_facts import ScenarioFactAdapter
from career_lab.scenarios.v2.module import ScenarioModule


@pytest.fixture(params=["zh", "en"])
def source_case(tmp_path, request):
    parts = (
        ["公开标题", "待确认", "第一句原文。第二句原文。", "第三句原文。第四句原文。"]
        if request.param == "zh"
        else [
            "Public title",
            "Pending confirmation",
            "First original sentence. Second original sentence.",
            "Third original sentence. Fourth original sentence.",
        ]
    )
    outside = "片段外说明。" if request.param == "zh" else "Notice outside the public fragments."
    text = outside + "\n\n" + parts[0] + "\n" + parts[1] + "\n\n" + "\n\n".join(parts[2:])
    (tmp_path / "source.txt").write_text(text)
    file = C.FileRef(path="source.txt", sha256=sha256(text.encode()).hexdigest())
    at = C.VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0)
    auth = C.AuthContext(
        session_id="s",
        actor_id="learner",
        credential_id="owner",
        executor=C.Executor(id="owner", kind="human"),
        capabilities=("read",),
    )
    bare = C.ObjectRef(session_id="s", kind="material", object_id="doc", version=1)
    ref = C.EvidenceRefV2(**bare.model_dump(), observed_at_seq=0)
    fragments = tuple(
        SimpleNamespace(
            ref=ref.model_copy(
                update={
                    "span_start": text.index(part),
                    "span_end": text.index(part) + len(part),
                    "quote": part,
                }
            ),
            text=part,
            disclosure=SimpleNamespace(mode="public", actors=()),
        )
        for part in parts
    )
    module = ScenarioModule.__new__(ScenarioModule)
    module.bindings = SimpleNamespace(scenario=file)
    module.files = {"source.txt": file}
    module.package = SimpleNamespace(
        root=tmp_path,
        rules={
            "initial_material_versions": {"doc": 1},
            "material_files": {"doc": {"1": "source.txt"}},
        },
        project=lambda *_: fragments,
        material=lambda *_: SimpleNamespace(fragments=fragments),
    )
    world = C.WorldStateV2(
        session_id="s",
        cycle_id="cycle",
        resources={},
        **{k: getattr(at, k) for k in ("business_seq", "workspace_revision", "storage_revision")},
    )
    snapshot = SimpleNamespace(world=world, material_activation={"doc:1": 0})
    window = SimpleNamespace(snapshot=snapshot, bindings=module.bindings, points=(at,))
    resolver = public_material_resolver(module)

    def resolve(ref):
        return resolver(
            auth,
            ref,
            at,
            module.bindings,
            scenario_state=SimpleNamespace(session_id="s", material_activation={"doc:1": 0}),
        )

    adapter = ScenarioFactAdapter(
        module,
        authorize=lambda _: None,
        window_reader=lambda *_: window,
        record_reader=lambda *_: None,
        reference_resolver=lambda _, ref, __: resolve(ref),
    )
    product_ref = C.EvidenceRefV2(
        session_id="s", kind="product", object_id="prd", version=1, observed_at_seq=0
    )
    product = SourceRecord(product_ref, "A saved proposal.", at)

    class Reader:
        plain = False

        def read(self, _, evidence, __):
            if evidence.kind == "product":
                return product
            value = adapter.source_reader(auth, evidence, at)
            if self.plain:
                value = SourceRecord(
                    **{field.name: getattr(value, field.name) for field in fields(SourceRecord)}
                )
            return replace(value, quote_scope="explicit_only")

    reader = Reader()
    whole = ref.model_copy(update={"span_start": 0, "span_end": len(text), "quote": text})

    def assemble(unitize, evidence=bare, proof=False):
        assembler = EvidenceAssemblerV2(reader, model_bytes=64000, work_language=request.param)
        assembler.unitize = unitize
        return assembler.assemble(
            auth=auth,
            subject_id="prd",
            subjects=(product_ref,),
            evidence_refs=(evidence,),
            purpose="plan",
            decision="no_go",
            as_of=at,
            policy=CriterionPolicy("R1.target", "Check evidence"),
            snapshot=RuleSnapshot(
                as_of=at, facts=(VerifiedFact("document", True, (whole,)),) if proof else ()
            ),
            anchor_mode="submission",
        )

    return SimpleNamespace(**locals())


def test_units_stay_in_one_public_fragment_and_keep_every_sentence(source_case):
    e = source_case
    package = e.assemble(True, proof=True)
    materials = [c for c in package.candidate_evidence if c.ref.kind == "material"]
    expected = e.parts[:2] + (
        ["第一句原文。", "第二句原文。", "第三句原文。", "第四句原文。"]
        if e.request.param == "zh"
        else [
            "First original sentence.",
            "Second original sentence.",
            "Third original sentence.",
            "Fourth original sentence.",
        ]
    )
    assert [c.text for c in materials] == expected
    for candidate in materials:
        ref = candidate.ref
        assert e.text[ref.span_start : ref.span_end] == ref.quote == candidate.text
        assert any(
            f.ref.span_start <= ref.span_start < ref.span_end <= f.ref.span_end for f in e.fragments
        )
        e.resolve(ref)
    assert e.outside not in [c.text for c in materials]
    # Rule proof remains the full original document and still passes its existing exception.
    assert package.rule_context["fact_refs"]["document"][0] == e.whole.model_dump(mode="json")
    e.resolve(e.whole)


def test_explicit_excerpt_is_not_expanded_and_forgery_is_still_rejected(source_case):
    e = source_case
    sentence = "第一句原文。" if e.request.param == "zh" else "First original sentence."
    start = e.text.index(sentence)
    excerpt = e.ref.model_copy(
        update={"span_start": start, "span_end": start + len(sentence), "quote": sentence}
    )
    package = e.assemble(True, excerpt)
    materials = [c for c in package.candidate_evidence if c.ref.kind == "material"]
    assert len(materials) == 1 and materials[0].ref == excerpt
    with pytest.raises(C.ProtocolError) as rejected:
        e.resolve(excerpt.model_copy(update={"quote": "Invented"}))
    assert rejected.value.code == "reference_span_forbidden"


def test_unitize_off_is_byte_identical_and_does_not_require_fragment_metadata(source_case):
    e = source_case
    with_boundaries = e.assemble(False, proof=True)
    e.reader.plain = True
    without_boundaries = e.assemble(False, proof=True)
    assert C.canonical(with_boundaries) == C.canonical(without_boundaries)
    with pytest.raises(C.ProtocolError) as rejected:
        e.assemble(True)
    assert rejected.value.code == "public_material_fragments_unavailable"
