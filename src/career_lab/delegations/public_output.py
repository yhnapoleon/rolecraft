"""Final protocol surface check for public role replies; do not trust loose DTOs."""
from pydantic import ValidationError
from career_lab.storage.role_memory import RoleReply
from .http_client import RemoteFailure


def validate_public_output(value):
    if isinstance(value,list):
        for item in value:validate_public_output(item)
    elif isinstance(value,dict):
        if value.get('kind')=='role_context' and 'object_id' in value:raise RemoteFailure('public_projection_unavailable',503)
        if 'role_id' in value and 'session_id' in value and any(k in value for k in ('text','prompt_messages','generation_audit','private_prompt')):
            try:RoleReply.model_validate(value)
            except ValidationError:raise RemoteFailure('public_projection_unavailable',503) from None
        for key,item in value.items():
            # Imported user provenance is inert; it is not a runtime RoleReply.
            if key=='legacy' and isinstance(item,dict):continue
            validate_public_output(item)
