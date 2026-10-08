"""Two simultaneous fixed-language sessions through the standard HTTP/worker assembly."""

import subprocess, sys, re
from pathlib import Path
from fastapi.testclient import TestClient
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.jobs.worker import Worker


def test_bilingual_sessions_keep_their_own_content_and_feedback(tmp_path, monkeypatch):
    built = subprocess.run(
        [
            sys.executable,
            "docs/integration/prepare_scenarios.py",
            "--output",
            str(tmp_path / "prepared"),
        ],
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(tmp_path / "prepared/catalog.json"))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    app = create_runtime_app("sqlite:///" + str(tmp_path / "bilingual.db"))
    c = TestClient(app)
    worker = Worker(app.state.jobs, app.state.handlers)
    hashes = {}
    try:
        for lang in ["zh", "en"]:
            r = c.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": lang},
            )
            assert r.status_code == 200, r.text
            value = r.json()
            sid = value["session_id"]
            h = {"Authorization": "Bearer " + value["token"]}
            hashes[lang] = value["binding"]["scenarioHash"]

            def send(path, key, operation, payload):
                state = c.get("/sessions/" + sid, headers=h).json()["state"]
                response = c.post(
                    "/sessions/" + sid + "/" + path,
                    headers=h,
                    json={
                        "schema_version": 2,
                        "request_id": key,
                        "expected_version": state["business_seq"],
                        "expected_workspace_revision": state["workspace_revision"],
                        "operation": operation,
                        "payload": payload,
                    },
                )
                assert response.status_code == 200, response.text
                return response.json()

            context = c.get("/sessions/" + sid + "/workbench", headers=h).json()["result"]["result"]
            assert context["session"]["workLanguage"] == lang and not context["read_only"]
            material = c.get("/sessions/" + sid + "/objects/material/brief/1", headers=h)
            assert material.status_code == 200, material.text
            text = " ".join(f["text"] for f in material.json()["content"]["fragments"])
            assert bool(re.search("[\u4e00-\u9fff]", text)) == (lang == "zh")
            send(
                "turns",
                "question",
                "turns.create",
                {
                    "role_id": "tech_lead",
                    "text": "How stale is the index?" if lang == "en" else "索引最多滞后多久？",
                    "shares": [],
                },
            )
            assert worker.run_once()
            rows = c.get("/sessions/" + sid + "/timeline", headers=h).json()["result"]["result"][
                "objects"
            ]
            replies = [row["content"]["text"] for row in rows if row["ref"]["kind"] == "role_reply"]
            assert replies, (
                lang,
                c.get("/sessions/" + sid + "/requests/question", headers=h).json(),
            )
            reply = replies[0]
            assert bool(re.search("[\u4e00-\u9fff]", reply)) == (lang == "zh")
            send(
                "turns",
                "followup",
                "turns.create",
                {
                    "role_id": "tech_lead",
                    "text": "Which version did you use?"
                    if lang == "en"
                    else "刚才使用的是哪个版本？",
                    "shares": [],
                },
            )
            assert worker.run_once()
            status = c.get("/sessions/" + sid + "/requests/followup", headers=h).json()
            assert status["status"] == "completed", (lang, status["status"])
            made = send(
                "work-products",
                "work",
                "work_products.create",
                {
                    "kind": "text",
                    "title": "Pilot options" if lang == "en" else "试点备选",
                    "content": "Defer until the ownership and scope are verified."
                    if lang == "en"
                    else "在负责人及范围核实前暂缓。",
                },
            )
            product = next(ref for ref in made["objects"] if ref["kind"] == "product")
            submitted = send(
                "submissions",
                "submit",
                "submissions.create",
                {"decision": "defer_with_conditions", "products": [product]},
            )
            assert worker.run_once()
            feedback = c.get(
                "/sessions/" + sid + "/feedback/" + submitted["result"]["submission"]["object_id"],
                headers=h,
            )
            assert feedback.status_code == 200, feedback.text
            report = feedback.json()["result"]["result"]["items"][0]
            assert len(report["items"]) == 14
            if lang == "en":
                assert not re.search(
                    "[\u4e00-\u9fff]",
                    report["business_response"]
                    + " ".join(item["explanation"] for item in report["items"]),
                )
        assert hashes["zh"] != hashes["en"]
    finally:
        app.state.store.close()
