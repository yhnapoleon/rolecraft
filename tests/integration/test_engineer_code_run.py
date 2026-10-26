"""The coding exercise of an engineer ticket: run, review attachment and isolation."""

import json

from test_engineer_session import Eng, draft, hidden_queries, sign, ticket_path
from test_engineer_session import eng as eng

from career_lab.engineer import coding

EXERCISE = coding.EXERCISES / coding.EXERCISE_ID


def run(eng: Eng, ticket: dict, code: str, key: str, **kw):
    return eng.call(
        ticket_path(ticket, "code-runs"),
        "engineer.code.run",
        {"ticket_id": ticket["id"], "code": code},
        key,
        **kw,
    )


def skeleton(eng: Eng) -> str:
    return (EXERCISE / ("skeleton." + eng.language + ".txt")).read_text(encoding="utf-8")


def reference() -> str:
    return (EXERCISE / "reference.txt").read_text(encoding="utf-8")


def test_detail_offers_the_exercise_without_hidden_cases(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert detail["code_exercise"]["public_cases"] == 6
    assert detail["code_exercise"]["hidden_cases"] == 5
    assert detail["code_runs"] == []
    read = eng.ok(eng.read(ticket_path(ticket, "code")))
    exercise = read["exercise"]
    assert exercise["function"] == "current_limit"
    assert exercise["skeleton"] == skeleton(eng)
    assert [case["id"] for case in exercise["public_cases"]] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert exercise["hidden_cases"] == 5
    assert read["code_runs"] == [] and read["latest_code_run"] is None
    raw = json.dumps([detail, read], ensure_ascii=False)
    hidden = json.loads((EXERCISE / (eng.language + ".json")).read_text(encoding="utf-8"))
    for case in hidden["cases"]:
        if not case["public"]:
            assert case["point"] not in raw and '"' + case["id"] + '"' not in raw
    assert "400.00" not in raw  # a hidden case's own way of writing the amount


def test_skeleton_fails_and_reference_passes(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    first = eng.ok(run(eng, ticket, skeleton(eng), "c1"))["code_run"]
    assert first["status"] == "completed" and not first["all_passed"]
    results = {row["id"]: row["result"] for row in first["public"]}
    # The top chunk's first number: the taxi limit, the old version, no warning.
    assert results == {
        "P1": "pass",
        "P2": "fail",
        "P3": "fail",
        "P4": "fail",
        "P5": "pass",
        "P6": "pass",
    }
    assert first["hidden"] == {"passed": 1, "total": 5}
    fixed = eng.ok(run(eng, ticket, reference(), "c2"))["code_run"]
    assert fixed["all_passed"] and fixed["counts"] == {"passed": 6, "total": 6}
    assert fixed["code"] == reference()
    again = eng.ok(run(eng, ticket, reference(), "c2"))["code_run"]
    assert again["id"] == fixed["id"]
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert [row["id"] for row in detail["code_runs"]] == [first["id"], fixed["id"]]
    assert all("code" not in row for row in detail["code_runs"])
    latest = eng.ok(eng.read(ticket_path(ticket, "code")))["latest_code_run"]
    assert latest["id"] == fixed["id"] and latest["code"] == reference()


def test_code_run_rides_along_the_signed_review(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    done = eng.ok(run(eng, ticket, reference(), "c"))["code_run"]
    made = eng.ok(draft(eng, ticket, "d", code_run_id=done["id"]))["draft"]
    assert made["code"]["id"] == done["id"] and made["code"]["all_passed"]
    signed = eng.ok(sign(eng, ticket, made["id"], "s"))
    assert signed["review"]["code"]["code_sha256"] == done["code_sha256"]
    read = eng.ok(eng.read("/engineer/reviews/" + signed["review"]["review_id"]))["review"]
    assert read["code"] == signed["review"]["code"]
    missing = draft(eng, ticket, "d2", code_run_id="coderun-" + "0" * 64)
    assert missing.status_code == 404


def test_sandbox_refuses_network_files_and_endless_loops(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    cases = {
        "net": "import socket\ndef current_limit(q, c, r):\n"
        "    socket.create_connection(('example.com', 80))\n",
        "read": "import os\ndef current_limit(q, c, r):\n"
        "    return {'status': open(os.path.join(os.path.dirname(os.getcwd()), 'x')).read()}\n",
        "write": "def current_limit(q, c, r):\n    open('x.txt', 'w').write('1')\n",
        "sub": "import subprocess\ndef current_limit(q, c, r):\n    subprocess.run(['whoami'])\n",
    }
    for key, code in cases.items():
        result = eng.ok(run(eng, ticket, code, key))["code_run"]
        assert all(row["result"] == "error" for row in result["public"]), key
        assert "blocked in the exercise sandbox" in result["public"][0]["error"], key
    secret = (
        "import os\ndef current_limit(q, c, r):\n    return {'status': str(dict(os.environ))}\n"
    )
    leaked = eng.ok(run(eng, ticket, secret, "env"))["code_run"]
    assert "CAREER_LAB" not in json.dumps(leaked)
    looping = "def current_limit(q, c, r):\n    while True:\n        pass\n"
    stuck = eng.ok(run(eng, ticket, looping, "loop"))["code_run"]
    assert stuck["status"] == "engineer_code_timeout"
    text = "\n".join(eng.responses)
    for query in hidden_queries(eng):
        assert query not in text
