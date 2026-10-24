# 工程师回归报告样例

这里的四个 JSON 是可信复核器真跑出来的公开回归报告（`EngineerPublicReport`，契约 `engineer-review-v1`），供前端样例页 `#/engineer-report` 和回归报告组件 `src/features/engineer-report/` 使用。每种情形中英各一份，业务事实相同。

| 文件 | 情形 | `status` / `claim_check` | 公开 4 条 | 隐藏 9 条 |
|---|---|---|---|---|
| `target-fixed-no-new-failures.{zh,en}.json` | 目标修好，无新增失败，自报一致 | `verified` / `matched` | F12（目标）修好；F01 改前也未通过；F04、F05 通过 | 通过 5 · 未通过 4 · 出错 0 |
| `target-not-fixed-new-failures.{zh,en}.json` | 目标没修好，有新增失败，自报不符 | `report_mismatch` / `mismatch` | F01（目标）仍未通过；F04、F05 新增失败；F12 通过 | 通过 4 · 未通过 5 · 出错 0 |

私有复核库里的隐藏探针对比（公开报告目前没有这个字段，`hidden_comparison` 上线后可拿来核对）：修好那份是新增失败 0 · 修好 1 · 仍未通过 4 · 未核实 0；没修好那份是新增失败 2 · 修好 1 · 仍未通过 3 · 未核实 0。

## 生成条件

- 2026-10-24，代码基点 `4b069b2`，`--provider local`，新 SQLite 库；没有设 `CAREER_LAB_RECOGNIZERS`（识别层关闭），复核器是规则版检索（`reviewer.json` 的 `mode` 为 `local-extractive`），不调用任何模型，`advice` 为 `waiting_model`。
- 中文用默认安装场景；英文另起一套服务，`CAREER_LAB_SCENARIO_V2` 指向英文场景。
- 公开报告由复核器自己投影：只有公开探针逐条、隐藏探针计数和规则文案。逐份核过：不含令牌、文件路径、提交说明或其他自由文字。报告里的 `session_id`（引用）与 `reviewer.id` 来自这次本机一次性库，单独拿到没有任何权限；令牌只在 `runs/` 下权限 0600 的 `credentials.json` 里。

## 怎样重跑

在 worktree 根目录。`runs/` 被 Git 忽略。下面以中文为例；英文把注释里标「英文」的几处换掉即可。

```sh
unset PYTHONPATH CAREER_LAB_SCENARIO_CATALOG
R=runs/local/engineer-samples/zh && mkdir -p "$R"
SCEN=scenarios/pm_pilot/v2/candidates/rubric-final-v1-2.9.6/pm_pilot
# 英文：SCEN="$SCEN/locales/en"，另设 export CAREER_LAB_SCENARIO_V2="$PWD/$SCEN"
export CAREER_LAB_SCENARIO_ARCHIVE="$PWD/$R/archive"
uv run --locked career-lab serve --host 127.0.0.1 --port 18592 \
  --database-url "sqlite:///$R/rolecraft.db" --provider local &   # 测试同步执行，不需要 worker
API=http://127.0.0.1:18592
until curl -sf $API/docs > /dev/null; do sleep 1; done

# 新开一局并写私有凭据（0600）；之后每条命令带上当前版本号
session() { mkdir -p "$1"; curl -s -X POST $API/sessions -H 'content-type: application/json' \
  -d '{"schema_version":2,"scenario":"pm_pilot_v2","work_language":"zh"}' > "$1/session.json"   # 英文："en"
  (umask 077; jq --arg api $API '{api_url:$api, session_id:.session_id, token:.token}' "$1/session.json" > "$1/credentials.json"); }
send() { D=$1; SID=$(jq -r .session_id "$D/credentials.json"); TOK=$(jq -r .token "$D/credentials.json")
  ST=$(curl -s "$API/sessions/$SID" -H "Authorization: Bearer $TOK")
  jq -n --arg k "$3" --arg op "$4" --argjson p "$5" --argjson s "$(echo "$ST" | jq .state.business_seq)" \
    --argjson w "$(echo "$ST" | jq .state.workspace_revision)" \
    '{schema_version:2, request_id:$k, operation:$op, payload:$p, expected_version:$s, expected_workspace_revision:$w}' |
  curl -s -X POST "$API/sessions/$SID/$2" -H "Authorization: Bearer $TOK" -H 'content-type: application/json' -d @-; }
base() { jq -n --arg sid "$(jq -r .session_id "$1/credentials.json")" --argjson v $2 --argjson cv $3 --argjson s "$4" \
  '{base:{schema_version:2, session_id:$sid, kind:"config", object_id:"pilot", version:$v, config_version:$cv}, settings:$s}'; }
```

**情形一：目标修好、无新增失败。** 产品经理把知识范围收窄到政策类（漏掉稳定办公知识），「账号密码忘了怎么重置？」被判为超出范围；工程师把范围改回来。

