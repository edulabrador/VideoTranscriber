import asyncio
import json
import pytest

from backend.api.local_access import LocalDataAccess


def request(*, peer='127.0.0.1', host='127.0.0.1:8187', origin=None, path='/api/history', method='GET', extra=(), riders=False, proxy_key_file=None):
    messages=[]
    async def app(scope,receive,send):
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{"allowed":true}'})
    async def receive():
        return {'type':'http.request','body':b'','more_body':False}
    async def send(message):messages.append(message)
    headers=[(b'host',host.encode())]+list(extra)
    if origin is not None:headers.append((b'origin',origin.encode()))
    scope={'type':'http','method':method,'path':path,'headers':headers,'client':(peer,1234) if peer else None}
    asyncio.run(LocalDataAccess(app,rider_views=riders,proxy_key_file=proxy_key_file)(scope,receive,send))
    return messages[0]['status'],dict(messages[0].get('headers',[]))


@pytest.mark.parametrize('peer,host,origin',[
 ('127.0.0.1','127.0.0.1:8187',None),('127.0.0.1','localhost:8187','http://localhost:5187'),
 ('::1','[::1]:8187','http://[::1]:5187'),('::ffff:127.0.0.1','localhost:8187',None),
])
def test_local_owner_keeps_access(peer,host,origin):
 status,headers=request(peer=peer,host=host,origin=origin)
 assert status==200 and headers[b'referrer-policy']==b'no-referrer'


@pytest.mark.parametrize('options',[
 {'peer':'192.0.2.12'},{'peer':None},{'host':'evil.example:8187'},{'origin':'https://evil.example'},
 {'origin':'null'},{'origin':'http://localhost/path'},{'origin':'http://localhost@evil.example'},
 {'host':'localhost:bad-port'}, {'extra':[(b'x-forwarded-for',b'127.0.0.1')]},
 {'extra':[(b'forwarded',b'for=127.0.0.1')]},{'extra':[(b'x-real-ip',b'127.0.0.1')]},
 {'extra':[(b'x-local-client-address',b'192.0.2.12')]},
 {'extra':[(b'host',b'evil.example')]},{'extra':[(b'sec-fetch-site',b'cross-site')]},
])
def test_untrusted_requests_cannot_read_owner_data(options):
 status,headers=request(**options)
 assert status==403 and headers[b'cache-control']==b'no-store'


def test_links_to_local_home_page_still_open():
 assert request(path='/',extra=[(b'sec-fetch-site',b'cross-site')])[0]==200


@pytest.mark.parametrize('path,method',[
 ('/r/abcdefghijklmnop1234','GET'),('/assets/app.js','GET'),
 ('/api/rider-view/abcdefghijklmnop1234','GET'),('/api/rider-view/abcdefghijklmnop1234/outcome','POST'),
])
def test_rider_requests_reach_existing_token_validation(path,method):
 assert request(peer='192.0.2.12',host='delivery.example',origin='https://delivery.example',path=path,method=method,riders=True)[0]==200
 assert request(peer='192.0.2.12',host='delivery.example',path=path,method=method,riders=False)[0]==403


@pytest.mark.parametrize('path',[
 '/api/orders','/api/plans','/api/rider-view/abcdefghijklmnop1234/plans',
 '/api/rider-view/abcdefghijklmnop1234/../../orders','/api/rider-view/short',
])
def test_rider_exceptions_never_open_owner_endpoints(path):
 assert request(peer='192.0.2.12',host='delivery.example',path=path,riders=True)[0]==403


def test_rider_cross_site_writes_are_denied():
 assert request(peer='192.0.2.12',host='delivery.example',origin='https://evil.example',path='/api/rider-view/abcdefghijklmnop1234/outcome',method='POST',riders=True)[0]==403


def test_local_development_proxy_preserves_functionality():
 assert request(extra=[(b'x-local-client-address',b'127.0.0.1')])[0]==200


@pytest.mark.parametrize('peer', ['127.0.0.1', '172.20.0.5'])
def test_authenticated_local_container_proxy(tmp_path, peer):
 key_file=tmp_path/'local-proxy-key'
 key=b'synthetic-proxy-fixture-only-0000000000'
 key_file.write_bytes(key+b'\n')
 assert request(peer=peer, proxy_key_file=str(key_file), extra=[(b'x-local-proxy-key',key)])[0]==200
 assert request(peer=peer, proxy_key_file=str(key_file), extra=[(b'x-local-proxy-key',b'wrong')])[0]==403
 assert request(peer=peer, proxy_key_file=str(key_file), extra=[(b'x-local-proxy-key',key),(b'x-local-proxy-key',key)])[0]==403
 assert request(peer=peer, host='evil.example', proxy_key_file=str(key_file), extra=[(b'x-local-proxy-key',key)])[0]==403
 assert request(peer=peer, origin='https://evil.example', proxy_key_file=str(key_file), extra=[(b'x-local-proxy-key',key)])[0]==403
 assert request(peer=peer, proxy_key_file=str(key_file), extra=[(b'x-local-proxy-key',key),(b'x-local-client-address',b'192.0.2.12')])[0]==403
 assert request(peer=peer, proxy_key_file=str(key_file))[0]==(200 if peer=='127.0.0.1' else 403)


def test_proxy_key_requires_explicit_local_configuration(tmp_path):
 assert request(extra=[(b'x-local-proxy-key',b'synthetic-proxy-fixture-only-0000000000')])[0]==403
 short=tmp_path/'short-key';short.write_text('short')
 with pytest.raises(ValueError,match='local proxy key'):
  LocalDataAccess(None,proxy_key_file=str(short))
 with pytest.raises(OSError):
  LocalDataAccess(None,proxy_key_file=str(tmp_path/'missing-key'))


def test_trusted_local_origins_work_across_supported_loopback_names():
 assert request(origin='http://localhost:5187',extra=[(b'sec-fetch-site',b'cross-site')])[0]==200
 assert request(origin='http://localhost:5187',path='/api/rider-view/abcdefghijklmnop1234/outcome',method='POST',riders=True)[0]==200
 assert request(peer='192.0.2.12',host='delivery.example',origin='http://localhost:5187',path='/api/rider-view/abcdefghijklmnop1234/outcome',method='POST',riders=True)[0]==403
