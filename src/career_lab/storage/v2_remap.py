"""Schema-directed namespace remapping; arbitrary JSON and provenance remain opaque."""
from copy import deepcopy
from pydantic import BaseModel
from career_lab.contracts import v2 as C


def identity_key(kind, object_id):
    return C.canonical(['object', kind, object_id])


def event_key(event_id):
    return C.canonical(['event', event_id])


def transaction_key(transaction_id):
    return C.canonical(['transaction', transaction_id])

# These are identity fields declared by public request models, never arbitrary dictionary keys.
SCALAR_IDS = {
    C.ProductEdit: {'product_id': 'product'},
    C.ProductAdopt: {'product_id': 'product'},
    C.ShareCreate: {'product_id': 'product'},
    C.ShareUpdate: {'product_id': 'product', 'share_id': 'share'},
    C.TaskPatch: {'item_id': 'task'},
    C.ResourcePage: {'product_id': 'product', 'review_id': 'review', 'submission_id': 'submission'},
    C.EvidenceRead: {'submission_id': 'submission'},
}
OPAQUE_MODELS = (C.LegacyProvenance, C.LegacyAnnotation, C.FileRef, C.Executor)


class NamespaceRemapper:
    def __init__(self, parent_session, target_session, mapping):
        self.parent_session, self.target_session, self.mapping = parent_session, target_session, mapping

    def object_id(self, kind, value):
        return self.mapping.get(identity_key(kind, value), value)

    def session(self, value):
        if value != self.parent_session:
            raise C.ProtocolError('foreign_session_reference', status=403)
        return self.target_session

    def value(self, value):
        if isinstance(value, BaseModel):
            return self.model(value)
        if isinstance(value, tuple):
            return tuple(self.value(x) if isinstance(x, BaseModel) else deepcopy(x) for x in value)
        if isinstance(value, list):
            return [self.value(x) if isinstance(x, BaseModel) else deepcopy(x) for x in value]
        if isinstance(value, dict):
            # Typed dict[str, Model] values are models after validation; JsonValue/string dictionaries are not.
            return {k: self.value(v) if isinstance(v, BaseModel) else deepcopy(v) for k, v in value.items()}
        return deepcopy(value)

    def model(self, model, *, entity_ref=None):
        if isinstance(model, OPAQUE_MODELS):
            return model.model_copy(deep=True)
        data = {name: self.value(getattr(model, name)) for name in type(model).model_fields}
        if isinstance(model, C.ObjectRef):
            data['session_id'] = self.session(model.session_id)
            data['object_id'] = self.object_id(model.kind, model.object_id)
        elif isinstance(model, C.WorldStateV2):
            data['session_id'] = self.session(model.session_id)
            data['cycle_id'] = self.object_id('cycle', model.cycle_id)
        elif isinstance(model, C.StoredEvent):
            data['session_id'] = self.session(model.session_id)
            data['id'] = self.mapping[event_key(model.id)]
            data['transaction_id'] = self.mapping[transaction_key(model.transaction_id)]
        elif isinstance(model, C.ActionBoundary):
            data['transaction_id'] = self.mapping[transaction_key(model.transaction_id)]
        elif isinstance(model, C.AssistantConfig):
            data['session_id'] = self.session(model.session_id)
            data['id'] = self.object_id('config', model.id)
        for cls, fields in SCALAR_IDS.items():
            if type(model) is cls:
                for field, kind in fields.items():
                    if data[field] is not None:
                        data[field] = self.object_id(kind, data[field])
        if entity_ref is not None:
            if 'session_id' in data:
                data['session_id'] = self.session(model.session_id)
            identifier = 'product_id' if entity_ref.kind == 'product' else 'id'
            if identifier in data:
                data[identifier] = self.object_id(entity_ref.kind, entity_ref.object_id)
        if isinstance(model, C.WorkProductVersion):
            payload = data['structured_payload']
            data['content_hash'] = C.digest({'content': data['content'], 'structured_payload': payload.model_dump(mode='json') if payload else None})
        return type(model).model_validate(data)
