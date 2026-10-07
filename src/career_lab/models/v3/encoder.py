"""A small trainable contextual self-attention encoder for CPU pipeline checks.

This is randomly initialized NumPy research code, not XLM-R, not pretrained and
not SFT. Both relation and evidence losses propagate through attention/embeddings.
"""
from collections import Counter
import hashlib
import re
import time
import numpy as np

from career_lab.contracts.v2.core import ProtocolError
from .temporal import temporal_text
from .core import (LABELS, checked_input, input_problem, training_examples, evidence_target,
                   abstention, prediction, softmax)


def tokens(text):
    return re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]", text.casefold())


def array_digest(arrays):
    h = hashlib.sha256()
    for key in sorted(arrays):
        value = np.ascontiguousarray(arrays[key])
        h.update(key.encode());h.update(str(value.shape).encode());h.update(str(value.dtype).encode());h.update(value.tobytes())
    return h.hexdigest()


class AttentionEncoder:
    kind = "numpy_attention"
    def __init__(self, task_type="relation", *, variant="pack", dimension=12, max_tokens=128,
                 max_vocabulary=4000, seed=5002, evidence_threshold=0.5,aggregation="mean_probabilities"):
        if task_type not in LABELS or variant not in {"pack", "pair"}:
            raise ProtocolError("encoder_configuration_invalid")
        if not 2 <= dimension <= 256 or not 4 <= max_tokens <= 2048 or not 8 <= max_vocabulary <= 100000 or not 0 <= evidence_threshold <= 1:
            raise ProtocolError("encoder_capacity_invalid")
        if aggregation not in {"mean_probabilities","mean_logits"}:raise ProtocolError("aggregation_not_supported")
        self.aggregation=aggregation
        self.task_type, self.variant, self.dimension = task_type, variant, dimension
        self.max_tokens, self.max_vocabulary, self.seed = max_tokens, max_vocabulary, seed
        self.evidence_threshold = evidence_threshold
        self.revision = "untrained-numpy-attention"

    def initialize(self, examples):
        counts = Counter()
        for row in training_examples(examples, self.task_type):
            counts.update(tokens(row.item.evidence.purpose + " " + row.item.evidence.claim+" "+temporal_text(row.item)))
            for candidate in row.item.evidence.candidate_evidence: counts.update(tokens(candidate.text+" "+temporal_text(row.item,candidate)))
        selected = sorted(counts, key=lambda x: (-counts[x], x))[:self.max_vocabulary-4]
        self.vocabulary = {"[PAD]": 0, "[UNK]": 1, "[CLS]": 2, "[SEP]": 3} | {t: i+4 for i, t in enumerate(selected)}
        rng = np.random.default_rng(self.seed);d=self.dimension;k=len(LABELS[self.task_type])
        self.params = {"embedding": rng.normal(0, .15, (len(self.vocabulary),d)),
            "query": rng.normal(0, 1/np.sqrt(d), (d,d)), "key": rng.normal(0, 1/np.sqrt(d), (d,d)),
            "value": rng.normal(0, 1/np.sqrt(d), (d,d)), "relation": rng.normal(0,.1,(d,k)),
            "relation_bias": np.zeros(k), "evidence": rng.normal(0,.1,d), "evidence_bias": np.zeros(1)}
        self.params["embedding"][0] = 0

    def _sequence(self, item, candidates):
        ids = [2] + [self.vocabulary.get(t,1) for t in tokens(item.evidence.purpose + " " + item.evidence.claim+" "+temporal_text(item))] + [3]
        groups = []
        for c in candidates:
            encoded = [self.vocabulary.get(t,1) for t in tokens(c.text+" "+temporal_text(item,c))]
            if not encoded: raise ProtocolError("empty_candidate_text")
            groups.append(tuple(range(len(ids),len(ids)+len(encoded))))
            ids.extend(encoded);ids.append(3)
        if len(ids) > self.max_tokens:
            raise ProtocolError("encoder_input_truncated")
        return np.array(ids,dtype=np.int64), tuple(groups)

    def encode_inputs(self, item):
        candidates = item.evidence.candidate_evidence
        if not candidates: raise ProtocolError("no_candidate_evidence")
        if self.variant == "pack": return [self._sequence(item,candidates)]
        return [self._sequence(item,[c]) for c in candidates]

    def _forward(self, ids, groups):
        p=self.params;d=self.dimension;mask=ids!=0
        if not mask.any(): raise ProtocolError("empty_encoder_mask")
        pos = np.arange(len(ids))[:,None] / np.power(10000., np.arange(d)[None,:]/d)
        X=(p["embedding"][ids] + .05*np.sin(pos))*mask[:,None]
        Q,K,V=X@p["query"],X@p["key"],X@p["value"]
        logits=Q@K.T/np.sqrt(d);logits[:,~mask]=-1e30
        A=softmax(logits);T=np.tanh(A@V+X);H=T*mask[:,None]
        z=H[mask].mean(axis=0)
        ev=np.stack([H[list(g)].mean(axis=0) for g in groups]) if groups else np.empty((0,d))
        cache=(ids,groups,mask,X,Q,K,V,A,T)
        return z,ev,cache

    def _backward(self, cache, gz, ge):
        ids,groups,mask,X,Q,K,V,A,T=cache;p=self.params;d=self.dimension
        gH=np.zeros_like(X);gH[mask]+=gz/mask.sum()
        for index,g in enumerate(groups):gH[list(g)]+=ge[index]/len(g)
        gZ=gH*(1-T*T)*mask[:,None]
        gA=gZ@V.T;gV=A.T@gZ
        gS=A*(gA-(gA*A).sum(axis=1,keepdims=True))
        gQ=gS@K/np.sqrt(d);gK=gS.T@Q/np.sqrt(d)
        gX=gZ+gQ@p["query"].T+gK@p["key"].T+gV@p["value"].T
        embedding=np.zeros_like(p["embedding"])
        np.add.at(embedding,ids[mask],gX[mask])
        return {"embedding":embedding,"query":X.T@gQ,"key":X.T@gK,"value":X.T@gV}

    def _represent(self,item):
        encoded=self.encode_inputs(item)
        outputs=[self._forward(ids,groups) for ids,groups in encoded]
        z=np.stack([x[0] for x in outputs]);ev=np.concatenate([x[1] for x in outputs],axis=0)
        return z,ev,[x[2] for x in outputs]

    def loss_and_grad(self,row):
        z,ev,caches=self._represent(row.item);p=self.params
        logits=z@p["relation"]+p["relation_bias"];each=softmax(logits)
        probs=each.mean(axis=0) if self.aggregation=="mean_probabilities" else softmax(logits.mean(axis=0))
        label=LABELS[self.task_type].index(row.annotation.final.label)
        loss=-np.log(max(probs[label],1e-15))
        # Mean-probability aggregation; loss supervises the entire evidence pack,
        # not an invented individual relation label for each incomplete pair.
        if self.aggregation=="mean_probabilities":
            dp=np.zeros_like(each);dp[:,label]=-1/(max(probs[label],1e-15)*len(each))
            gl=each*(dp-(dp*each).sum(axis=1,keepdims=True))
        else:
            gl=np.broadcast_to(probs,(len(each),len(probs))).copy();gl[:,label]-=1;gl/=len(each)
        grads={k:np.zeros_like(v) for k,v in p.items()}
        grads["relation"]=z.T@gl;grads["relation_bias"]=gl.sum(axis=0)
        gz=gl@p["relation"].T
        scores=1/(1+np.exp(-np.clip(ev@p["evidence"]+p["evidence_bias"][0],-50,50)))
        wanted=evidence_target(row)
        ge=np.zeros_like(ev)
        if wanted is not None:
            target=np.array([int(c.id in wanted) for c in row.item.evidence.candidate_evidence])
            logits=ev@p["evidence"]+p["evidence_bias"][0]
            loss+=np.mean(np.logaddexp(0,logits)-target*logits)
            gl_ev=(scores-target)/len(target)
            grads["evidence"]=ev.T@gl_ev;grads["evidence_bias"][0]=gl_ev.sum()
            ge=gl_ev[:,None]*p["evidence"][None,:]
        offset=0
        for index,cache in enumerate(caches):
            n=len(cache[1]);part=self._backward(cache,gz[index],ge[offset:offset+n]);offset+=n
            for key,value in part.items():grads[key]+=value
        return float(loss),grads

    def fit(self,examples,*,epochs=8,learning_rate=.05):
        rows=training_examples(examples,self.task_type)
        if type(epochs) is not int or epochs<1 or not np.isfinite(learning_rate) or learning_rate<=0:
            raise ProtocolError("training_hyperparameters_invalid")
        original_count=len(rows);kept=[];excluded=[]
        for row in rows:
            candidates=row.item.evidence.candidate_evidence
            query=2+len(tokens(row.item.evidence.purpose+" "+row.item.evidence.claim+" "+temporal_text(row.item)))
            sizes=[len(tokens(c.text+" "+temporal_text(row.item,c)))+1 for c in candidates]
            total=query+(sum(sizes) if self.variant=="pack" else max(sizes,default=0))
            reason="no_candidate_evidence" if not candidates else "encoder_input_truncated" if total>self.max_tokens else None
            if reason:excluded.append({"record_id":row.record_id,"input_hash":row.annotation.input_hash,"reason":reason,"tokens":total,"max_tokens":self.max_tokens})
            else:kept.append(row)
        try:rows=training_examples(kept,self.task_type)
        except ProtocolError as exc:
            exc.report=dict(getattr(exc,"report",{}),excluded_records=excluded,input_train_records=original_count,kept_train_records=len(kept),filter_reason="revalidated after declared capacity filter")
            raise
        self.initialize(rows)
        initial={k:v.copy() for k,v in self.params.items()};before=array_digest(initial)
        start=time.perf_counter();rng=np.random.default_rng(self.seed);losses=[];max_gradient=0.
        for epoch in range(epochs):
            values=[]
            for index in rng.permutation(len(rows)):
                loss,grads=self.loss_and_grad(rows[index])
                if not np.isfinite(loss) or any(not np.isfinite(g).all() for g in grads.values()):
                    exc=ProtocolError("nonfinite_training_gradient");exc.record_id=rows[index].record_id;raise exc
                norm=np.sqrt(sum(np.square(g).sum() for g in grads.values()));scale=min(1.,5/max(norm,1e-12))
                max_gradient=max(max_gradient,max(float(np.abs(g).max()) for g in grads.values()))
                for key in self.params:self.params[key]-=learning_rate*scale*grads[key]
                values.append(loss)
            losses.append(float(np.mean(values)))
        after=array_digest(self.params);delta=float(np.sqrt(sum(np.square(self.params[k]-initial[k]).sum() for k in self.params)))
        if before==after or delta==0:raise ProtocolError("training_did_not_update_parameters")
        self.revision="trained-numpy-attention-pending-bundle"
        self.training_report={"architecture":"single-head contextual self-attention, residual tanh, categorical and evidence heads",
            "implementation":"NumPy analytic gradients", "variant":self.variant,"aggregation":self.aggregation,"input_train_records":original_count,"excluded_records":excluded,
            "pretrained":False,"post_training":False,"fixture_quality_claim":False,"fit_split":"train","seed":self.seed,
            "epochs":epochs,"learning_rate":learning_rate,"losses":losses,"fit_seconds":time.perf_counter()-start,
            "before_weights":before,"after_weights":after,"weight_delta_l2":delta,"max_abs_gradient":max_gradient,
            "evidence_train_ids":[r.record_id for r in rows if r.annotation.final.evidence_evaluable],
            "label_only_train_ids":[r.record_id for r in rows if not r.annotation.final.evidence_evaluable],
            "train_records":len(rows),"train_ids":[r.record_id for r in rows],"input_hashes":[r.annotation.input_hash for r in rows],
            "parameters":sum(v.size for v in self.params.values()),"device":"CPU","truncation":"reject; never silently drop necessary evidence"}
        return self.training_report

    def predict(self,item):
        item=checked_input(item)
        if item.task_type!=self.task_type:raise ProtocolError("candidate_task_mismatch")
        if input_problem(item):return abstention(item,self.revision,input_problem(item))
        if not hasattr(self,"params"):raise ProtocolError("model_not_trained")
        try:z,ev,_=self._represent(item)
        except ProtocolError as exc:return abstention(item,self.revision,exc.code)
        logits=z@self.params["relation"]+self.params["relation_bias"]
        probs=softmax(logits).mean(axis=0) if self.aggregation=="mean_probabilities" else softmax(logits.mean(axis=0))
        scores=1/(1+np.exp(-np.clip(ev@self.params["evidence"]+self.params["evidence_bias"][0],-50,50)))
        return prediction(item,self.revision,probs,scores,self.evidence_threshold)

    def arrays(self):return {k:v.copy() for k,v in self.params.items()}

    def configuration(self):
        return {"preprocessing_revision":"historical-time-v1","kind":self.kind,"task_type":self.task_type,"variant":self.variant,"dimension":self.dimension,
            "aggregation":self.aggregation,"max_tokens":self.max_tokens,"max_vocabulary":self.max_vocabulary,"seed":self.seed,"evidence_threshold":self.evidence_threshold,
            "vocabulary":self.vocabulary,"labels":list(LABELS[self.task_type]),"training_report":self.training_report}

    @classmethod
    def restore(cls,config,arrays):
        keys=("variant","dimension","max_tokens","max_vocabulary","seed","evidence_threshold","aggregation")
        obj=cls(config["task_type"],**{k:config[k] for k in keys});obj.vocabulary=config["vocabulary"]
        v=len(obj.vocabulary);d=obj.dimension;k=len(LABELS[obj.task_type])
        shapes={"embedding":(v,d),"query":(d,d),"key":(d,d),"value":(d,d),"relation":(d,k),"relation_bias":(k,),"evidence":(d,),"evidence_bias":(1,)}
        if config["labels"]!=list(LABELS[obj.task_type]) or set(obj.vocabulary.values())!=set(range(v)):
            raise ProtocolError("encoder_vocabulary_or_labels_invalid")
        if any(obj.vocabulary.get(t)!=i for i,t in enumerate(("[PAD]","[UNK]","[CLS]","[SEP]"))):
            raise ProtocolError("encoder_special_tokens_invalid")
        if set(arrays)!=set(shapes) or any(arrays[x].shape!=s or not np.isfinite(arrays[x]).all() for x,s in shapes.items()):
            raise ProtocolError("encoder_weights_invalid")
        obj.params={x:np.array(a,dtype=float,copy=True) for x,a in arrays.items()};obj.training_report=config["training_report"]
        return obj
