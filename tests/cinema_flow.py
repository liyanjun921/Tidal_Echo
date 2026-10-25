"""HTTP integration against a running pinned cinema and a synthetic local film."""
import asyncio
import atexit
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix='lune-cinema-test-')
data_root = Path(temporary.name)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0))
    os.environ['LUNE_CINEMA_PORT'] = str(sock.getsockname()[1])
os.environ['LUNE_CINEMA_DATA'] = str(data_root)
os.environ['RELAY_SECRET'] = 'fixture-owner-secret'
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12:duration=3',
    '-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',
    '-y',str(data_root/'fixture.mp4')],check=True)
service = subprocess.Popen(['node',str(ROOT/'backend/vendor/open_watch_cinema/server.mjs')],
    env={**os.environ,'PORT':os.environ['LUNE_CINEMA_PORT'],'LOCAL_DATA_ROOT':str(data_root),'OPEN_BROWSER':'0'},
    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
def cleanup():
    service.terminate()
    try:service.wait(timeout=5)
    except subprocess.TimeoutExpired:service.kill();service.wait()
    service.stderr.close()
    temporary.cleanup()
atexit.register(cleanup)
import httpx
for _ in range(60):
    try:
        if httpx.get('http://127.0.0.1:'+os.environ['LUNE_CINEMA_PORT']+'/api/health',trust_env=False).status_code==200:break
    except httpx.HTTPError:pass
    time.sleep(.1)
else:raise AssertionError('cinema service did not start: '+service.stderr.read().decode())

from backend.lune_cinema import register as register_cinema
from backend.lune_cinema_companion import register as register_guests


def auth(request):
    if request.headers.get('authorization') != 'Bearer fixture-owner-secret':
        raise HTTPException(401, 'unauthorized')


db = str(data_root/'relay-test.sqlite')
app = FastAPI()
register_cinema(app, {'DB_PATH':db,'check_auth':auth})
runtime = register_guests(app, {'DB_PATH':db,'check_auth':auth})
runtime['init']()
client = TestClient(app)
headers = {'Authorization':'Bearer fixture-owner-secret'}
source = (data_root/'fixture.mp4').read_bytes()

assert client.get('/lune/cinema/status').status_code == 401
assert client.get('/lune/cinema/status',headers=headers).json()['connected']
upload = str(uuid.uuid4())
response = client.put('/lune/cinema/uploads/'+upload,headers={**headers,'x-cinema-name':'fixture.mp4','x-cinema-size':str(len(source)),'x-cinema-offset':'0'},content=source)
assert response.status_code == 200, response.text
assert response.json()['received'] == len(source)
assert client.put('/lune/cinema/uploads/'+upload,headers={**headers,'x-cinema-name':'fixture.mp4','x-cinema-size':str(len(source)),'x-cinema-offset':'0'},content=source).status_code == 409
finished = client.post('/lune/cinema/uploads/'+upload+'/finish',headers=headers)
assert finished.status_code == 200, finished.text
item = next(x for x in finished.json()['items'] if x['title'].startswith('fixture'))
assert client.get('/lune/cinema/api/media/'+item['id']+'/stream',headers={'Range':'bytes=0-99'}).status_code == 401
stream = client.get('/lune/cinema/api/media/'+item['id']+'/stream',headers={**headers,'Range':'bytes=0-99'})
assert stream.status_code == 206 and stream.content == source[:100] and stream.headers['content-range'].startswith('bytes 0-99/')
room = client.post('/lune/cinema/api/rooms/open',headers=headers,json={'mediaId':item['id']}).json()['room']
rid = room['id']
nonce = str(uuid.uuid4())
body = {'senderName':'我','senderKind':'user','content':'这一幕怎么样？','mediaTimeMs':500,'nonce':nonce}
first = client.post('/lune/cinema/api/rooms/'+rid+'/messages',headers=headers,json=body)
again = client.post('/lune/cinema/api/rooms/'+rid+'/messages',headers=headers,json=body)
assert first.status_code == 201 and again.status_code == 201 and first.json()['message']['id'] == again.json()['message']['id']
assert client.post('/lune/cinema/guests',headers=headers,json={'room_id':rid,'agents':['gpt']}).status_code == 409
prepare = client.post('/lune/cinema/api/media/'+item['id']+'/prepare-ai',headers=headers,json={})
assert prepare.status_code == 202, prepare.text
job = prepare.json()['job']['id']
for _ in range(60):
    state = client.get('/lune/cinema/api/jobs/'+job,headers=headers).json()['job']
    if state['status'] in {'done','error'}: break
    time.sleep(.25)
assert state['status'] == 'done', state
client.post('/lune/cinema/api/media/rescan',headers=headers,json={})
enabled = client.post('/lune/cinema/guests',headers=headers,json={'room_id':rid,'agents':['gpt']})
assert enabled.status_code == 200, enabled.text
client.post('/lune/cinema/api/rooms/'+rid+'/messages',headers=headers,json={'senderName':'我','senderKind':'user','content':'现在这段呢？','mediaTimeMs':1000})
client.post('/lune/cinema/api/rooms/'+rid+'/playback',headers=headers,json={'mediaTimeMs':1500,'playbackState':'playing'})
calls=[]
async def model(agent,prompt,frames):
    calls.append((agent,prompt,frames))
    return {'text':'{"action":"say","text":"这段转场很有趣。"}'}
asyncio.run(runtime['tick'](generate_fn=model))
messages = client.get('/lune/cinema/api/rooms/'+rid+'/messages',headers=headers).json()['messages']
assert len([m for m in messages if m['senderKind']=='ai']) == 1 and calls and calls[0][0]=='gpt', (messages,calls)
asyncio.run(runtime['tick'](generate_fn=model))
messages = client.get('/lune/cinema/api/rooms/'+rid+'/messages',headers=headers).json()['messages']
assert len([m for m in messages if m['senderKind']=='ai']) == 1
client.post('/lune/cinema/api/rooms/'+rid+'/end',headers=headers,json={'mediaTimeMs':1500})
assert client.post('/lune/cinema/api/rooms/'+rid+'/messages',headers=headers,json=body).status_code == 409
print('Cinema HTTP PASS: authenticated upload/range, room/idempotency, AI preparation, guest tick and read-only archive')
