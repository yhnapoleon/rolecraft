# Data and model inventory

What the RoleCraft submission package contains besides the code: every dataset, where it came
from, what kind of data it is, and the model weights. Paths are relative to the repository
root. None of the directories below is in git (they are listed in `.gitignore` or were never
added), so they have to be copied into the package by hand.

Full provenance of the public data (row counts, conversions, known limits, rebuild commands)
is in [`public-sources-v1.md`](public-sources-v1.md); each release directory also carries its
own `data_card.md`, `manifest.json` and `SHA256SUMS`.

## 1. What to pack

| Path | Size | Contents | Needed for |
|---|---|---|---|
| `data/releases/` | 310 MB | All released datasets (section 2) | Re-running the experiments; reading the data |
| `runs/local/recognizers/` | 2.7 GB | Recognizer weights and the registry manifest (section 4); 1.6 GB without the E15 experiment model `c1-mdeberta-mix/` | Running the product with recognition on; the experiments |
| `data/raw/` | 1.7 GB | Raw downloads of the public sources (section 3) | Rebuilding the public releases only; everything here can be downloaded again with `python -m scripts.public.fetch` |
| `runs/local/weights/xlm-roberta-base/` | 1.1 GB | The pretrained base model that C1 was fine-tuned from | Re-training C1 only (C1 itself is self-contained in `recognizers/c1-xlmr-cpu/`) |
| `runs/local/weights/mdeberta-v3-base-xnli-2mil7/` | 0.6 GB | The multilingual NLI model E15 starts from (zero-shot rows of E15) | Re-running E15 zero-shot or re-training `c1-mdeberta-mix` |
| `runs/local/c1-return/registry/encoder-bb7895c0…/` | 1.1 GB | C1 packaged in the encoder-return format the feedback page's sentence-level model suggestions load | That one feedback-page column; the other entry `encoder-65dbaea3…` is stale and can be left out |
| `data/annotation/v2-pilot/` | 0.4 MB | Two-annotator sheet for 100 controlled items (human annotation still pending) | Reference only |
| `data/external-samples/` | 0.6 MB | The 10-06 hand-written drafts, now in `_superseded/` and `_reference/` with a README each | Reference only |
| `demo/` | 2 MB | Eight pre-recorded demo sessions (in git already) | The demo |
| `experiments/recognition/results/` | small | All experiment results E1–E15 as JSON (in git already) | The report's numbers |

Do **not** pack: `ds.txt` and `openai.txt` at the repository root (API keys), `runs/local/data/`
and `runs/local/dev/` (local server databases and logs), `runs/local/cache/` (recomputable
C1 probabilities).

## 2. Datasets (`data/releases/`)

Label tiers used below:

- **G1**: the original human annotation of a published dataset, carried over unchanged.
- **G2v**: written by DeepSeek (`deepseek-chat`) from a generation plan, kept only when a
  second, label-blind DeepSeek pass gave the same label. Generator and reviewer are the same
  vendor; the report states this as a limitation.
