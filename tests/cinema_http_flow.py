"""Real supervisor -> authenticated cinema -> prepared film -> actual fixture model."""
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import httpx

with tempfile.TemporaryDirectory() as tmp:
    film=Path(tmp)/'cinema-e2e.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12:duration=3',
      '-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-y',str(film)],check=True)
    source=film.read_bytes()
    base='http://127.0.0.1:8089/relay/lune/cinema'
    with httpx.Client(headers={'Authorization':'Bearer fixture-owner-secret'},trust_env=False,timeout=30) as client:
        for _ in range(40):
            if client.get(base+'/status').json()['connected']:break
            time.sleep(.25)
        else:raise AssertionError('cinema runtime unavailable')
        uid=str(uuid.uuid4())
        r=client.put(base+'/uploads/'+uid,content=source,headers={'x-cinema-name':film.name,'x-cinema-size':str(len(source)),'x-cinema-offset':'0'});r.raise_for_status()
        r=client.post(base+'/uploads/'+uid+'/finish');r.raise_for_status()
        item=next(m for m in r.json()['items'] if m['title']=='cinema e2e')
        media_id=item['id']
        r=client.get(base+f'/api/media/{media_id}/stream',headers={'Range':'bytes=0-99'})
        assert r.status_code==206 and r.content==source[:100]
        r=client.post(base+'/api/rooms/open',json={'mediaId':media_id});r.raise_for_status();rid=r.json()['room']['id']
        r=client.post(base+f'/api/media/{media_id}/prepare-ai',json={});r.raise_for_status();job=r.json()['job']['id']
        for _ in range(80):
            state=client.get(base+'/api/jobs/'+job).json()['job']
            if state['status'] in {'done','error'}:break
            time.sleep(.25)
        assert state['status']=='done',state
        client.post(base+'/api/media/rescan',json={}).raise_for_status()
        r=client.post(base+'/guests',json={'room_id':rid,'agents':['gpt']});r.raise_for_status()
        client.post(base+f'/api/rooms/{rid}/messages',json={'senderName':'我','content':'这个开场怎么样？','senderKind':'user','mediaTimeMs':1000}).raise_for_status()
        client.post(base+f'/api/rooms/{rid}/playback',json={'mediaTimeMs':1500,'playbackState':'playing'}).raise_for_status()
        for _ in range(65):
            rows=client.get(base+f'/api/rooms/{rid}/messages').json()['messages']
            if any(m['senderKind']=='ai' for m in rows):break
            time.sleep(.5)
        delivered=[m for m in rows if m['senderKind']=='ai' and 'CINEMA_GUEST_DELIVERED' in m['content']]
        assert len(delivered)==1,rows
        client.post(base+f'/api/rooms/{rid}/end',json={'mediaTimeMs':1500}).raise_for_status()
        assert client.post(base+f'/api/rooms/{rid}/messages',json={'senderName':'我','content':'结束了','mediaTimeMs':1500}).status_code==409
        print('Cinema supervisor HTTP PASS: upload, Range, visual package, GPT model tick, one room message, archive')
