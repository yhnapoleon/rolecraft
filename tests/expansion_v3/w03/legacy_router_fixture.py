"""Test-only r3 router; official API integration uses frozen Gateway slots."""
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from career_lab.contracts.v2.core import AuthContext, Command, ProtocolError, PageRequest


def create_router(service, auth_dependency, prefix='/sessions/{session_id}'):
    router=APIRouter(prefix=prefix,tags=['workspace-v2'])

    def scoped(session_id: str, auth: AuthContext = Depends(auth_dependency)):
        if auth.session_id!=session_id: raise HTTPException(404,'not found')
        return auth

    def run(operation, body, auth, expected=None):
        try:
            if body.operation!=operation: raise ProtocolError('operation_mismatch')
            if expected:
                for key,value in expected.items():
                    if body.payload.get(key)!=value: raise ProtocolError('path_payload_mismatch')
            return service.execute(auth,body)
        except ProtocolError as error:
            return JSONResponse({'schema_version':2,'code':error.code,'message':str(error)},status_code=error.status)
        except ValidationError:
            # Do not echo a private product or credential in validation details.
            return JSONResponse({'schema_version':2,'code':'invalid_request','message':'Invalid workspace request'},status_code=422)

    def read(call):
        try: return call()
        except ProtocolError as error:
            return JSONResponse({'schema_version':2,'code':error.code,'message':str(error)},status_code=error.status)
        except ValidationError:
            return JSONResponse({'schema_version':2,'code':'invalid_request','message':'Invalid page'},status_code=422)

    @router.get('/work-items')
    def tasks(cursor:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),auth=Depends(scoped)):
        return read(lambda:service.list(auth,'task',PageRequest(cursor=cursor,limit=limit)))

    @router.post('/work-items')
    def create_task(body:Command,auth=Depends(scoped)): return run('work_items.create',body,auth)

    @router.post('/work-items/batch')
    def batch_tasks(body:Command,auth=Depends(scoped)): return run('work_items.batch',body,auth)

    @router.patch('/work-items/{item_id}')
    def update_task(item_id:str,body:Command,auth=Depends(scoped)):
        return run('work_items.update',body,auth,{'item_id':item_id})

    @router.get('/work-products')
    def products(cursor:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),auth=Depends(scoped)):
        return read(lambda:service.list(auth,'product',PageRequest(cursor=cursor,limit=limit)))

    @router.post('/work-products')
    def create_product(body:Command,auth=Depends(scoped)): return run('work_products.create',body,auth)

    @router.get('/work-products/{product_id}/versions')
    def product_versions(product_id:str,cursor:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),auth=Depends(scoped)):
        return read(lambda:service.list(auth,'versions',PageRequest(cursor=cursor,limit=limit),product_id=product_id))

    @router.get('/work-products/{product_id}/versions/{version}')
    def version(product_id:str,version:int=Path(ge=1),auth=Depends(scoped)):
        return read(lambda:service.get_product(auth,product_id,version))

    @router.post('/work-products/{product_id}/versions')
    def edit_product(product_id:str,body:Command,auth=Depends(scoped)):
        return run('work_products.versions.create',body,auth,{'product_id':product_id})

    @router.post('/work-products/{product_id}/adoption')
    def adopt(product_id:str,body:Command,auth=Depends(scoped)):
        return run('work_products.adopt',body,auth,{'product_id':product_id})

    @router.get('/work-products/{product_id}/shares')
    def shares(product_id:str,cursor:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),auth=Depends(scoped)):
        return read(lambda:service.list(auth,'share',PageRequest(cursor=cursor,limit=limit),product_id=product_id))

    @router.post('/work-products/{product_id}/shares')
    def share(product_id:str,body:Command,auth=Depends(scoped)):
        return run('work_products.shares.create',body,auth,{'product_id':product_id})

    @router.post('/work-products/{product_id}/shares/{share_id}')
    def update_share(product_id:str,share_id:str,body:Command,auth=Depends(scoped)):
        return run('work_products.shares.change',body,auth,{'product_id':product_id,'share_id':share_id})

    @router.post('/workspace-imports')
    def import_workspace(body:Command,auth=Depends(scoped)):
        if body.payload.get('mode') not in {'preview','apply'}:
            return JSONResponse({'code':'invalid_request','message':'Import mode required'},status_code=422)
        return run('workspace_imports',body,auth)

    return router
