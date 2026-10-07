from copy import deepcopy

import pytest

from career_lab.contracts import v2 as C
from career_lab.delegations.http_client import RemoteFailure
from examples.byo_agent_client.service_check import check_public_fragments


def fragment():
    return {'ref': {'session_id': 'session1', 'kind': 'material', 'object_id': 'brief', 'version': 1,
                    'observed_at_seq': 2, 'valid_from_seq': 0, 'span_start': 0, 'span_end': 6, 'quote': 'Policy'},
            'text': 'Policy', 'channel': 'material', 'verification': 'verified'}


REF = C.ObjectRef(session_id='session1', kind='material', object_id='brief', version=1)


@pytest.mark.parametrize('ids', [[], ['internal_fact']])
def test_material_server_wire_cannot_hide_private_ids_behind_client_projection(ids):
    part = fragment(); part['fact_ids'] = ids
    with pytest.raises(RemoteFailure, match='material_private_metadata'):
        check_public_fragments([part], REF)


@pytest.mark.parametrize('change', ['text', 'quote', 'span_start', 'version'])
def test_material_recovery_keeps_exact_body_quote_location_and_version(change):
    original = fragment(); changed = deepcopy(original)
    if change == 'text': changed['text'] = 'Other policy'
    elif change == 'quote': changed['ref']['quote'] = 'Other'
    elif change == 'version': changed['ref']['version'] = 2
    else: changed['ref']['span_start'] = 1
    with pytest.raises(RemoteFailure): check_public_fragments([changed], REF, [original])


def test_material_object_read_can_have_later_observation_but_same_citation():
    original = fragment(); later = deepcopy(original)
    later['ref']['observed_at_seq'] = 7
    assert check_public_fragments([later], REF, [original]) == check_public_fragments([original], REF)
