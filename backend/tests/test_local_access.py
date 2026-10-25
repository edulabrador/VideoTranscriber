import asyncio
import json
import pytest

from backend.api.local_access import LocalDataAccess


def request(*, peer='127.0.0.1', host='127.0.0.1:8187', origin=None, path='/api/history', method='GET', extra=()):
    messages=[]
    async def app(scope,receive,send):
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{"allowed":true}'})
    async def receive():
        return {'type':'http.request','body':b'','more_body':False}
    async def send(message):messages.append(message)
    headers=[(b'host',host.encode())]+list(extra)
    if origin is not None:
        headers.append((b'origin',origin.encode()))
    scope={'type':'http','method':method,'path':path,'headers':headers,'client':(peer,1234) if peer else None}
    asyncio.run(LocalDataAccess(app)(scope,receive,send))
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


def test_local_development_proxy_preserves_functionality():
 assert request(extra=[(b'x-local-client-address',b'127.0.0.1')])[0]==200


def test_local_origins_work_across_supported_loopback_names():
 assert request(origin='http://localhost:5187',extra=[(b'sec-fetch-site',b'cross-site')])[0]==200
 assert request(origin='http://127.0.0.1:5187')[0]==200


def test_proxy_key_header_grants_nothing_to_remote_peers():
 assert request(peer='172.20.0.5',extra=[(b'x-local-proxy-key',b'synthetic-proxy-fixture-only-0000000000')])[0]==403


def test_denied_message_names_this_application():
 messages=[]
 async def send(message):messages.append(message)
 async def receive():return {'type':'http.request','body':b'','more_body':False}
 scope={'type':'http','method':'GET','path':'/api/history','headers':[(b'host',b'evil.example')],'client':('192.0.2.1',1)}
 asyncio.run(LocalDataAccess(None)(scope,receive,send))
 assert 'VideoTranscriber' in json.loads(messages[1]['body'])['detail']
