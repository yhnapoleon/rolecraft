"""Actual chunk retrieval/configuration behavior; no gold or path inputs."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from typing import Literal

from career_lab.assistant.retrieval import tokens
from career_lab.contracts.v2.core import ProtocolError, VersionPoint, ObjectRef, digest
from career_lab.contracts.v2.world import TestResultV2, TestExecutionMetadata, RetrievedChunk
from career_lab.scenarios.v2.engine import ScenarioEngine
from career_lab.scenarios.v2.policy import effective_config, canonical_domains


@dataclass(frozen=True)
class RetrievalTuning:
    """Internal parameters pending public AssistantConfig fields; no wire schema."""
    min_score: float = 0.35
    freshness_guard: Literal["none", "warn", "fallback"] = "none"
    manual_domains: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.freshness_guard, str) or self.freshness_guard not in {"none", "warn", "fallback"}:
            raise ValueError("freshness_guard must be none, warn or fallback")
        if not math.isfinite(self.min_score) or self.min_score < 0:
            raise ValueError("min_score must be finite and nonnegative")


@dataclass(frozen=True)
class TestExecution:
    result: TestResultV2
    provenance: dict


@dataclass(frozen=True)
class Chunk:
    id: str
    material_id: str
    version: int
    domain: str
    text: str
    ref: object


def meaningful_tokens(text):
    for generic in ("如何", "怎么", "什么", "多少", "请问", "是否", "可以", "一下", "是多少", "怎么办"):
        text = text.replace(generic, " ")
    return set(tokens(text))


def chunks(material, fragments, size):
    result = []
    for fragment in fragments:
        if fragment.ref.span_start is None:
            # A paraphrase cannot truthfully cite the original private span.
            # Role paraphrases are conversation material, never assistant KB.
            continue
        for start in range(0, len(fragment.text), size):
            value = fragment.text[start:start+size]
            if not value.strip(): continue
            begin = fragment.ref.span_start + start
            ref = fragment.ref.model_copy(update={"span_start":begin,"span_end":begin+len(value),"quote":value})
            identity = digest([material.id,material.version,begin,begin+len(value),value])
            result.append(Chunk(identity,material.id,material.version,material.domain,value,ref))
    return result


class Assistant:
    def __init__(self, package):
        self.package=package

    def run(self, snapshot, request, auth, request_id, *, tuning=None, now=None, operation_name="test_assistant"):
        engine=ScenarioEngine(self.package)
        engine.authorize(auth,snapshot,operation_name)
        # TestResultV2 contains the complete requested/effective config. Reading
        # that execution dependency requires an explicit config grant.
        engine.authorize(auth,snapshot,operation_name,"read")
        if auth.allowed_objects is not None and snapshot.config.id not in auth.allowed_objects:
            raise ProtocolError("config_forbidden",status=403)
        if snapshot.world.status!="active":
            raise ProtocolError("session_"+snapshot.world.status,status=409)
        if request.config_version!=snapshot.config.config_version:
            raise ProtocolError("config_not_current",status=409)
        if not request.query.strip():
            raise ProtocolError("query_empty")
        configured_tuning=RetrievalTuning(snapshot.config.min_score,snapshot.config.freshness_guard,snapshot.config.manual_domains)
        if tuning is not None and tuning!=configured_tuning:
            raise ProtocolError("config_tuning_mismatch", "apply tuning as an explicit configuration version",409)
        tuning=configured_tuning
        if set(canonical_domains(self.package,tuning.manual_domains))-self.package.bundle.domains.keys():
            raise ProtocolError("unknown_manual_domain")
        conf=effective_config(self.package,snapshot.config,snapshot.world.resources)
        cfg=conf.effective
        versions=snapshot.source_versions if cfg.update_strategy=="realtime" else snapshot.indexed_versions
        visible=self.package.visible_materials(versions,auth.actor_id,snapshot.world.business_seq,snapshot.world.session_id,kb_only=True)
        if auth.allowed_objects is not None:
            visible=tuple((m,fs) for m,fs in visible if m.id in auth.allowed_objects)
        candidates=[c for m,fs in visible for c in chunks(m,fs,cfg.chunk_size)]
        query_terms=meaningful_tokens(request.query)
        scored=[]
        for candidate in candidates:
            overlap=query_terms & meaningful_tokens(candidate.text)
            # Normalized query coverage avoids a shared "如何" returning every FAQ.
            score=len(overlap)/max(1,len(query_terms))
            if overlap and score>=tuning.min_score:
                scored.append((score,candidate))
        scored.sort(key=lambda x:(-x[0],x[1].id))
        selected=[]; status="fallback"; code=None; answer=""; selected_stale=False
        forbidden=tuple(self.package.rules["mandatory_prohibited_topics"])+tuple(cfg.prohibited_topics)
        if any(term.casefold() in request.query.casefold() for term in forbidden) or any(re.search(pattern,request.query) for pattern in self.package.rules.get("credential_request_patterns",())):
            code="prohibited_topic"
        elif not scored:
            code="no_retrieval_hit"
        else:
            scoped=[pair for pair in scored if not cfg.scope_filter or pair[1].domain in cfg.domains]
            if not scoped: code="outside_scope"
            else:
                selected=[c for _,c in scoped[:cfg.retrieval_limit]]
                selected_stale=any(c.version!=snapshot.source_versions[c.material_id] for c in selected)
                manual=set(canonical_domains(self.package,tuning.manual_domains))|(set(self.package.rules.get("mutable_domains",["policy"])) if cfg.update_strategy=="manual_policy" else set())
                if any(c.domain in manual for c in selected):
                    code="manual_verification_required";selected=[]
                elif selected_stale and tuning.freshness_guard == "fallback":
                    code="stale_source_guard";selected=[]
                else:
                    warn=selected_stale and tuning.freshness_guard == "warn"
                    status="answered_with_warning" if warn else "answered"
                    answer="\n\n".join(c.text for c in selected)
                    if warn: answer="来源索引版本落后，以下内容须核验当前政策。\n"+answer
        if code:
            if cfg.fallback=="human":
                answer={"prohibited_topic":"该主题禁止自动回答，请向授权负责人核验。",
                        "outside_scope":"该问题超出当前开放知识范围，请转人工核验。",
                        "no_retrieval_hit":"未检索到可靠依据，请转人工核验。",
                        "manual_verification_required":"该知识域需要人工核验，当前未作自动回答。",
                        "stale_source_guard":"索引与源版本不一致，新鲜度守卫已阻止自动回答。"}[code]
            else:
                status="failed"
                answer="当前无法可靠自动回答，且人工兜底尚未生效。"
        sid=snapshot.world.session_id;seq=snapshot.world.business_seq
        refs=tuple(c.ref.model_copy(update={"observed_at_seq":seq,
                "valid_from_seq":snapshot.material_activation.get(f"{c.material_id}:{c.version}",0)}) for c in selected)
        point=VersionPoint(business_seq=seq,workspace_revision=snapshot.world.workspace_revision,storage_revision=snapshot.world.storage_revision)
        rid=digest(["w02-test",sid,request_id,request.model_dump(mode="json"),cfg.model_dump(mode="json"),point.model_dump(mode="json"),tuning.__dict__,digest(auth)])
        source_visible={m.id for m,_ in self.package.visible_materials(snapshot.source_versions,auth.actor_id,seq,sid,kb_only=True)}
        if auth.allowed_objects is not None:source_visible &= set(auth.allowed_objects)
        executed_at=now or datetime.now(timezone.utc)
        if executed_at.tzinfo is None or executed_at.utcoffset() is None:raise ProtocolError("execution_timezone_required")
        scores={chunk.id:score for score,chunk in scored}
        execution=TestExecutionMetadata(executed_at=executed_at,executor=auth.executor,
            source_versions={k:v for k,v in snapshot.source_versions.items() if k in source_visible},
            indexed_versions={k:v for k,v in snapshot.indexed_versions.items() if k in source_visible},
            used_versions={k:v for k,v in versions.items() if k in source_visible},
            chunks=tuple(RetrievedChunk(id=c.id,material_id=c.material_id,version=c.version,ref=ref,score=scores[c.id]) for c,ref in zip(selected,refs)),
            projection_actor=auth.actor_id,attempts=(),cost_complete=True)
        config_ref=ObjectRef(session_id=sid,kind="config",object_id=snapshot.config.id,version=snapshot.config.version,config_version=snapshot.config.config_version)
        result=TestResultV2(id=rid,execution=execution,config_ref=config_ref,session_id=sid,query=request.query,config=conf,status=status,answer=answer,
            citations=refs,as_of=point,declared_category=request.declared_category,
            declared_expected=request.declared_expected,observed_coverage=tuple(sorted({c.domain for c in selected})),
            error_code=code)
        source_visible={m.id for m,_ in self.package.visible_materials(snapshot.source_versions,auth.actor_id,seq,sid,kb_only=True)}
        if auth.allowed_objects is not None:source_visible &= set(auth.allowed_objects)
        return TestExecution(result, {
            "mode":"local-extractive-v2", "scenario_hash":self.package.content_hash,
            "created_at":executed_at.isoformat(),
            "source_versions":{k:v for k,v in snapshot.source_versions.items() if k in source_visible},
            "indexed_versions":{k:v for k,v in snapshot.indexed_versions.items() if k in source_visible},
            "used_versions":{k:v for k,v in versions.items() if k in source_visible},
            "chunk_ids":[c.id for c in selected],
            "tuning":dict(tuning.__dict__),"executor":auth.executor.model_dump(mode="json"),
            "authorization_digest":digest(auth),"retrieved_source_stale":selected_stale,
            "declared_expectation_is_gold":False,"result_is_evaluation":False})
