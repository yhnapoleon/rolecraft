"""Explicit old character-MLP baseline, never presented as a contextual encoder."""
import time
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from career_lab.contracts.evaluation import EvidencePackage,CandidateEvidence
from career_lab.models.linear import TextClassifier
from career_lab.contracts.v2.core import ProtocolError
from .core import LABELS,training_examples,checked_input,input_problem,abstention,prediction,softmax


def legacy_item(item):
    p=item.evidence
    return EvidencePackage(item_id=p.item_id,task_type="relation",criterion=p.criterion or "user_claim",claim=p.claim,
        as_of_seq=p.as_of.business_seq,candidate_evidence=tuple(CandidateEvidence(id=c.id,version=c.ref.version,text=c.text) for c in p.candidate_evidence),completeness="complete")


class LegacyMLP:
    kind="legacy_character_mlp"
    def __init__(self,seed=5002):self.seed=seed;self.task_type="relation";self.revision="untrained-legacy-character-mlp"
    def fit(self,examples):
        rows=training_examples(examples,"relation");started=time.perf_counter()
        original=TextClassifier("encoder",seed=self.seed).fit([legacy_item(r.item) for r in rows],[r.annotation.final.label for r in rows])
        self.vectorizer=original.vectorizer;self.coefs=[v.copy() for v in original.classifier.coefs_];self.biases=[v.copy() for v in original.classifier.intercepts_]
        self.class_order=list(original.classifier.classes_)
        self.training_report={"architecture":"legacy character binary n-grams + tanh MLP(32,16)","contextual_encoder":False,
            "fit_split":"train","fit_seconds":time.perf_counter()-started,"seed":self.seed,"optimizer":"lbfgs",
            "iterations":int(original.classifier.n_iter_),"final_loss":float(original.classifier.loss_),
            "converged_before_limit":original.classifier.n_iter_<original.classifier.max_iter,
            "evidence_selection":"all-candidate legacy baseline; excess citations are penalized", "pretrained":False,
            "train_ids":[r.record_id for r in rows],"input_hashes":[r.annotation.input_hash for r in rows]}
        self.revision="trained-legacy-character-mlp-pending-bundle"
        return self.training_report
    def predict(self,item):
        item=checked_input(item)
        if item.task_type!="relation":raise ProtocolError("legacy_relation_only")
        if input_problem(item):return abstention(item,self.revision,input_problem(item))
        if not hasattr(self,"coefs"):raise ProtocolError("model_not_trained")
        p=item.evidence;text=p.claim+"\n"+"\n".join(c.text for c in p.candidate_evidence)
        h=self.vectorizer.transform([text]).toarray()
        for w,b in zip(self.coefs[:-1],self.biases[:-1],strict=True):h=np.tanh(h@w+b)
        raw=softmax(h@self.coefs[-1]+self.biases[-1])[0]
        ordered=raw[[self.class_order.index(label) for label in LABELS["relation"]]]
        return prediction(item,self.revision,ordered,np.ones(len(p.candidate_evidence)))
    def arrays(self):return {f"coef_{i}":a for i,a in enumerate(self.coefs)}|{f"bias_{i}":a for i,a in enumerate(self.biases)}
    def configuration(self):
        return {"preprocessing_revision":"historical-time-v1","kind":self.kind,"task_type":"relation","seed":self.seed,"vocabulary":{k:int(v) for k,v in self.vectorizer.vocabulary_.items()},
                "class_order":self.class_order,"labels":list(LABELS["relation"]),"training_report":self.training_report}
    @classmethod
    def restore(cls,config,arrays):
        obj=cls(config["seed"]);vocab=config["vocabulary"];v=len(vocab)
        if config["labels"]!=list(LABELS["relation"]) or set(config["class_order"])!=set(LABELS["relation"]) or set(vocab.values())!=set(range(v)):
            raise ProtocolError("legacy_model_metadata_invalid")
        shapes={"coef_0":(v,32),"coef_1":(32,16),"coef_2":(16,3),"bias_0":(32,),"bias_1":(16,),"bias_2":(3,)}
        if set(arrays)!=set(shapes) or any(arrays[k].shape!=s or not np.isfinite(arrays[k]).all() for k,s in shapes.items()):raise ProtocolError("legacy_model_weights_invalid")
        obj.vectorizer=CountVectorizer(analyzer="char",ngram_range=(1,2),vocabulary=vocab,binary=True)
        obj.coefs=[arrays[f"coef_{i}"] for i in range(3)];obj.biases=[arrays[f"bias_{i}"] for i in range(3)]
        obj.class_order=config["class_order"];obj.training_report=config["training_report"];return obj
