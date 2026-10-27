"""Enrollment, focus, step links and the same-window guide/progress reads.

The experience is bound only from the server's real scenario binding. A session whose
scenario hash has no installed AIPM content keeps its original meaning (409).
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from career_lab.contracts import v2 as C
from career_lab.storage.reference_graph import references
from career_lab.storage.v2_store import Mutation, ObjectWrite

from .projection import feedback_page, heads, project
from .types import (
    EXPERIENCE_REVISION,
    STEP_IDS,
    AipmFocus,
    AipmGuide,
    AipmProfile,
    AipmStepLink,
    CoverageRule,
    EnrollInput,
    FocusInput,
    MentorRule,
    StepLinkInput,
)

REPO = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AipmContent:
    """Installed content for one scenario hash. ``root`` and rules stay server-side."""

    scenario_hash: str
    content_revision: str
    work_language: str
    guide: AipmGuide
    root: Path | None = None
    design_public: dict | None = None
    design_rules: Path | None = None
    coverage_rules: tuple[CoverageRule, ...] = ()
    coverage_revision: str | None = None
    mentor_rules: tuple[MentorRule, ...] = ()
    mentor_revision: str | None = None


def authored(raw, key, model):
    """(revision, items) of a private coverage/mentor file; absent means none."""
    if raw is None:
        return None, ()
    data = json.loads(raw)
    if data.get("schema_version") != 1:
        raise C.ProtocolError("aipm_grading_file_invalid", status=503)
    return str(data.get("revision")), tuple(model.model_validate(i) for i in data.get(key, ()))


def _member(root, files, path, expected):
    ref = files.get(path)
    if ref is None or expected.get(path) != ref.sha256:
        return None
    raw = (root / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref.sha256:
        raise C.ProtocolError("aipm_content_identity_mismatch", status=503)
    return raw


def load_content(root):
    """Read the aipm/ members of one verified scenario package, or None if absent."""
    from career_lab.scenarios.v2.loader import load_package

    root = Path(root)
    if not (root / "aipm/manifest.json").is_file():
        return None
    package = load_package(root)
    files = {ref.path: ref for ref in package.bundle.files}
    if "aipm/manifest.json" not in files:
        return None
    manifest = json.loads(
        _member(
            root,
            files,
            "aipm/manifest.json",
            {"aipm/manifest.json": files["aipm/manifest.json"].sha256},
        )
    )
    if manifest.get("experience_revision") != EXPERIENCE_REVISION:
        return None
    language = manifest["work_language"]
    expected = {
        "aipm/" + k if not k.startswith("aipm/") else k: v for k, v in manifest["files"].items()
    }
    raw = _member(root, files, f"aipm/public/guide.{language}.json", expected)
    if raw is None:
        return None
    design = _member(root, files, f"aipm/public/design.{language}.json", expected)
    rules = "aipm/private/grading/design.json"
    coverage = authored(
        _member(root, files, "aipm/private/grading/coverage.json", expected), "items", CoverageRule
    )
    mentor = authored(
        _member(root, files, "aipm/private/grading/mentor.json", expected), "prompts", MentorRule
    )
    return AipmContent(
        scenario_hash=package.content_hash,
        content_revision=manifest["content_revision"],
        work_language=language,
        guide=AipmGuide.model_validate_json(raw),
        root=root,
        design_public=json.loads(design) if design else None,
        design_rules=root / rules if _member(root, files, rules, expected) else None,
        coverage_revision=coverage[0],
        coverage_rules=coverage[1],
        mentor_revision=mentor[0],
        mentor_rules=mentor[1],
    )


def default_contents():
    """Installed main packages plus explicit candidates in CAREER_LAB_AIPM_PACKAGES."""
    roots = []
    try:
        index = json.loads((REPO / "scenarios/pm_pilot/v2/installed/current.json").read_text())
        roots += [REPO / entry["root"] for entry in index.get("main", {}).values()]
    except (OSError, ValueError, KeyError):
        pass
    roots += [Path(p) for p in os.getenv("CAREER_LAB_AIPM_PACKAGES", "").split(os.pathsep) if p]
    found = []
    for root in roots:
        content = load_content(root)
        if content is not None:
            found.append(content)
    return found


def profile_of(view, auth):
    rows = [r for r in view.objects if r.ref.kind == "aipm_profile"]
    return AipmProfile.model_validate(rows[0].content) if rows else None


def enrolled(view, auth, catalog):
    """The content bound to this session, else an explicit not-enabled error."""
    content = catalog.get(view.bindings.scenario.sha256)
    if content is None:
        raise C.ProtocolError("aipm_not_enabled", status=409)
    profile = profile_of(view, auth)
    if profile is None and auth.allowed_objects is not None:
        # An object-narrowed grant cannot see the enrollment; say so instead of guessing.
        raise C.ProtocolError("aipm_scope_incomplete", status=403)
    if profile is None:
        raise C.ProtocolError("aipm_not_enrolled", status=409)
    if profile.scenario_hash != view.bindings.scenario.sha256 or (
        profile.content_revision != content.content_revision
    ):
        raise C.ProtocolError("aipm_binding_mismatch", status=409)
    return content


def require_owner(auth):
    if (
        auth.executor.kind != "human"
        or auth.actor_id != "learner"
        or "act" not in auth.capabilities
    ):
        raise C.ProtocolError("aipm_human_required", status=403)


def _write(kind, model, head, dependencies=()):
    content = model.model_dump(mode="json")
    ref = C.ObjectRef(
        session_id=model.session_id, kind=kind, object_id=model.id, version=model.revision
    )
    return ref, ObjectWrite(
        ref=ref,
        expected_head=head,
        content=content,
        visible_to=("learner",),
        dependencies=tuple(dependencies) or references(content),
    )


def now():
    return datetime.now(UTC)


def handlers(catalog, registry):
    def enroll(view, command, auth):
        require_owner(auth)
        EnrollInput.model_validate(command.payload)
        content = catalog.get(view.bindings.scenario.sha256)
        if content is None:
            raise C.ProtocolError("aipm_not_enabled", status=409)
        existing = profile_of(view, auth)
        if existing is not None:
            # Idempotent: the original binding is read back, never rebound.
            enrolled(view, auth, catalog)
            return Mutation(result={"profile": existing.model_dump(mode="json"), "created": False})
        profile = AipmProfile(
            session_id=auth.session_id,
            content_revision=content.content_revision,
            scenario_hash=view.bindings.scenario.sha256,
            work_language=content.work_language,
            enrolled_at=now(),
        )
        ref, write = _write("aipm_profile", profile, 0)
        return Mutation(
            writes=(write,),
            result={"ref": ref.model_dump(mode="json"), "profile": write.content, "created": True},
        )

    def set_focus(view, command, auth):
        require_owner(auth)
        enrolled(view, auth, catalog)
        body = FocusInput.model_validate(command.payload)
        head = heads(view.objects).get(("aipm_focus", "aipm-focus"))
        version = head.ref.version if head else 0
        focus = AipmFocus(
            session_id=auth.session_id,
            step_id=body.step_id,
            revision=version + 1,
            changed_by=auth.executor.id,
            changed_at=now(),
        )
        ref, write = _write("aipm_focus", focus, version)
        return Mutation(
            writes=(write,), result={"ref": ref.model_dump(mode="json"), "focus": write.content}
        )

    def save_link(view, command, auth):
        require_owner(auth)
        enrolled(view, auth, catalog)
        body = StepLinkInput.model_validate(command.payload)
        target = body.product_ref
        if target.kind != "product" or target.session_id != auth.session_id:
            raise C.ProtocolError("aipm_product_required")
        view.get(target)  # exact, visible version only
        key = f"{body.step_id}|{target.object_id}|{body.section_key or ''}"
        identity = "link-" + hashlib.sha256(key.encode()).hexdigest()[:24]
        head = heads(view.objects).get(("aipm_step_link", identity))
        version = head.ref.version if head else 0
        if head is not None and head.content["product_ref"] == target.model_dump(mode="json"):
            return Mutation(result={"ref": head.ref.model_dump(mode="json"), "link": head.content})
        link = AipmStepLink(
            id=identity,
            session_id=auth.session_id,
            step_id=body.step_id,
            product_ref=target,
            section_key=body.section_key,
            linked_by=auth.executor.id,
            revision=version + 1,
        )
        ref, write = _write("aipm_step_link", link, version, (target,))
        return Mutation(
            writes=(write,), result={"ref": ref.model_dump(mode="json"), "link": write.content}
        )

    def guide(view, query, auth):
        content = enrolled(view, auth, catalog)
        return content.guide.model_dump(mode="json")

    def progress(view, query, auth):
        content = enrolled(view, auth, catalog)
        focus_default = content.guide.steps[0].id
        return project(view, auth, content, registry, focus_default=focus_default).model_dump(
            mode="json"
        )

    def process_feedback(view, query, auth):
        enrolled(view, auth, catalog)
        return feedback_page(
            view, auth, cursor=query.cursor, limit=query.limit, step_id=query.step_id
        )

    return {
        "aipm.enroll": enroll,
        "aipm.focus.set": set_focus,
        "aipm.step_links.save": save_link,
        "aipm.guide.read": guide,
        "aipm.progress.read": progress,
        "aipm.process_feedback.read": process_feedback,
    }


def design_facts(content):
    """Trusted same-window facts for L2 rules. Missing facts stay unknown, never guessed."""
    from career_lab.aipm.design.rules import DesignFacts

    public = content.design_public or {}
    requirements = public.get("source_requirements") or {}
    scopes = {need["id"]: need["scope"] for need in public.get("starter_needs") or ()}

    def provider(view, auth):
        private = view.private_scenario_state
        sources = {}
        if private is not None and callable(view.reference_allowed):
            for key, material in requirements.items():
                version = private.source_versions.get(material)
                active = private.material_activation.get(f"{material}:{version}")
                if version is None or active is None or active > view.state.business_seq:
                    continue
                ref = C.EvidenceRefV2(
                    session_id=auth.session_id,
                    kind="material",
                    object_id=material,
                    version=version,
                    observed_at_seq=active,
                    valid_from_seq=active,
                )
                try:
                    if view.reference_allowed(ref):
                        sources[key] = (ref,)
                except C.ProtocolError:
                    continue
        # No execution tool is installed for these scopes; capabilities stay empty.
        return DesignFacts(public_sources=sources, need_scopes=scopes)

    return provider


BRIEF_REVISION = "aipm-brief-v1"
BRIEF_LIMIT = 300
# Short sheet names as the compass shows them (apps/web aipm-guide/sheets.ts).
BRIEF_WORDS = {
    "zh": {
        "short": {
            "business": "看懂业务",
            "stakeholders": "相关方",
            "need": "真需求",
            "boundary": "AI 边界",
            "solution": "方案",
            "assurance": "评测与回退",
            "decision": "上线决策",
        },
        "status": {
            "not_started": "未开始",
            "draft": "草稿",
            "based": "有依据",
            "solid": "站得住",
            "recheck": "需重新核对",
        },
        "edited": "批改后改过",
        "gaps": "还要再看",
        "join": "；",
        "quote": "「{}」",
    },
    "en": {
        "short": {
            "business": "Business",
            "stakeholders": "Stakeholders",
            "need": "Real need",
            "boundary": "AI boundary",
            "solution": "Solution",
            "assurance": "Evals & rollback",
            "decision": "Launch call",
        },
        "status": {
            "not_started": "not started",
            "draft": "draft",
            "based": "supported",
            "solid": "holds up",
            "recheck": "recheck",
        },
        "edited": "edited since review",
        "gaps": "still to look at ",
        "join": "; ",
        "quote": "“{}”",
    },
}
# Internal source ids such as SD-120 or BC-01; the brief names no source at all.
SOURCE_ID = re.compile(r"(?<![\w-])[A-Z]{2,}-\d+(?![\w-])")


def _numbered(order, language):
    return "①②③④⑤⑥⑦"[order - 1] if language == "zh" else str(order)


def _sheet_runs(states, words, language):
    """Consecutive sheets with the same state collapse into one run: ①②站得住；④–⑦未开始."""
    runs = []
    for order, step in enumerate(STEP_IDS, 1):
        state = states.get(step)
        word = words["status"][state.status if state else "not_started"]
        if state is not None and state.edited_since_review:
            word += f"（{words['edited']}）" if language == "zh" else f" ({words['edited']})"
        if runs and runs[-1][2] == word and runs[-1][1] == order - 1:
            runs[-1][1] = order
        else:
            runs.append([order, order, word])
    parts = []
    for first, last, word in runs:
        span = _numbered(first, language)
        if last > first:
            sep = "" if language == "zh" and last == first + 1 else "–"
            span += sep + _numbered(last, language)
        parts.append(span + ("" if language == "zh" else " ") + word)
    return words["join"].join(parts)


def colleague_brief(view, auth, language):
    """Where the learner is, for the colleagues' learner_state (YH's recognition hook).

    The step in focus, each sheet's state and the short gap labels of the latest review,
    in at most BRIEF_LIMIT characters. The review's findings, the answers it points to and
    source ids are never included. Read only; None outside an AI PM session or on error.
    """
    try:
        from .projection import heads, pending, scoped
        from .review import SEVERITY, reviews_of, sheets

        profile = profile_of(view, auth)
        if profile is None:
            return None
        # The colleague writes in the session's work language; the hook passes "en" for all.
        language = profile.work_language
        words = BRIEF_WORDS[language]
        objects = scoped(view, auth) if auth is not None else view.objects
        latest = heads(objects).values()
        designs = [r for r in latest if r.ref.kind == "aipm_design"]
        design = max(
            designs, key=lambda r: (r.created_storage_revision, r.ref.version), default=None
        )
        focuses = [r for r in latest if r.ref.kind == "aipm_focus"]
        focus_row = max(focuses, key=lambda r: r.ref.version, default=None)
        focus = focus_row.content["step_id"] if focus_row else STEP_IDS[0]
        drafts = {step for draft in pending(objects) for step in draft.steps}
        states, _ = sheets(view, objects, design.content if design else None, drafts)

        def name(step):
            return _numbered(STEP_IDS.index(step) + 1, language) + " " + words["short"][step]

        brief = {
            "revision": BRIEF_REVISION,
            "step": name(focus),
            "sheets": _sheet_runs(states, words, language),
        }
        row = next(iter(reviews_of(objects)), None)
        if row is not None:
            review = row.content
            open_marks = sorted(
                (m for m in review.get("coverage") or () if m["mark"] != "covered"),
                key=lambda m: SEVERITY[m["severity"]],
            )
            labels = []
            for mark in open_marks:
                label = str(mark["label"]).strip()
                if label and label not in labels and not SOURCE_ID.search(label):
                    labels.append(label)
            for keep in (2, 1, 0):
                line = name(review["step_id"])
                if labels[:keep]:
                    quoted = ("、" if language == "zh" else ", ").join(
                        words["quote"].format(label) for label in labels[:keep]
                    )
                    line += ("：" if language == "zh" else ": ") + words["gaps"] + quoted
                brief["latest_review"] = line
                if _size(brief) <= BRIEF_LIMIT:
                    break
        return brief if _size(brief) <= BRIEF_LIMIT else None
    except Exception:  # noqa: BLE001 - the brief is an annotation, never a reason to fail
        return None


def _size(brief):
    """Characters the brief adds to the colleague's context, keys included."""
    return len(json.dumps(brief, ensure_ascii=False, separators=(",", ":")))
