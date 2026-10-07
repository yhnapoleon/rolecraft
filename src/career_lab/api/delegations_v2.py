"""W06 registrations only; the integrator owns app/CLI/production source wiring."""
from career_lab.api.modules import Operation,V2Response
from career_lab.contracts import v2 as C
from career_lab.delegations.service import issue,revoke,ToolService
from career_lab.delegations.observation import build_observation


def install_delegations(registry,*,source_provider=None,max_ttl_seconds=3600,synchronous=None):
    registry.register(Operation('delegations.create','delegate',C.DelegationInput,
        lambda store,payload,auth,request_id:issue(store,payload,auth,request_id,max_ttl_seconds=max_ttl_seconds),
        service_mode=True,response_model=V2Response))
    registry.register(Operation('delegations.revoke','delegate',C.DelegationRevoke,revoke,service_mode=True,response_model=V2Response))
    holder={}
    def service():
        if 'gateway' not in holder:raise C.ProtocolError('delegation_gateway_unbound',status=503)
        return ToolService(holder['gateway'],**({'synchronous':synchronous} if synchronous is not None else {}),
            unavailable={} if source_provider else {'observation':'observation_source_unavailable'})
    registry.register(Operation('tools','read',C.ResourcePage,
        lambda view,page,auth:V2Response(result={'tools':[t.model_dump(mode='json') for t in service().catalogue(auth,view.state)]}),
        mutates=False,response_model=V2Response))
    registry.register(Operation('observation','read',C.ResourcePage,
        lambda view,page,auth:build_observation(view,page,auth,service().catalogue(auth,view.state),source_provider),
        mutates=False,response_model=C.Observation))
    def bind_gateway(gateway):
        if gateway.registry is not registry:raise ValueError('gateway registry mismatch')
        if 'gateway' in holder and holder['gateway'] is not gateway:raise ValueError('gateway already bound')
        holder['gateway']=gateway
        return service()
    return bind_gateway
