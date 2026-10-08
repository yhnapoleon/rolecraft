"""Private/nonexistent query pairs and positive neutralization, controlled model only."""

from dataclasses import replace
import json
from urllib.parse import quote
import pytest
from career_lab.contracts.v2 import ProtocolError, TurnInput, DisclosedFragment, EvidenceRefV2
from career_lab.runtime.context_v2 import assemble_context
from career_lab.runtime.model_adapter import ScriptedModel, ModelReply
from career_lab.storage.role_memory import RoleMemory
from test_context import (
    package,
    catalog,
    private_sample,
    disclosure_samples,
    frame,
    owner,
    share_receipt,
)
from test_runtime import request, generate


def turn(snap, text):
    req = request(owner(), role_id=snap.role.id)
    return req.model_copy(update={"input": TurnInput(role_id=snap.role.id, text=text)})


def run_pair(snap, query, kind):
    req = turn(snap, query)

    class Probe:
        revision = "controlled-oracle-probe"
        calls = []

        def complete(self, messages, tools):
            self.calls.append(messages)
            if kind == "echo_prompt":
                return ModelReply(text="待核实的输入：" + messages[-1]["content"])
            if kind == "echo_raw":
                return ModelReply(text="引用 " + query)
            return ModelReply(text="请提供可核对的公开材料。")

    model = Probe()
    model.calls = []
    attempts = []
    try:
        reply, audit = generate(snap, owner(), req, model, sink=attempts)
        public = {
            "status": reply.status,
            "question": reply.question,
            "error": reply.error_code,
            "text": reply.text,
        }
    except ProtocolError as exc:
        public = {
            "status": exc.status,
            "question": req.input.text,
            "error": exc.code,
            "text": str(exc),
        }
    assert len(model.calls) == 1 and len(attempts) == 1
    return public, model.calls[0][-1]["content"]


@pytest.mark.parametrize(
    "pair",
    [
        ("tech_private", "nope_unknown"),
        ("isolation_marker", "unlocated_marker"),
        ("retrieval_debug_code", "unlocated_debug_code"),
        ("material:tech_private@1", "material:nope_unknown@1"),
        ("tech_private-v1.md", "nope_unknown-v1.md"),
        ("materials/tech_private-v1.md", "materials/nope_unknown-v1.md"),
        ("private-source-1", "private-source-999"),
    ],
)
@pytest.mark.parametrize("encoding", ["plain", "double_url", "unicode", "fullwidth"])
@pytest.mark.parametrize("kind", ["constant", "echo_prompt", "echo_raw"])
def test_private_and_user_defined_queries_preserve_input_with_real_private_guard(
    package, catalog, pair, encoding, kind
):
    snap = assemble_context(catalog, frame(package, catalog))

    def encode(value):
        if encoding == "double_url":
            return quote(quote(value, safe=""), safe="")
        if encoding == "unicode":
            return value.replace("_", chr(92) + "u005f").replace("-", chr(92) + "u002d")
        if encoding == "fullwidth":
            return "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E else c for c in value)
        return value

    queries = ["请解释 " + encode(x) + ". 的内容" for x in pair]
    (a, pa), (b, pb) = [run_pair(snap, q, kind) for q in queries]
    assert a["question"] == queries[0] and b["question"] == queries[1]
    # SQ-01 covers identifier-existence parity. Do not block arbitrary user
    # names to obtain that parity; real private references remain protected.
    alias = pair[0].startswith("private-source-")
    if kind == "constant" or (kind == "echo_prompt" and not alias):
        assert a["status"] == b["status"] == "completed" and a["error"] is b["error"] is None
    else:
        assert a["error"] == "role_output_blocked"
        if alias:
            assert b["error"] == "role_output_blocked"
        else:
            assert b["status"] == "completed" and b["error"] is None


@pytest.mark.parametrize(
    "value",
    [
        "private-source-1",
        "private-source-999",
        quote(quote("private-source-1", safe="-"), safe=""),
        "ｐｒｉｖａｔｅ－ｓｏｕｒｃｅ－１",
        "private-\u200bsource-1",
    ],
)
def test_internal_alias_echo_is_blocked_even_when_not_assigned(package, catalog, value):
    snap = assemble_context(catalog, frame(package, catalog))
    with pytest.raises(ProtocolError) as exc:
        generate(
            snap,
            owner(),
            request(owner()),
            ScriptedModel([ModelReply(text="依据来自 " + value + "。")]),
        )
    assert exc.value.code == "role_output_blocked" and "private-source" not in str(exc.value)


def test_source_memory_question_neutralization_retains_approved_prose(
    package, catalog, private_sample
):
    raw = "material:" + private_sample["fact"].source.object_id + "@1"
    approved = private_sample["approved"]
    memory = RoleMemory(
        DisclosedFragment(
            ref=EvidenceRefV2(
                session_id="s",
                kind="role_reply",
                object_id="oldreply",
                version=1,
                observed_at_seq=0,
            ),
            text="历史原话 " + raw + "；" + approved,
            channel="memory",
            verification="verified",
        ),
        private_sample["role"].id,
    )
    snap = assemble_context(
        catalog, frame(package, catalog, private_sample["role"].id, memories=(memory,))
    )
    source = next(s for s in snap.context.sources if s.text == approved)
    changed = source.model_copy(update={"text": source.text + " 参见 " + raw})
    snap = replace(
        snap,
        context=snap.context.model_copy(
            update={"sources": tuple(changed if s == source else s for s in snap.context.sources)}
        ),
    )
    req = turn(snap, "请核对 " + raw + " 并保留获准说明")
    model = ScriptedModel([ModelReply(text=approved)])
    reply, audit = generate(snap, owner(), req, model)
    payload = json.loads(model.calls[0][0]["content"].split("\nCONTEXT\n", 1)[1])
    entries = [
        s["text"] for s in payload["sources"] if "参见" in s["text"] or "历史原话" in s["text"]
    ]
    assert len(entries) == 2 and all("[来源引用]" in text and approved in text for text in entries)
    assert raw not in json.dumps(model.calls, ensure_ascii=False)
    assert "[来源引用]" in model.calls[0][-1]["content"]
    assert reply.question == req.input.text and reply.text == approved


