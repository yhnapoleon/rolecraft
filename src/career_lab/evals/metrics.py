import random
from collections import defaultdict


def summarize(rows):
    if not rows:
        return {"count": 0, "accuracy": None, "macro_f1": None, "joint_correctness": None, "false_deduction": None, "infrastructure_errors": 0}
    n = len(rows)
    labels = sorted({r["gold_label"] for r in rows})
    f1 = []
    for label in labels:
        tp = sum(r["gold_label"] == label and r["predicted_label"] == label for r in rows)
        fp = sum(r["gold_label"] != label and r["predicted_label"] == label for r in rows)
        fn = sum(r["gold_label"] == label and r["predicted_label"] != label for r in rows)
        f1.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
    positive = [r for r in rows if r["gold_label"] in {"MET", "SUPPORTED"}]
    negative = [r for r in rows if r["gold_label"] in {"NOT_MET", "CONTRADICTED"}]
    joint = [r for r in rows if r["joint_correct"] is not None]
    return {"count": n, "accuracy": sum(bool(r["label_correct"]) for r in rows)/n, "macro_f1": sum(f1)/len(f1),
            "joint_correctness": sum(bool(r["joint_correct"]) for r in joint)/len(joint) if joint else None,
            "false_deduction": sum(r["predicted_label"] in {"NOT_MET", "CONTRADICTED"} for r in positive)/len(positive) if positive else None,
            "false_pass": sum(r["predicted_label"] in {"MET", "SUPPORTED"} for r in negative)/len(negative) if negative else None,
            "infrastructure_errors": sum(r["error_class"] == "infrastructure_error" for r in rows),
            "abstentions": sum(r["error_class"] == "model_abstention" for r in rows),
            "format_errors": sum(r["error_class"] == "model_format_error" for r in rows)}


def group_bootstrap(rows, seed=0, samples=500):
    groups = defaultdict(list)
    for r in rows:
        groups[r["group"]].append(r)
    if not groups:
        return None
    randomizer = random.Random(seed)
    names = list(groups)
    means = []
    for _ in range(samples):
        drawn = [r for name in randomizer.choices(names, k=len(names)) for r in groups[name]]
        means.append(sum(bool(r["label_correct"]) for r in drawn)/len(drawn))
    means.sort()
    return {"lower": means[int(samples*.025)], "upper": means[min(samples-1, int(samples*.975))], "groups": len(groups), "warning": "Few groups; descriptive interval only" if len(groups) < 10 else None}


def paired_diff(left, right):
    a = {r["trial_key"]: r for r in left}
    b = {r["trial_key"]: r for r in right}
    if a.keys() != b.keys() or any(a[k]["input_hash"] != b[k]["input_hash"] for k in a):
        raise ValueError("paired trials/inputs must match")
    differences = [int(bool(b[k]["label_correct"])) - int(bool(a[k]["label_correct"])) for k in a]
    return {"pairs": len(differences), "accuracy_delta": sum(differences)/len(differences) if differences else None}
