from attendio_shared.contracts import EventEnvelope


def test_event_envelope_defaults():
    env = EventEnvelope(event_name='user.created', source='auth-service', tenant_id='t1', payload={'id': 1})
    assert env.event_name == 'user.created'
    assert env.source == 'auth-service'
    assert env.tenant_id == 't1'
    assert env.payload['id'] == 1
    assert env.occurred_at
