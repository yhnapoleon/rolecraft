"""Public v2 routes exist before business modules; uninstalled slots return 503."""

from fastapi import Depends
from career_lab.contracts.v2 import Command, ProtocolError
from .modules import SessionAccess

ROUTES = [
    ("POST", "/configuration", "configuration.apply"),
    ("GET", "/reviews", "reviews.read"),
    ("GET", "/workbench", "workbench.read"),
    ("POST", "/turns/display", "turns.display"),
    ("GET", "/feedback-records/{feedback_id}", "feedback.records.read"),
    ("POST", "/feedback/{feedback_id}/responses", "feedback.responses.create"),
    ("GET", "/feedback/{feedback_id}/responses", "feedback.responses.list"),
    ("GET", "/feedback-responses/{response_id}", "feedback.responses.read"),
    ("POST", "/work-items/batch", "work_items.batch"),
    ("POST", "/work-products/{product_id}/adoption", "work_products.adopt"),
    ("GET", "/work-items", "work_items.list"),
    ("POST", "/work-items", "work_items.create"),
    ("PATCH", "/work-items/{item_id}", "work_items.update"),
    ("GET", "/work-products", "work_products.list"),
    ("POST", "/work-products", "work_products.create"),
    ("GET", "/work-products/{product_id}/versions", "work_products.versions.list"),
    ("POST", "/work-products/{product_id}/versions", "work_products.versions.create"),
    ("POST", "/work-products/{product_id}/shares", "work_products.shares.create"),
    ("POST", "/work-products/{product_id}/shares/{share_id}", "work_products.shares.change"),
    ("GET", "/work-products/{product_id}/shares", "work_products.shares.list"),
    ("GET", "/workspace-imports", "workspace_imports.list"),
    ("GET", "/workspace-imports/{import_id}", "workspace_imports.read"),
    ("POST", "/workspace-imports", "workspace_imports"),
    ("POST", "/reviews", "reviews.create"),
    ("GET", "/reviews/{review_id}", "reviews.read"),
    ("POST", "/revision-cycles", "revision_cycles"),
    ("GET", "/observation", "observation"),
    ("GET", "/tools", "tools"),
    ("POST", "/delegations", "delegations.create"),
    ("DELETE", "/delegations/{delegation_id}", "delegations.revoke"),
]


def mount_v2_routes(app, gateway, auth_dependency):
    from fastapi import Request

    for method, path, name in ROUTES:

        def make_endpoint(operation, write):
            if write:

                def endpoint(request: Request, body: Command, session_id=Depends(auth_dependency)):
                    if not isinstance(session_id, SessionAccess):
                        raise ProtocolError("v2_session_required", status=409)
                    params = {k: v for k, v in request.path_params.items() if k != "session_id"}
                    return gateway.dispatch(
                        session_id.context, operation, body.model_dump(mode="json"), params
                    )
            else:

                def endpoint(
                    request: Request,
                    session_id=Depends(auth_dependency),
                    cursor: int = 0,
                    limit: int = 50,
                    since_seq: int | None = None,
                ):
                    if not isinstance(session_id, SessionAccess):
                        raise ProtocolError("v2_session_required", status=409)
                    params = {k: v for k, v in request.path_params.items() if k != "session_id"}
                    params.update(cursor=cursor, limit=limit)
                    if since_seq is not None:
                        params["since_seq"] = since_seq
                    return gateway.dispatch(session_id.context, operation, params)

            endpoint.__name__ = operation.replace(".", "_")
            return endpoint

        app.add_api_route(
            "/sessions/{session_id}" + path,
            make_endpoint(name, method != "GET"),
            methods=[method],
            response_model=None,
        )