```sh
A=$R/fixed; session $A
send $A configuration a1 configuration.apply "$(base $A 1 0 '{"min_score":0.05}')"
send $A tests t1 tests.create '{"query":"火星天气如何？","config_version":1}'          # 英文：What is the weather on Mars?
send $A configuration a2 configuration.apply \
  "$(base $A 2 1 '{"min_score":0.35,"domains":["policy_travel","policy_meal","policy_leave","onboarding"]}')"
send $A tests t2 tests.create '{"query":"账号密码忘了怎么重置？","config_version":2}' > $A/target.json  # 英文：I forgot my account password. How do I reset it?
CHANGES='{"domains":["stable_faq","onboarding","policy_travel","policy_meal","policy_leave"]}'
CLAIM='[{"probe_id":"F01","result":"fail"},{"probe_id":"F04","result":"pass"},{"probe_id":"F05","result":"pass"},{"probe_id":"F12","result":"pass"}]'
```

**情形二：目标没修好、有新增失败、自报不符。** 政策更新后索引落后，住宿上限问题照旧答 500 元、没有提醒；工程师把新鲜度保护设成「转人工」又关掉了人工兜底，并自报四条全过。

```sh
B=$R/not-fixed; session $B
i=0; for q in "住宿报销上限是多少？" "火星天气如何？" "个人薪资是多少？" "账号密码忘了怎么重置？"; do   # 英文：public-probes.json 里的四个英文问题
  i=$((i+1)); send $B tests "v0-$i" tests.create "$(jq -n --arg q "$q" '{query:$q, config_version:0}')" > /dev/null; done
send $B configuration b1 configuration.apply "$(base $B 1 0 '{"work_items":["scope_filter","human_fallback"],"fallback":"human"}')"
send $B tests t3 tests.create '{"query":"住宿报销上限是多少？","config_version":1}' > $B/target.json   # 英文：What is the hotel reimbursement limit per night?
CHANGES='{"freshness_guard":"fallback","fallback":"none"}'
CLAIM='[{"probe_id":"F01","result":"pass"},{"probe_id":"F04","result":"pass"},{"probe_id":"F05","result":"pass"},{"probe_id":"F12","result":"pass"}]'
```

**打包 → 准备候选配置 → 提交 → 复核**（对 `D=$A` 或 `D=$B` 各做一遍，`CHANGES`、`CLAIM` 用上面对应的值）：

```sh
ENG() { .venv/bin/python -m career_lab.engineer "$@" --database "$R/rolecraft.db" --credentials "$D/credentials.json" --scenario "$SCEN"; }
ENG pack --test "$(jq -r .result.test.id $D/target.json)" --output $D/pack
.venv/bin/python - "$D/pack" "$D/input" "$CHANGES" "$CLAIM" <<'PY'
import json, sys
from datetime import UTC, datetime
from pathlib import Path
from career_lab.contracts.v2.engineer import EngineerClaimedReport, EngineerSubmissionRecord
from career_lab.engineer.files import encode, file_ref
pack, source = Path(sys.argv[1]), Path(sys.argv[2]); source.mkdir(parents=True, exist_ok=True)
index = json.loads((pack / "index.json").read_bytes())
test = json.loads((pack / index["tests"][0]["path"]).read_bytes())
candidate = {**json.loads((pack / "config.json").read_bytes()), **json.loads(sys.argv[3])}
raw = encode(candidate); (source / "candidate.json").write_bytes(raw)
(source / "pack.json").write_bytes((pack / "pack.json").read_bytes())
now = datetime.now(UTC).replace(microsecond=0)
pack_ref, config_ref = file_ref("pack.json", (pack / "pack.json").read_bytes()), file_ref("candidate.json", raw)
claim = encode(EngineerClaimedReport(contract_version="engineer-review-v1", id="claim", pack=pack_ref,
    config=config_ref, created_at=now, results=tuple(json.loads(sys.argv[4]))))
(source / "claim.json").write_bytes(claim)
record = EngineerSubmissionRecord(contract_version="engineer-review-v1", id="repair", pack=pack_ref,
    config=config_ref, base_config_hash=file_ref("config.json", (pack / "config.json").read_bytes()).sha256,
    regression_report=file_ref("claim.json", claim), unresolved=(), explanation="sample submission",
    executor=test["execution"]["executor"], created_at=now, work_language=index["work_language"])
(source / "submission.json").write_bytes(encode(record))
PY
ENG submit --pack $D/pack --input $D/input/submission.json --output $D/submissions
ENG review --pack $D/pack --submission $D/submissions/submission-* --output $D/public --private-output $D/private
# 情形二的复核输出 status=report_mismatch、退出码 1，属预期
```

最后把 `$D/public/review-*/report.json` 拷成这里对应的文件名，并用契约校验一遍：

```sh
.venv/bin/python -c "import sys; from pathlib import Path; from career_lab.contracts.v2.engineer import EngineerPublicReport as R; [print(p, R.model_validate_json(Path(p).read_bytes()).status) for p in sys.argv[1:]]" apps/web/public/engineer/*.json
```
