# RoleCraft

**Recognising evidence grounding and work behaviour in simulated workplace practice.**
ISY5002 Pattern Recognition Systems · Practice Module · Group 47 · [中文版](README.zh-CN.md)

Learners practise as an AI product manager on a pilot decision: they read versioned materials, question three colleagues, test a retrieval-augmented knowledge assistant, configure the pilot and submit a written plan. RoleCraft senses two streams from that work, the **text** learners write and read and the **sequence of actions** they take, and recognises:

- whether each claim in the plan is **supported, contradicted, or left without evidence** by the materials (the primary task);
- which **evidence units** a claim or question refers to;
- whether a question to the assistant is **inside the knowledge scope**, and whether an answer **drifted** after re-indexing;
- the **intent** of each question put to a colleague;
- the learner's **strategy, phase and anomalous steps** from the action sequence;
- whether each sentence of a colleague's reply is **grounded** in what that colleague can see.

Three generators act on these results: the rubric Judge reads the per-sentence relation summary before labelling, the role-played colleagues receive ranked sources and the learner's recognised intent and phase, and the knowledge assistant answers only from retrieved, in-scope units. Wherever a recogniser's output is used, the page shows the recogniser's name and score: assistant test cards, colleague replies, the pre-submission rehearsal, feedback items, the session summary, the behaviour section and the recognition lab.

![RoleCraft architecture](docs/figures/architecture.png)

## Recognisers

| Recogniser | Input | Method | Output | Used by |
|---|---|---|---|---|
| **Claim–evidence relation** (primary) | plan sentence × top-k evidence units | XLM-RoBERTa cross-encoder (fine-tuned, temperature-scaled) stacked with a TF-IDF + feature logistic regression; late fusion with a number-and-limit rule | supported / contradicted / insufficient, probabilities, evidence ids | Judge input, pre-submission rehearsal, reply check, arbiter |
| **Evidence retrieval** | claim or question × materials | sentence / list-item units; BM25, multilingual-e5-small, Reciprocal Rank Fusion | ranked units with scores | relation, assistant, colleague source ranking |
| **Scope & drift detection** | assistant query; answers across index versions | e5 embedding, Mahalanobis distance with Ledoit-Wolf covariance per scenario, language and scope setting; cosine drift against a 2σ band | in / out of scope; drift anomaly | assistant gate, test card, Judge input |
| **Question intent** | learner question to a colleague | character 2–4 gram TF-IDF + logistic regression | 5 intents | colleague prompt, behaviour symbols |
| **Behaviour recognition** | workbench events → 26-symbol sequence | DTW 1-NN against 40 reference trajectories; 5-state categorical HMM (BIC, Viterbi); anomaly rules | nearest strategy, phase timeline, anomalies, alignment | review page, colleague prompt, Judge input |
| **Reply grounding check** | each sentence of a colleague reply | retrieval + relation against the colleague's visible sources and private facts | grounded / ungrounded / leak per sentence | reply bubble |
| **Decision layer** | relation probabilities; Judge label | Bayes minimum-expected-cost decision with a reject option (explicit cost matrix); conservative arbiter | decide or defer to a human; arbitrated label | feedback page, review queue |

Code: [`src/career_lab/recognition/`](src/career_lab/recognition/). Each output is stored as a `RecognitionRecord` (recogniser id and weight revision, label, score, threshold, citations) on the object it shaped, and `GET /sessions/{id}/recognition` returns them per session.

## How the recognisers drive the generators

- **Judge (rubric feedback).** Before the Judge labels any of the 14 rubric items, the recognition layer splits materials into at most 80 evidence units, judges every sentence of the plan against its top-5 units, decides or defers each sentence by expected cost, and adds recent scope results and the behaviour summary. This summary goes into every evidence package; the Judge's instructions tell it to read the recognisers first and start each explanation with `[recognition agrees]`, `[recognition missing]` or `[disagrees with recognition: reason]`. On the evidence-support item the arbiter keeps the more cautious of the Judge's and the recognisers' labels, within the rule bounds.
- **Colleagues.** Sources are ranked by retrieval relevance to the question, and the prompt carries a `learner_state` with the recognised intent and current phase. After the reply, the grounding check marks each sentence.
- **Knowledge assistant.** Scope detection gates every query: an out-of-scope query is handed to a human before any answer is composed. Dense retrieval selects the units; the answer is extractive or, if the learner configures it, LLM-generated from those units only.

## Results

