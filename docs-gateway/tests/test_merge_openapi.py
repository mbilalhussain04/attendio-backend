from docs_gateway.main import merge_openapi


def test_merge_openapi_combines_paths_and_tags():
    auth = {
        'paths': {'/api/v1/auth/login': {'post': {'tags': ['Authentication']}}},
        'components': {'schemas': {'A': {'type': 'object'}}, 'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer'}}},
        'tags': [{'name': 'Authentication'}],
    }
    att = {
        'paths': {'/api/v1/attendance/check-in': {'post': {'tags': ['Attendance']}}},
        'components': {'schemas': {'B': {'type': 'object'}}, 'securitySchemes': {}},
        'tags': [{'name': 'Attendance'}],
    }
    storage = {
        'paths': {'/api/v1/storage/upload': {'post': {'tags': ['Storage']}}},
        'components': {'schemas': {'C': {'type': 'object'}}, 'securitySchemes': {}},
        'tags': [{'name': 'Storage'}],
    }
    merged = merge_openapi(auth, att, storage)
    assert '/api/v1/auth/login' in merged['paths']
    assert '/api/v1/attendance/check-in' in merged['paths']
    assert '/api/v1/storage/upload' in merged['paths']
    assert 'A' in merged['components']['schemas']
    assert 'B' in merged['components']['schemas']
    assert 'C' in merged['components']['schemas']
    tag_names = {t['name'] for t in merged['tags'] if isinstance(t, dict)}
    assert 'Authentication' in tag_names
    assert 'Attendance' in tag_names
    assert 'Storage' in tag_names