- **Engine**: recorded from the RoleCraft engine itself (labels are the script that produced
  the run, or the engine's own state).
- **G0**: rule-generated controlled items whose labels follow from the template.

### 2.1 Built for this project on the RoleCraft scenarios

| Dataset | Recognizer | Type | Language | Size | Labels |
|---|---|---|---|---|---|
| `relation-v3` | C1 claim–evidence relation; stack (E1, E10, E11, E12) | Synthetic claims on the pm_pilot materials | zh, en | 4,325 claims, 17,281 claim–unit pairs | G2v |
| `assistant-queries-v1` | C4 scope (E5), C2 retrieval (E3) | Synthetic questions to the knowledge assistant | zh, en | 538 questions | G2v; in-domain ones also checked against C2 top-5 |
| `paraphrases-v1` | C4 (fit set only) | Synthetic paraphrased in-domain questions | zh, en | 124 | G2v |
| `intent-v1` | C11 intent (E7) | Synthetic learner-to-colleague utterances, 5 intents × 4 styles | zh, en | 1,236 | G2v |
| `trajectories-v1` | C5 behaviour (E6) | Engine-recorded sessions of 8 scripted strategies through the real HTTP API | zh, en | 400 sessions | Engine |
| `it-ticket-v1` | Cross-domain test (E9) | Synthetic second domain (IT service desk): materials, relation claims, questions | zh, en | 1,199 claims, 624 questions | G2v; materials limited to a fixed fact ledger |

### 2.2 Public real data, converted to the formats above

| Dataset | Recognizer | Source (section 3) | Language | Size | Labels |
|---|---|---|---|---|---|
| `public-real-v1` | C1 / stack transfer and mixed training (E11, E12) | ContractNLI, VitaminC, CFEVER | en, zh | 50,515 claims | G1 |
| `public-materials-v1` | Raw material for the grounded synthetic sets; KEP checklist; trajectories | GitHub site-policy, Kubernetes KEPs, Public Jira Dataset, TheAgentCompany, tau-bench | en | 13,319 evidence units, 5,948 checklist items, 2,380 trajectories | G1 where the source has labels (checklist ticks, final status, environment reward); otherwise unlabelled text |
| `public-reply-v1` | C10 reply check (E13) | RAGTruth | en | 17,790 replies, 131,160 sentences | G1 (word-level hallucination spans) |
| `public-scope-v1` | C4 scope (E13) | CLINC150, MASSIVE 1.1 | en, zh | 23,700 + 33,042 questions | G1 intents; the in / near / far partition of MASSIVE scenarios is ours |
| `public-retrieval-v1` | C2 retrieval (E13) | PrivacyQA | en | 1,750 questions over 35 policies | G1 (expert relevance) |
| `public-sequence-v1` | C5 behaviour (E13) | tau-bench, Public Jira Dataset | en | 1,980 + 400 sequences | G1 (environment reward, final resolution) |

### 2.3 Synthetic, grounded on the real material of 2.2

| Dataset | Recognizer | Language | Size | Labels |
|---|---|---|---|---|
| `public-synth-v1` | C1 / stack transfer (E11, E12) | zh, en | 3,839 claims; evidence units are real text (Chinese units are number-checked translations) | G2v |
| `public-reply-synth-v1` | C10, including leaks (E13) | zh, en | 603 replies, 2,724 sentences | G2v |
| `public-queries-synth-v1` | C2, C4 (E13) | zh, en | 2,658 questions over 155 real units | G2v |
| `public-intent-synth-v1` | C11 (E13) | zh, en | 1,354 utterances | G2v |

### 2.4 Earlier pipeline pilots (before 10-16)

| Dataset | What it is | Size | Labels |
|---|---|---|---|
| `v1` | First engineering pilot of the relation format | 90 items | G0 |
| `contractnli-pilot-v1` | ContractNLI import pilot (5 contracts) | 85 items | G1 |
| `controlled-v2`, `controlled-v2-pilot100` | Controlled Chinese relation items, 6 capability families × 24 templates | 1,152 / 100 items | G0 |

These are kept for the record; the experiments in the report use 2.1–2.3.

## 3. External sources (`data/raw/`)

| Source | Where from | Pinned version | Licence | Raw size | Used in |
|---|---|---|---|---|---|
| ContractNLI (Koreeda & Manning, 2021) | stanfordnlp.github.io/contract-nli | zip of 2026-10-02 (hash in `source.json`) | CC BY 4.0 | 63 MB | public-real, contractnli-pilot |
| VitaminC (Schuster et al., 2021) | huggingface.co/datasets/tals/vitaminc | `be6febb761b0` | CC BY-SA 3.0 | 244 MB | public-real |
| CFEVER (Lin et al., 2024) | huggingface.co/datasets/IKMLab-team/cfever | `1f8fa4bd2908` | Apache-2.0 | 968 MB | public-real |
| GitHub site-policy | github.com/github/site-policy | `b9578b546d25` | CC0-1.0 | 3 MB | materials, synth |
| Kubernetes enhancements (KEPs) | github.com/kubernetes/enhancements | `5b503a75369b` | Apache-2.0 | 92 MB | materials, synth |
| TheAgentCompany (Xu et al., 2024) | github.com/TheAgentCompany/TheAgentCompany | `98b68ef82a47` | MIT | 15 MB | materials, synth |
| Public Jira Dataset (Montgomery et al., 2022) | zenodo.org/records/15719919 (first 100 MB streamed) | 2025-06-23 release | CC BY 4.0 | 2 MB | materials, sequence, synth |
| tau-bench (Yao et al., 2024) | github.com/sierra-research/tau-bench | `59a200c6d575` | MIT | 66 MB | materials, sequence, synth |
| RAGTruth (Niu et al., 2024) | github.com/ParticleMedia/RAGTruth | `c103204b9ce2` | MIT | 43 MB | public-reply |
| CLINC150 (Larson et al., 2019) | github.com/clinc/oos-eval | `828f8093932c` | CC BY 3.0 | 17 MB | public-scope |
| MASSIVE 1.1 (FitzGerald et al., 2023) | amazon-massive-nlu-dataset S3 tar; HF card `ff6bd8e4b27c` | 1.1 | CC BY 4.0 | 39 MB (zh-CN and en-US only) | public-scope |
| PrivacyQA (Ravichander et al., 2019) | github.com/AbhilashaRavichander/PrivacyQA_EMNLP | `5178ff3eaf61` | MIT | 92 MB | public-retrieval |

Each source directory has a `source.json` (URL, pinned version, retrieval date, licence and
the SHA-256 of the licence file); the licence texts are copied into each release's `LICENSES/`.

The RoleCraft scenarios themselves (pm_pilot, it_ticket_pilot) and all synthetic text were
written for this project; synthetic text was generated with DeepSeek (`deepseek-chat`).

## 4. Models and weights (`runs/local/recognizers/`)

| Directory | Recognizer | What it is | Trained on | Size |
|---|---|---|---|---|
| `c1-xlmr-cpu/` | C1 relation | XLM-R base cross-encoder, bottom 10 layers frozen, 2 epochs, 160 tokens, temperature-scaled | relation-v3 train | 1.1 GB |
| `relation-stack-v1/` | Stack (product) | TF-IDF + hand-crafted features LR, stacked with C1 by an LR meta-learner; rule fusion α | relation-v3 train / dev | 1 MB |
| `relation-stack-mix-v1/` | Stack (E12 experiment, not registered, not used by the product) | Same recipe with the public real train / dev added | relation-v3 + ContractNLI + VitaminC + CFEVER | 5 MB |
| `retrieval-e5/` | C2 retrieval, C4 embeddings | `intfloat/multilingual-e5-small`, unchanged | – (pretrained) | 470 MB |
| `scope-mahalanobis-v1/` | C4 scope | Ledoit-Wolf mean and precision per language and scope setting | KB units + paraphrases-v1 | 5 MB |
| `intent-tfidf-lr-v1/` | C11 intent | TF-IDF character 2–4 grams + logistic regression | intent-v1 train + dev | 2 MB |
| `c1-mdeberta-mix/` | Relation pair classifier (E15 experiment, not registered, not used by the product yet) | mDeBERTa-v3 multilingual NLI cross-encoder fine-tuned 1 epoch | relation-v3 train + 6,000 sampled ContractNLI / VitaminC / CFEVER train claims | 1.1 GB |
| `behavior-v1/` | C5 behaviour | DTW reference medoids and the phase HMM | trajectories-v1 | 20 KB |
| `manifest.json` | – | Registry of the entries above with SHA-256 | – | – |

Pretrained models: `FacebookAI/xlm-roberta-base` (MIT), `intfloat/multilingual-e5-small`
(MIT) and `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` (MIT, revision `b5113eb`). The judge, role and assistant slots call DeepSeek over its API; no LLM weights are
shipped.

To switch recognition on after unpacking, set `CAREER_LAB_RECOGNIZERS=<repo>/runs/local/recognizers`
and `CAREER_LAB_RELATION_ENCODER=<repo>/runs/local/recognizers/c1-xlmr-cpu`.

## 5. Constraints to keep with the package

- VitaminC is CC BY-SA 3.0: `public-real-v1/relation-vitaminc.jsonl` and anything derived from
  it must keep that licence. VitaminC records carry the BIG-bench canary string and must not
  go into any pre-training corpus.
- The Public Jira Dataset's personal fields were anonymised by its authors; we did not add any.
- The TheAgentCompany run logs (no declared licence) and CHEF (no licence) were not taken.
- All G2v data shares one vendor for generation and review (DeepSeek).