Held-out test sets, Chinese / English, except the last row (28 paired live sessions). Full results in [`experiments/recognition/results/`](experiments/recognition/results/) and on the recognition lab page (`#/lab`).

| Task | Metric | Result |
|---|---|---|
| Claim–evidence relation | claim-level macro-F1 | deployed chain (stacked ensemble + number-and-limit rule) **0.698 / 0.635**; stacked ensemble alone 0.713 / 0.633; XLM-R alone 0.656 / 0.608; best classical model (TF-IDF + features LR) 0.646 / 0.572 |
| Decision layer | wrong-deduction rate | 4.2% → 0.7% when 20% of claims are deferred to a human (deployed chain) |
| Scope detection | AUROC | Mahalanobis 0.977 / 0.953 (K-Means 0.907 / 0.832, one-class SVM 0.815 / 0.823, Isolation Forest 0.756 / 0.701) |
| Scope, new domain | AUROC | refitted on the IT knowledge base 0.986 / 0.949 |
| Retrieval, paraphrased questions | Recall@5 | e5 0.82 / 0.79, RRF 0.65 / 0.57, BM25 0.49 / 0.36 |
| Question intent | accuracy | 0.946 / 0.824 (keyword rule 0.550 / 0.496) |
| Behaviour, 50% perturbed steps | strategy accuracy | DTW 1-NN 0.71, n-gram random forest 0.55 |
| Behaviour anomaly | AUROC | HMM log-likelihood 0.90, DTW distance 0.88 |
| Judge with / without recognition summary | items labelled | 42.6% / 38.9%; citations per item 1.12 / 1.05 |

### Evaluation on public data

The recognisers were re-evaluated on public datasets with human labels, and the relation task was trained with an upgraded pair classifier: a multilingual NLI cross-encoder (mDeBERTa-v3, pre-trained on XNLI and multilingual NLI) fine-tuned on `relation-v3` plus the ContractNLI, VitaminC and CFEVER train splits. This classifier is evaluated offline; the deployed chain is the first row of the table above. Method, data and full tables: [`docs/data/public-sources-v1.md`](docs/data/public-sources-v1.md), sections 8–10.

| Task | Test data | Metric | Result |
|---|---|---|---|
| Claim–evidence relation, NLI cross-encoder | `relation-v3` (zh / en) | claim-level macro-F1 | **0.903** (0.894 / 0.908) |
| Claim–evidence relation, NLI cross-encoder | ContractNLI / VitaminC / CFEVER (human-written claims) | claim-level macro-F1 | 0.806 / 0.792 / 0.641 |
| Reply grounding check, NLI cross-encoder reading the three retrieved units as one passage | colleague-style replies on real material (zh / en) | sentence three-class macro-F1; leak F1 | 0.928; 0.94 |
| Scope detection, deployed method refitted per dataset | MASSIVE zh / en | AUROC | 0.961 / 0.940 |
| Evidence retrieval, e5 dense | PrivacyQA (crowdworker questions, expert relevance) | Recall@5 / MRR | 0.770 / 0.562 |

## Data

All sets live in `data/releases/<name>/` with a `manifest.json`, `data_card.md` and `SHA256SUMS`. The project's own sets are bilingual (zh / en):

| Set | Content | Size |
|---|---|---|
| `relation-v3` | learner-voice claims, each with one gold unit and three hard negatives; nine phenomena (direct, negation, paraphrase, unfounded inference, numeric comparison, number format, slot mismatch, request-as-approval, old version) | 4,325 claims, 17,281 pairs |
| `intent-v1` | five intents × four styles | 1,236 questions |
| `assistant-queries-v1` | in-domain direct / paraphrased, near / far out-of-domain | 538 queries |
| `paraphrases-v1` | in-domain paraphrases for fitting scope detection | 124 |
| `trajectories-v1` | eight scripted strategies run against the live backend | 400 sequences |
| `it-ticket-v1` | second domain (IT ticket assistant) for cross-domain tests | 1,199 claims, 624 queries |

Claims and questions were generated with DeepSeek and kept only when a label-blind second pass agreed (relation 93.7%, intent 91.0%) or, for assistant queries, when the source unit was retrievable. Relation claims are split by language and source material, so paraphrases of one fact never cross partitions.

