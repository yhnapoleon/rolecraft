from career_lab.contracts.v2.core import AuthContext, Command, ProtocolError, PageRequest
from career_lab.contracts.v2.workspace import ProductShare
from career_lab.contracts.v2.workspace import WorkspaceImport
from career_lab.contracts.v2.requests import TaskCreate, TaskPatch, ProductCreate, ProductEdit, ShareCreate, ShareUpdate
from .domain import OPERATIONS, handle, visible_product
from .ports import authorize, object_scope


class WorkspaceService:
    def __init__(self, repository):
        self.repository = repository

    def execute(self, auth: AuthContext, command: Command):
        if command.operation not in OPERATIONS: raise ProtocolError('capability_not_installed', status=503)
        from .imports import reject_credentials
        if command.operation.startswith('workspace_imports.'): reject_credentials(command.payload)
        types = {'work_items.create':TaskCreate,'work_items.patch':TaskPatch,
                 'work_products.create':ProductCreate,'work_products.edit':ProductEdit,'work_products.adopt':ProductEdit,
                 'work_products.shares.create':ShareCreate,'work_products.shares.update':ShareUpdate,
                 'workspace_imports.preview':WorkspaceImport,'workspace_imports.apply':WorkspaceImport}
        # v2 fingerprints use typed defaults. v1 canonicalizers are untouched.
        parsed = types[command.operation].model_validate(command.payload)
        # TaskPatch uses null for unchanged; clear_parent is its explicit removal
        # operation. Preserve that distinction when materializing typed defaults.
        payload = parsed.model_dump(mode='json',exclude_none=command.operation=='work_items.patch')
        command = command.model_copy(update={'payload':payload})
        if command.operation == 'workspace_imports.preview':
            authorize(auth, self.repository.clock())
            if auth.actor_id != 'learner': raise ProtocolError('capability_denied', status=403)
            return self.repository.read(auth, lambda snap: handle(snap, auth, command, self.repository.clock()).result)
        return self.repository.execute(auth, command, handle)

    def get_product(self, auth, oid, version=None):
        return self.repository.read(auth, lambda snap: self._product_output(auth,visible_product(snap,auth,oid,version).content))

    @staticmethod
    def _product_output(auth, content):
        if auth.actor_id == 'learner': return content
        # Import provenance includes unsaved drafts and unshared old versions.
        return {**content, 'legacy':None, 'shares':[]}

    def list(self, auth, kind, page: PageRequest, *, product_id=None):
        if kind not in {'task','product','share','versions'}: raise ProtocolError('not_found', status=404)
        def query(snap):
            if kind == 'versions':
                if not product_id: raise ProtocolError('product_required')
                candidates = [o for o in snap.objects if o.ref.kind=='product' and o.ref.object_id==product_id]
            else: candidates = list(snap.heads(kind))
            visible = []
            for obj in candidates:
                try:
                    if obj.ref.kind == 'product':
                        if kind=='product' and auth.actor_id!='learner':
                            obj=visible_product(snap,auth,obj.ref.object_id)
                        else: obj=visible_product(snap,auth,obj.ref.object_id,obj.ref.version)
                    elif obj.ref.kind=='share':
                        share=ProductShare.model_validate(obj.content)
                        if product_id and share.product.object_id!=product_id: continue
                        object_scope(auth,share.product.object_id)
                        if auth.actor_id!='learner':
                            if share.recipient_role!=auth.actor_id or share.revoked_at is not None: continue
                            visible_product(snap,auth,share.product.object_id,share.product.version)
                    else:
                        object_scope(auth,obj.ref.object_id)
                        if auth.actor_id!='learner': continue
                    visible.append(self._product_output(auth,obj.content) if obj.ref.kind=='product' else obj.content)
                except ProtocolError as error:
                    if error.status!=404: raise
            if kind=='task': visible.sort(key=lambda x:(x['priority'],x['order'],x['id']))
            if kind=='versions': visible.sort(key=lambda x:x['version'])
            end=page.cursor+page.limit
            return {'items':visible[page.cursor:end], 'next_cursor':end if end<len(visible) else None,
                    'as_of':snap.point.model_dump(mode='json')}
        return self.repository.read(auth,query)


def create_service(engine, authority, *, clock=None):
    from career_lab.storage.workspace_v2 import WorkspaceRepository
    return WorkspaceService(WorkspaceRepository(engine,authority,clock))
