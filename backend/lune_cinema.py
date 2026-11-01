"""Authenticated Luné bridge to the pinned loopback Open Watch Cinema runtime."""
import asyncio
import json
import os
from pathlib import Path
import re
import uuid

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask


PORT = int(os.environ.get('LUNE_CINEMA_PORT', '4182'))
BASE = f'http://127.0.0.1:{PORT}'
DATA = Path(os.environ.get('LUNE_CINEMA_DATA') or Path(os.environ.get('RELAY_DB', 'relay.db')).resolve().parent / 'cinema').resolve()
VIDEO = {'.mp4', '.m4v', '.webm', '.mov', '.mkv'}
MAX_UPLOAD = 12 * 1024 ** 3
CHUNK = 8 * 1024 ** 2
SAFE_PATH = re.compile(r'[A-Za-z0-9/_-]+')


def register(app, relay):
    lock = asyncio.Lock()

    async def cinema(method, path, *, body=None, timeout=30):
        try:
            async with httpx.AsyncClient(base_url=BASE, timeout=timeout, trust_env=False) as client:
                response = await client.request(method, path, json=body)
            return response
        except httpx.HTTPError as exc:
            raise HTTPException(503, '私人影院尚未启动，请检查本机服务与 Node 24') from exc

    @app.get('/lune/cinema/status')
    async def status(request: Request):
        relay['check_auth'](request)
        try:
            response = await cinema('GET', '/api/health', timeout=2)
            response.raise_for_status()
            return {'connected': True, 'cinema': response.json()}
        except (HTTPException, httpx.HTTPError, ValueError):
            return {'connected': False, 'cinema': None}

    @app.api_route('/lune/cinema/api/{path:path}', methods=['GET', 'HEAD', 'POST', 'DELETE'])
    async def proxy(path: str, request: Request):
        relay['check_auth'](request)
        if not path or not SAFE_PATH.fullmatch(path) or '..' in path or not path.startswith(('media', 'rooms', 'jobs', 'observer/', 'health')):
            raise HTTPException(404, '影院路径不存在')
        target = '/api/' + path
        if request.url.query:
            pairs = [(key, value) for key, value in request.query_params.multi_items() if key != 'token']
            if pairs:
                from urllib.parse import urlencode
                target += '?' + urlencode(pairs)
        stream = request.method in {'GET', 'HEAD'} and (path.endswith('/stream') or '/subtitles/' in path or path.endswith('/ai-frame'))
        if stream:
            client = httpx.AsyncClient(base_url=BASE, timeout=httpx.Timeout(30, read=90), trust_env=False)
            try:
                headers = {key: request.headers[key] for key in ('range', 'if-range') if key in request.headers}
                upstream = await client.send(client.build_request(request.method, target, headers=headers), stream=True)
            except httpx.HTTPError as exc:
                await client.aclose()
                raise HTTPException(503, '私人影院尚未启动') from exc
            keep = {k: v for k, v in upstream.headers.items() if k.lower() in {'content-type', 'content-length', 'content-range', 'accept-ranges', 'cache-control', 'x-open-watch-frame-metadata'}}
            keep.update({'x-content-type-options': 'nosniff', 'referrer-policy': 'no-referrer', 'cache-control': 'private, no-store'})
            if request.method == 'HEAD':
                await upstream.aclose()
                await client.aclose()
                return Response(status_code=upstream.status_code, headers=keep)
            async def cleanup():
                await upstream.aclose()
                await client.aclose()
            return StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code, headers=keep, background=BackgroundTask(cleanup))
        body = await request.body() if request.method in {'POST', 'DELETE'} else None
        if body is not None and len(body) > 65536:
            raise HTTPException(413, '影院请求过大')
        try:
            async with httpx.AsyncClient(base_url=BASE, timeout=30, trust_env=False) as client:
                response = await client.request(request.method, target, content=body, headers={'content-type': 'application/json'} if body is not None else None)
            return Response(response.content, status_code=response.status_code, media_type=response.headers.get('content-type', 'application/json'), headers={'cache-control': 'no-store'})
        except httpx.HTTPError as exc:
            raise HTTPException(503, '私人影院尚未启动') from exc

    @app.put('/lune/cinema/uploads/{upload_id}')
    async def upload_chunk(upload_id: uuid.UUID, request: Request):
        relay['check_auth'](request)
        name = request.headers.get('x-cinema-name', '')
        try:
            from urllib.parse import unquote
            name = unquote(name)
            size = int(request.headers.get('x-cinema-size', ''))
            offset = int(request.headers.get('x-cinema-offset', ''))
        except ValueError:
            raise HTTPException(422, '上传参数不正确') from None
        if (name != Path(name).name or '/' in name or '\\' in name or not 1 <= len(name) <= 180
                or Path(name).suffix.lower() not in VIDEO or not 1 <= size <= MAX_UPLOAD or not 0 <= offset < size):
            raise HTTPException(422, '只接受有文件名的本地影片')
        try:
            declared_length = int(request.headers.get('content-length', '0'))
        except ValueError:
            raise HTTPException(422, '分片长度不正确') from None
        if declared_length > CHUNK:
            raise HTTPException(413, '分片超过 8 MB')
        content = await request.body()
        if not content or len(content) > CHUNK or offset + len(content) > size:
            raise HTTPException(413, '分片大小不正确')
        async with lock:
            incoming = DATA / 'media' / '.incoming'
            incoming.mkdir(parents=True, exist_ok=True)
            part, meta = incoming / f'{upload_id}.part', incoming / f'{upload_id}.json'
            info = {'name': name, 'size': size}
            if offset == 0 and not meta.exists():
                with meta.open('x', encoding='utf-8') as file:
                    json.dump(info, file)
            try:
                if json.loads(meta.read_text(encoding='utf-8')) != info or (part.stat().st_size if part.exists() else 0) != offset:
                    raise HTTPException(409, '分片位置或影片信息不一致')
            except (OSError, ValueError) as exc:
                raise HTTPException(409, '上传记录不完整') from exc
            with part.open('ab') as file:
                file.write(content)
            return {'received': part.stat().st_size, 'size': size}

    @app.post('/lune/cinema/uploads/{upload_id}/finish')
    async def finish_upload(upload_id: uuid.UUID, request: Request):
        relay['check_auth'](request)
        async with lock:
            incoming = DATA / 'media' / '.incoming'
            part, meta = incoming / f'{upload_id}.part', incoming / f'{upload_id}.json'
            try:
                info = json.loads(meta.read_text(encoding='utf-8'))
                if part.stat().st_size != info['size']:
                    raise HTTPException(409, '影片仍未上传完毕')
            except (OSError, ValueError, KeyError) as exc:
                raise HTTPException(404, '未找到完整的上传') from exc
            media = DATA / 'media'
            stem, suffix = Path(info['name']).stem, Path(info['name']).suffix
            name = info['name']
            for n in range(1, 1001):
                if not (media / name).exists():
                    break
                name = f'{stem} ({n}){suffix}'
            else:
                raise HTTPException(409, '同名影片过多')
            part.replace(media / name)
            meta.unlink()
        response = await cinema('POST', '/api/media/rescan', body={})
        if response.status_code != 200:
            raise HTTPException(503, '影片已保存；影院扫描暂未完成，请点重新扫描')
        return {'name': name, 'items': response.json()['items']}

    return {'status': status}
