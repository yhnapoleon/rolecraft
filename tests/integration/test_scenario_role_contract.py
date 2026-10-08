"""Author boundary checks; public build/entry wiring remains a separate integration gate."""

from career_lab.scenario_compiler.boundaries import validate_boundary


def test_SCN_01_missing_role_and_confirmation_stays_candidate():
    result = validate_boundary({}, installed_effects={}, confirmed_digest=None)
    assert result.status == "needs_confirmation"
    assert {issue.location for issue in result.issues} >= {"roles", "extensions", "title"}
    assert result.public_description is None


def declaration(role="aipm"):
    terms = {
        "inputs": ["brief"],
        "outputs": ["pilot_decision"],
        "actions": ["test_assistant"],
        "consequences": ["test_record"],
        "permissions": ["read", "test"],
        "resources": [{"name": "operators", "unit": "seats", "amount": 3.0}],
    }
    return {
        "title": {"zh": "知识助手试点", "en": "Knowledge assistant pilot"},
        "roles": [
            {
                "role": role,
                "task_id": "pilot_decision",
                "execution_mode": "business_decision",
                "zh": {"responsibility": "形成有依据的试点决定", "terms": terms},
                "en": {"responsibility": "Decide on an evidence-based pilot", "terms": terms},
            }
        ],
        "extensions": [{"zh": "更多已审核范围", "en": "Additional reviewed scopes"}],
        "unsupported": [{"zh": "任意代码执行", "en": "Arbitrary code execution"}],
    }


def check(value, confirmed=True, effects=None):
    from career_lab.contracts.v2.core import digest

    return validate_boundary(
        value,
        installed_effects=effects
        if effects is not None
        else {"test_assistant": frozenset({"test_record"})},
        confirmed_digest=digest(value) if confirmed else None,
    )


def test_SCN_02_pm_aliases_produce_one_aipm_description():
    for alias in ("pm", "ai_pm", "aipm"):
        result = check(declaration(alias))
        assert result.status == "ready_for_review"
        assert [role.role for role in result.public_description.roles] == ["aipm"]


def test_SCN_02_duplicate_alias_does_not_create_another_role():
    value = declaration()
    value["roles"].append(declaration("pm")["roles"][0])
    result = check(value)
    assert result.status == "needs_confirmation"
    assert "duplicate_role" in {issue.code for issue in result.issues}


def test_SCN_03_engineer_cannot_repeat_aipm_task():
    value = declaration()
    engineer = declaration("engineer")["roles"][0]
    engineer["execution_mode"] = "bounded_config"
    value["roles"].append(engineer)
    result = check(value)
    assert result.status == "needs_confirmation"
    assert "role_responsibilities_overlap" in {issue.code for issue in result.issues}


def test_SCN_03_arbitrary_code_is_not_a_supported_engineer_mode():
    value = declaration("engineer")
    value["roles"][0]["execution_mode"] = "arbitrary_code"
    result = check(value)
    assert result.status == "unsupported"
    assert "execution_mode_unsupported" in {issue.code for issue in result.issues}


def test_SCN_04_uninstalled_action_or_consequence_cannot_be_advertised():
    for effects in ({}, {"test_assistant": frozenset({"different_consequence"})}):
        result = check(declaration(), effects=effects)
        assert result.status == "unsupported"
        assert "capability_unavailable" in {issue.code for issue in result.issues}
        assert result.public_description is None


def test_SCN_05_translated_resource_or_permission_drift_is_rejected():
    from copy import deepcopy

    for field, replacement in (
        ("permissions", ["read", "approve"]),
        ("resources", [{"name": "operators", "unit": "seats", "amount": 30.0}]),
    ):
        value = deepcopy(declaration())
        value["roles"][0]["en"]["terms"] = deepcopy(value["roles"][0]["en"]["terms"])
        value["roles"][0]["en"]["terms"][field] = replacement
        result = check(value)
        assert result.status == "needs_confirmation"
        assert "translated_business_terms_differ" in {issue.code for issue in result.issues}


def test_SCN_01_stale_confirmation_does_not_authorize_changed_content():
    from career_lab.contracts.v2.core import digest

    value = declaration()
    original_confirmation = digest(value)
    value["extensions"][0]["en"] = "Unlimited new domains"
    result = validate_boundary(
        value,
        installed_effects={"test_assistant": frozenset({"test_record"})},
        confirmed_digest=original_confirmation,
    )
    assert result.status == "needs_confirmation"
    assert result.public_description is None


def test_SCN_01_missing_confirmation_never_returns_a_public_description():
    result = check(declaration(), confirmed=False)
    assert result.status == "needs_confirmation"
    assert result.public_description is None


def test_SCN_03_renaming_same_task_does_not_create_engineer_responsibility():
    value = declaration()
    engineer = declaration("engineer")["roles"][0]
    engineer["task_id"] = "renamed_task"
    engineer["execution_mode"] = "bounded_config"
    value["roles"].append(engineer)
    result = check(value)
    assert result.status == "needs_confirmation"
    assert "role_responsibilities_overlap" in {issue.code for issue in result.issues}