def test_public_identifiers_shared_version_and_english_prose_stay_intact(
    package, catalog, private_sample
):
    receipt = share_receipt(2, "已授权的第二版方案")
    snap = assemble_context(
        catalog, frame(package, catalog, private_sample["role"].id, shares=(receipt,))
    )
    public = next(
        m for m in catalog.materials if ("material", m.id) not in catalog.private_source_objects()
    )
    fact = next(f for f in catalog.facts if f.disclosure.mode == "public")
    query = f"Please explain material:{public.id}@{public.version} and product:plan@2 through share:share-2@1, including {fact.id}."
    reply, audit = generate(
        snap,
        owner(),
        turn(snap, query),
        ScriptedModel([ModelReply(text=query + " " + private_sample["approved"])]),
    )
    assert reply.question == query and reply.text == query + " " + private_sample["approved"]
    assert audit.prompt_messages[-1].content == query
    assert receipt.fragment.text in audit.prompt_messages[0].content


def test_original_question_with_private_fact_has_no_special_prompt_error(
    package, catalog, disclosure_samples
):
    snap = assemble_context(catalog, frame(package, catalog))
    for fact in disclosure_samples["never"]:
        query = "请解释 " + fact.id
        public, prompt = run_pair(snap, query, "constant")
        assert (
            public["status"] == "completed"
            and public["question"] == query
            and public["error"] is None
        )
        assert fact.id not in prompt and "[来源引用]" in prompt


@pytest.mark.parametrize(
    "pair", [("tech_private", "nope_unknown"), ("isolation_marker", "unlocated_marker")]
)
@pytest.mark.parametrize("echo_raw", [False, True])
def test_pair_survives_real_store_worker_and_public_replay(
    tmp_path, package, catalog, pair, echo_raw
):
    # Real common transaction/worker/read/replay with explicitly bounded private
    # fixture. This is not the production full-generation carrier.
    from career_lab.runtime.roles_v2 import RoleService
    from career_lab.runtime.context_v2 import ContextPort
    from career_lab.contracts.v2 import Command, ObjectRef
    from career_lab.api.modules import ExtensionRegistry, Gateway
    from career_lab.jobs.repository import JobRepository
    from career_lab.jobs.worker import Worker, ClaimedHandler
    from test_private_port_boundary import (
        ControlledSnapshot,
        ControlledPrivatePort,
        ControlledReplyVerifier,
    )
    from test_runtime import common_store

    outcomes = []
    for i, identifier in enumerate(pair):
        folder = tmp_path / str(i)
        folder.mkdir()
        store, auth = common_store(folder, catalog)
        query = "请解释 " + identifier + " 的内容"
        model = ScriptedModel([ModelReply(text=query if echo_raw else "请提供可核对的公开材料。")])
        private = ControlledPrivatePort()
        service = RoleService(
            ContextPort(catalog, ControlledSnapshot(package, catalog)),
            model,
            private_port=private,
            reply_verifier=ControlledReplyVerifier(),
        )
        registry = ExtensionRegistry()
        service.install(registry)
        gateway = Gateway(store, registry)
        view = store.view(auth)
        command = Command(
            schema_version=2,
            request_id="pair",
            operation="turns.create",
            expected_version=view.state.business_seq,
            expected_workspace_revision=view.state.workspace_revision,
            payload=TurnInput(role_id="tech_lead", text=query).model_dump(mode="json"),
        )
        queued = gateway.dispatch(auth, "turns.create", command.model_dump(mode="json"))
        assert queued["result"]["question"] == query
        jobs = JobRepository(store.db)
        worker = Worker(
            jobs,
            {
                "v2.role_turn": ClaimedHandler(
                    lambda payload, claim: gateway.run_job("v2.role_turn", payload, claim=claim)
                )
            },
        )
        worker.run_once()
        job = jobs.get(queued["result"]["queued_jobs"][0])
        assert len(model.calls) == 1
        replay = gateway.dispatch(auth, "turns.create", command.model_dump(mode="json"))
        assert replay["result"]["question"] == query
        turns = [x for x in store.view(auth).objects if x.ref.kind == "role_turn"]
        assert len(turns) == 1 and turns[0].content["input"]["text"] == query
        if echo_raw and i == 0:
            assert job["status"] == "failed" and job["error"] == "role_output_blocked"
            assert not [x for x in store.view(auth).objects if x.ref.kind == "role_reply"]
            outcomes.append((job["status"], job["error"], None))
        else:
            assert job["status"] == "completed"
            reply = next(x for x in store.view(auth).objects if x.ref.kind == "role_reply")
            assert store.read(auth, reply.ref).content["question"] == query
            assert reply.content["question"] == query and reply.content["error_code"] is None
            outcomes.append((job["status"], job["error"], reply.content["text"]))
    if echo_raw:
        assert outcomes[0][0] == "failed" and outcomes[1][0] == "completed"
    else:
        assert outcomes[0] == outcomes[1]
