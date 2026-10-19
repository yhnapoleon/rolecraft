# 演示会话包

`demo-pack-v1.json.gz` 里是几局**已经完整走完**的练习，把它导入任何一套部署，用继续码打开，就能把识别层在每一页的表现完整演示一遍。导入只往数据库里写记录，**不调用任何模型**，所以现场不用等 DeepSeek，也不需要 API key。

| 会话 | 情境 | 语言 |
|---|---|---|
| 见 `python -m scripts.recognition.demo_pack show --pack demo/demo-pack-v1.json.gz` | pm_pilot（内部知识助手）、it_ticket_pilot（IT 工单助手） | 中 / 英 |

## 导入（每台机器一次）

前提：拉了包含 `scenarios/pm_pilot/v2/candidates/rubric-final-v1-2.9.6/` 和 `scenarios/it_ticket_pilot/` 的代码，`uv sync` 过。

```powershell
# 在仓库根目录。三个变量要和启动服务时用的一致（密钥随便取，至少 32 字节）
$env:CAREER_LAB_SCENARIO_CATALOG = "demo/catalog.json"
$env:CAREER_LAB_CREDENTIAL_KEY_ID = "local-dev-v1"
$env:CAREER_LAB_CREDENTIAL_KEY = "local-development-key-at-least-32-bytes-long-0000"

# 1. 导入，打印每局的继续码（同一局再导入一次要加 --replace）
uv run python -m scripts.recognition.demo_pack import --db runs/demo/rolecraft.db --pack demo/demo-pack-v1.json.gz --catalog demo/catalog.json

# 2. 起服务（只看演示不需要 worker）
uv run career-lab serve --host 127.0.0.1 --port 18562 --database-url sqlite:///runs/demo/rolecraft.db

# 3. 起前端
cd apps/web; $env:ROLECRAFT_API_TARGET = "http://127.0.0.1:18562"; npm run build; npm run preview -- --port 18560
```

浏览器打开 `http://127.0.0.1:18560/`，首页点「有继续码？」，输入第 1 步打印的码。继续码只在导入它的那套部署上有效；换机器就在那台机器上再导入一次。

## 演示路线（每一页看哪个署名）

1. **测试记录**：三次助手测试。「账号密码怎么重置」在域内，检索 top-1 命中 FAQ；「火星天气」被范围检测（C4，马氏距离）判为域外、转人工；政策问题在索引刷新前后各测一次，漂移标注会显示「数值变化 500 → 400」（IT 场景是 4 → 2 小时）。
2. **同事回复**：每个气泡下有意图识别（C11）和依据核查（C10，几句有依据、有没有泄露）。C10 用的是本机 CPU 训练的 C1，会有误判（录制的这局里技术负责人说对的「可审批上限 60 人」也被标成矛盾）——讲的时候当作「识别器给出的是可核查的信号，不是裁决」。
3. **交付前预演**：用包里标着「交付前」的那几局（作品已写好、没有交付）。工作板点「交付」→ 勾作品版本 → 选「缩小范围推进」，预演卡上半部分是规则核实（4/4 项满足：人数、资源与期限、复测用新政策、调整后复测通过），下半部分是作品逐句标色——有依据 / 与材料矛盾 / 证据不足 / 送人工，附命中的材料原句。第一次算要二十秒左右（CPU 上跑 C1），同一选择再算约 8 秒。**不要点「提交选中的版本」**，否则这一局就交付了。
4. **反馈页**：语义评分项的解释以 `[识别一致]` / `[与识别不一致：…]` / `[识别缺失]` 开头；R2.support 有仲裁记录：评审给出 MET / PARTIAL / NOT_MET 且与识别器不一致时，在规则界内取更保守的一个；评审给的是 INSUFFICIENT 或待核验时，记为「评审未给出可比标签」（`judge_undecided`），保留评审标签。部分项显示「引用已定位，支持关系仍待核验」——那是核验没通过、按设计留给人看，不是故障。
5. **修订一轮**：第一版里「人工兜底已经落实：每天 45 分钟值班」是故意写的过度表述（材料里那 45 分钟只是查看记录），修订版改成「尚未落实」。两版的反馈与逐句识别可以对照看；这一句识别器两版都判「证据不足」，没有抓到——这是 C1 现在的边界。
6. **复盘页**：会话级识别汇总一行（范围检测几次、关系判定几句、意图几次……），以及「你的行为模式」（C5：最接近的策略、HMM 阶段、异常）。
7. **识别实验室** `#/lab`：选作品里任一句，看检索 → 关系概率 → 代价决策 → Judge 输入里的识别摘要 → 仲裁的全链；下面是 E1、E3–E10 的离线实验图。

## 局限

- 识别器权重（`runs/local/recognizers/`，含 e5 与 XLM-R）不在仓库里。没有权重的机器上，**已经存下的**识别记录照常显示；但「你的行为模式」和交付前预演是打开时现算的，会退回规则版（署名显示灰色「规则回退」）。要完整效果就在有权重的机器上演示，或把 `runs/local/recognizers/` 拷过去并设 `CAREER_LAB_RECOGNIZERS`。
- 导入的会话可以继续操作，但继续操作会调用模型（需要 worker 和 DeepSeek key）。演示只读即可。

## 重新录制

```powershell
# 开发服务按 docs/plans/progress-pattern-recognition-20261016.md 第 6 节起好（识别层开、DeepSeek）
uv run python -m scripts.recognition.demo_play --scenario pm_pilot --language zh --revise
uv run python -m scripts.recognition.demo_play --scenario it_ticket_pilot --language zh
# ……每局打印 session id；再导出
uv run python -m scripts.recognition.demo_pack export --db runs/local/dev/rolecraft.db `
  --session <sid1> --label "pm_pilot 中文：完整一局（含修订）" --session <sid2> --label "..." `
  --out demo/demo-pack-v1.json.gz
```
