from app.middleware import tenant as tenant_middleware


def test_platform_hosts_include_public_api_gateway(monkeypatch):
    monkeypatch.setattr(tenant_middleware.settings, 'AUTH_BASE_DOMAIN', 'api.attendio.technoflick.com')
    monkeypatch.setattr(tenant_middleware.settings, 'DEFAULT_ROOT_DOMAIN', 'attendio.technoflick.com')

    hosts = tenant_middleware.platform_hosts()

    assert 'api.attendio.technoflick.com' in hosts
    assert 'attendio.technoflick.com' in hosts
    assert 'www.attendio.technoflick.com' in hosts


def test_strip_port_normalizes_host():
    assert tenant_middleware.strip_port('Api.Attendio.Technoflick.Com:443') == 'api.attendio.technoflick.com'
