"""Module CLI checks. Shared CLI and real restore service are not installed."""
import json
from career_lab.branching.cli import main
from test_w10_branching import snapshot, seal


def test_prefix_compare_machine_result_and_nonzero_failure(tmp_path,capsys):
    s,_=snapshot();a=tmp_path/"a.json";b=tmp_path/"b.json";a.write_text(s.model_dump_json());b.write_text(s.model_dump_json())
    args=["branch","compare","--expected-prefix",str(a),"--actual-prefix",str(b)]
    assert main(args)==0 and json.loads(capsys.readouterr().out)["equal"]
    changed=seal(s.model_copy(update={"state":s.state.model_copy(update={"resources":{"capacity":99}})}))
    b.write_text(changed.model_dump_json())
    assert main(args)==2 and not json.loads(capsys.readouterr().out)["equal"]


def test_create_without_factory_fails_instead_of_mock_success(tmp_path,capsys):
    request=tmp_path/"request.json";request.write_text("{}")
    assert main(["branch","create","--request",str(request)])==2
    assert json.loads(capsys.readouterr().out)["code"]=="w10_factory_not_installed"
