"""Discover the exact public model set used by export and runtime OpenAPI."""
import inspect
from pydantic import BaseModel

def public_models():
    from career_lab.contracts import v2
    from career_lab.api.modules import CreateSessionV2,JobEnvelope,V2Response
    from career_lab.storage.v2_store import ObjectWrite,EventDraft,JobRequest,TransactionResult
    models={name:obj for name,obj in vars(v2).items() if inspect.isclass(obj) and issubclass(obj,BaseModel) and obj.__module__.startswith('career_lab.contracts.v2')}
    models.update({x.__name__:x for x in [CreateSessionV2,JobEnvelope,V2Response,ObjectWrite,EventDraft,JobRequest,TransactionResult]})
    return dict(sorted(models.items()))

REQUEST_MODELS={
 'work_items.batch':'TaskBatch','work_products.adopt':'ProductAdopt',
 'requests.read':'RequestResultQuery','actions':'ActionInput','tests.create':'TestRequestV2','tests.list':'ResourcePage',
 'turns.create':'TurnInput','submissions.create':'SubmitInput','submissions.list':'ResourcePage',
 'feedback.create':'FeedbackInput','feedback.read':'ResourcePage','approvals.resolve':'ApprovalInput',
 'materials.list':'ResourcePage','timeline':'ResourcePage','evidence.read':'EvidenceRead',
 'work_items.create':'TaskCreate','work_items.list':'ResourcePage','work_items.update':'TaskPatch',
 'work_products.create':'ProductCreate','work_products.list':'ResourcePage',
 'work_products.versions.create':'ProductEdit','work_products.versions.list':'ResourcePage',
 'work_products.shares.create':'ShareCreate','work_products.shares.change':'ShareUpdate',
 'work_products.shares.list':'ResourcePage','workspace_imports.read':'ResourcePage','workspace_imports.list':'ResourcePage',
 'workspace_imports':'WorkspaceImport','reviews.create':'ReviewInput','reviews.read':'ResourcePage',
 'revision_cycles':'BeginRevisionInput','observation':'ResourcePage','tools':'ResourcePage',
 'delegations.create':'DelegationInput','delegations.revoke':'DelegationRevoke',
}

def install_openapi(app):
    from fastapi.openapi.utils import get_openapi
    def build():
        if app.openapi_schema:return app.openapi_schema
        schema=get_openapi(title=app.title,version=app.version,routes=app.routes)
        components=schema.setdefault('components',{}).setdefault('schemas',{})
        for name,model in public_models().items():
            value=model.model_json_schema(ref_template='#/components/schemas/{model}')
            for key,item in value.pop('$defs',{}).items():components[key]=item
            components[name]=value
        schema['x-rolecraft-module-payloads']={name:{'$ref':'#/components/schemas/'+model} for name,model in REQUEST_MODELS.items()}
        schema['x-rolecraft-v2-boundary']='Explicit schema_version=2; uninstalled modules return503. Internal snapshots are not public tools.'
        app.openapi_schema=schema
        return schema
    app.openapi=build