Public data, converted to the same record formats (real text with the datasets' own human labels, and synthetic sets whose evidence is real public material):

| Set | Source | For | Size |
|---|---|---|---|
| `public-real-v1` | ContractNLI, VitaminC, CFEVER | claim–evidence relation | 50,515 claims |
| `public-materials-v1` | GitHub site-policy, Kubernetes KEPs, Public Jira Dataset, TheAgentCompany, tau-bench | evidence units, checklists, trajectories | 13,319 units |
| `public-synth-v1` | claims written against real evidence units | claim–evidence relation | 3,839 claims |
| `public-reply-v1` | RAGTruth | reply grounding check | 17,790 responses, 131,160 sentences |
| `public-reply-synth-v1` | colleague replies on real material, with leaks | reply grounding check | 603 replies |
| `public-scope-v1` | CLINC150, MASSIVE 1.1 (zh, en) | scope detection | 23,700 + 33,042 queries |
| `public-retrieval-v1` | PrivacyQA | evidence retrieval | 1,750 questions, 35 policies |
| `public-queries-synth-v1` | knowledge-base questions on real material | retrieval, scope | 2,658 queries |
| `public-sequence-v1` | tau-bench runs, Jira change logs | behaviour recognition | 1,980 + 400 sequences |
| `public-intent-synth-v1` | learner questions on real material | question intent | 1,354 |

Sources, pinned versions and licences: [`docs/data/public-sources-v1.md`](docs/data/public-sources-v1.md). What each dataset and weight directory is, and where it lives: [`docs/data/DATA_INVENTORY.md`](docs/data/DATA_INVENTORY.md).

## Scenarios

`pm_pilot` (internal knowledge-assistant pilot, with `urgent` and `capacity15` variants) and `it_ticket_pilot` (IT ticket assistant), each in Chinese and English. The learner meets a 24-hour index delay, a 30-user capacity limit, three developer-days of effort and a policy update mid-task; limiting the pilot to stable knowledge and asking for more resources can both be valid if the facts support them.

## Running

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node.js 22.12+.

```sh
uv sync --locked --extra encoder --python 3.12   # CPU torch and transformers for the recognisers
cd apps/web && npm ci && cd ../..
```

### Recorded sessions (no model calls)

[`demo/`](demo/) holds eight completed sessions (two scenarios × two languages × full run / before submission). Importing them writes database rows only.

```powershell
$env:CAREER_LAB_SCENARIO_CATALOG = "demo/catalog.json"
$env:CAREER_LAB_CREDENTIAL_KEY_ID = "local-dev-v1"
$env:CAREER_LAB_CREDENTIAL_KEY = "<any secret of at least 32 bytes>"
New-Item -ItemType Directory -Force runs/demo | Out-Null
uv run python -m scripts.recognition.demo_pack import --db runs/demo/rolecraft.db --pack demo/demo-pack-v1.json.gz --catalog demo/catalog.json
uv run career-lab serve --host 127.0.0.1 --port 18562 --database-url sqlite:///runs/demo/rolecraft.db
# second terminal
cd apps/web; $env:ROLECRAFT_API_TARGET = "http://127.0.0.1:18562"; npm run build; npm run preview -- --port 18560
```

Open `http://127.0.0.1:18560/`, choose **Have a continue code?** and enter a code printed by the import.

What to look at, page by page:

1. **Test runs.** An in-scope question retrieves its FAQ unit; "What is the weather on Mars?" is out of scope by Mahalanobis distance and handed to a human; a policy question asked before and after re-indexing is flagged as drift ("numbers changed 500 → 400").
2. **Colleague replies.** Under each reply: the recognised intent of the question and how many sentences are grounded.
3. **Pre-submission rehearsal** (sessions labelled "before submission"). On the board choose **Submit**, tick the work versions and pick **Proceed with a limited scope**: rule checks on top, and below them every sentence of the plan coloured as supported, contradicted, insufficient or sent to a person, with the matched source sentence. Do not press **Submit selected versions**.
4. **Feedback.** Semantic items start with `[recognition agrees]`, `[disagrees with recognition: …]` or `[recognition missing]`; the evidence-support item carries an arbitration record.
5. **Revision.** The full-run sessions include a second submission; compare feedback and sentence labels across the two versions.
6. **Review.** The session summary counts each recogniser's records; **Your behaviour pattern** shows the nearest strategy, the HMM phase timeline, anomalies and the alignment with the nearest reference.
7. **Recognition lab** (`#/lab`). Pick any sentence of the plan to follow retrieval → relation probabilities → cost decision → the summary given to the Judge → arbitration, above the offline experiment charts.

The Chinese notes in [`demo/README.md`](demo/README.md) cover re-recording the sessions.

### Full system

Additionally needs the recogniser weights (`runs/local/recognizers/`: XLM-R relation model, e5, scope fits, intent model, behaviour references, stacked ensemble) and a DeepSeek key in `ds.txt`.

```powershell
$env:CAREER_LAB_RECOGNIZERS = "runs/local/recognizers"
$env:CAREER_LAB_RELATION_ENCODER = "runs/local/recognizers/c1-xlmr-cpu"
foreach ($s in 'JUDGE','ROLES','ASSISTANT') {
  Set-Item "Env:CAREER_LAB_${s}_PROVIDER" 'deepseek'
  Set-Item "Env:CAREER_LAB_${s}_KEY_FILE" "$PWD\ds.txt"
}
uv run career-lab serve --host 127.0.0.1 --port 18562 --database-url sqlite:///runs/local/rolecraft.db
uv run career-lab worker --database-url sqlite:///runs/local/rolecraft.db   # run 2–3 of these
```

Keep the scenario-catalog and credential variables from the previous block, and start the frontend the same way.

### Reproducing data, models and experiments

```sh
uv run python -m scripts.recognition.synth relation --out data/releases/relation-v3      # also: intent, queries, paraphrases
uv run python -m scripts.recognition.synth_domain --out data/releases/it-ticket-v1
uv run python -m scripts.recognition.run_strategies --strategy all --count 25 --language zh \
  --out data/releases/trajectories-v1/raw-zh.jsonl                                  # needs a running server
uv run python -m experiments.recognition.relation.train_c1 --data data/releases/relation-v3/relation.jsonl \
  --out runs/local/recognizers/c1-xlmr-cpu --freeze-layers 10 --epochs 2 --max-len 160
uv run python -m experiments.recognition.relation.fit_stack --encoder runs/local/recognizers/c1-xlmr-cpu
uv run python -m experiments.recognition.baselines --encoder runs/local/recognizers/c1-xlmr-cpu   # E1
uv run python -m experiments.recognition.retrieval      # E3; likewise relation_eval (E4), scope (E5),
                                                        # behavior (E6), intent (E7), judge_ab (E8),
                                                        # cross_domain (E9), fusion (E10)
uv run python -m experiments.recognition.publish_lab --c1 runs/local/recognizers/c1-xlmr-cpu
```

Generation parameters actually used are recorded in each release's `manifest.json`. The behaviour experiment additionally needs `hmmlearn==0.3.3`.

Public data and the experiments on it (E11–E15); the download, conversion and synthesis commands and the environments each script needs are in [`docs/data/public-sources-v1.md`](docs/data/public-sources-v1.md), sections 4 and 7.3:

```sh
python -m experiments.recognition.relation.transfer_public --encoder runs/local/recognizers/c1-xlmr-cpu  # E11
python -m experiments.recognition.relation.mix_public --encoder runs/local/recognizers/c1-xlmr-cpu      # E12
python -m experiments.recognition.public_eval all                                                     # E13
python -m experiments.recognition.relation.diagnose_public --encoder runs/local/recognizers/c1-xlmr-cpu # E14
python -m experiments.recognition.relation.nli_relation train \
  --base runs/local/weights/mdeberta-v3-base-xnli-2mil7 --out runs/local/recognizers/c1-mdeberta-mix   # E15
python -m experiments.recognition.relation.nli_relation predict \
  --model runs/local/recognizers/c1-mdeberta-mix --tag mix --time
python -m experiments.recognition.relation.nli_relation reply \
  --model runs/local/recognizers/c1-mdeberta-mix --tag mix --time
```

## Repository layout

```text
src/career_lab/
  recognition/     recognisers, registry, recognition records (this project's core)
  evidence/        evidence packages for the Judge
  rubrics/         rubric rules, Judge, score ranges
  runtime/         colleague roles, model slots, context building
  assistant/       knowledge assistant (retrieval, gates, generation)
  scenarios/       scenario engine and packages
  api/ jobs/ storage/ mcp/ delegations/   service, worker queue, event store, agent access
apps/web/          learner workbench and recognition lab (Vite + TypeScript)
experiments/recognition/   E1, E3–E15 scripts and results
scripts/recognition/       data generation, strategy runner, demo recording and import
scripts/public/            public-data download, conversion and grounded synthesis
scenarios/         installed scenario packages (pm_pilot, it_ticket_pilot)
demo/              recorded sessions and catalog
docs/              design, plans, figures
```

## Team

FENG Tangyu · LIU Kairui · YING Hao · ZHANG Junming
