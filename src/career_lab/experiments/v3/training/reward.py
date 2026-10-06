"""Reward/mask/reference-policy mechanisms; this module does not run SFT or GRPO."""
from pathlib import Path
import numpy as np

from career_lab.contracts.v2.core import FileRef,ProtocolError,digest,read_file
from .metrics import grade


def reward(example,output):
    if example.split!="train":raise ProtocolError("reward_train_only",status=403)
    result=grade(example,output)
    invalid=(not result["format_valid"]) or result["error_code"] in {"invalid_evidence_time","prediction_invalid_reference"}
    if invalid or output.status!="ok":total=-1.
    elif not result["label_correct"]:total=-.5
    elif result["evidence_f1"] is None:total=.7
    else:total=.7+.3*result["evidence_f1"]
    return {"total":total,"reward_version":"w08-set-f1-v1","label_correct":result["label_correct"],
            "evidence_score":result["evidence_f1"],"joint_correct":result["joint_correct"],"error_code":result["error_code"]}


def completion_mask(prompt_lengths,total_lengths,width):
    if len(prompt_lengths)!=len(total_lengths) or any(not 0<=p<t<=width for p,t in zip(prompt_lengths,total_lengths,strict=True)):
        raise ProtocolError("completion_mask_lengths_invalid")
    positions=np.arange(width)[None,:]
    return (positions>=np.array(prompt_lengths)[:,None])&(positions<np.array(total_lengths)[:,None])


def masked_cross_entropy(logits,targets,mask):
    logits=np.asarray(logits,dtype=float);targets=np.asarray(targets);mask=np.asarray(mask,dtype=bool)
    if logits.ndim!=3 or logits.shape[:2]!=targets.shape or targets.shape!=mask.shape or not mask.any():raise ProtocolError("completion_loss_shape_invalid")
    if not np.isfinite(logits).all() or (targets[mask]<0).any() or (targets[mask]>=logits.shape[-1]).any():raise ProtocolError("completion_loss_values_invalid")
    selected=logits[mask];selected=selected-selected.max(axis=-1,keepdims=True)
    normalizer=np.log(np.exp(selected).sum(axis=-1))
    return float(np.mean(normalizer-selected[np.arange(len(selected)),targets[mask]]))


def reference_policy(root,base_weights,adapter_weights,*,sft_identity=None):
    if not base_weights or not adapter_weights:raise ProtocolError("sft_adapter_reference_required")
    refs=(*base_weights,*adapter_weights)
    if len({r.path for r in refs})!=len(refs):raise ProtocolError("reference_weight_identity_conflict")
    for ref in refs:read_file(Path(root),ref)
    bound_identity=digest({"base":[r.model_dump(mode="json") for r in base_weights],"active_adapter":[r.model_dump(mode="json") for r in adapter_weights]})
    if sft_identity is not None and sft_identity!=bound_identity:raise ProtocolError("sft_identity_not_bound_to_weights")
    body={"sft_identity":bound_identity,"base_weights":[r.model_dump(mode="json") for r in base_weights],
          "active_adapter_weights":[r.model_dump(mode="json") for r in adapter_weights],"adapter_enabled":True}
    return body|{"reference_hash":digest(body),"training_executed":False}
