"""One serialized native worker per application event loop, stopped on shutdown."""
import asyncio
import json
from pathlib import Path
import sys
import weakref

_workers = weakref.WeakKeyDictionary()


class NativeWorker:
    def __init__(self, source, env):
        self.source, self.env, self.process = source, env, None
        self.lock = asyncio.Lock()

    async def close(self):
        process = self.process
        self.process = None
        if process is not None:
            if process.returncode is None:
                process.kill()
            # Reap the process and drain/close its pipes before the owning loop exits.
            await process.communicate()

    async def call(self, payload):
        async with self.lock:
            if self.process is None or self.process.returncode is not None:
                self.process = await asyncio.create_subprocess_exec(sys.executable, "-I", "-B",
                    str(Path(__file__).with_name("latent_worker.py")), str(self.source), "--serve",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, env=self.env, limit=4 * 1024 * 1024)
            try:
                self.process.stdin.write(json.dumps(payload, ensure_ascii=False).encode() + b"\n")
                await self.process.stdin.drain()
                line = await asyncio.wait_for(self.process.stdout.readline(), timeout=30)
                value = json.loads(line)
                if "error" in value:
                    raise RuntimeError("native_worker_failed")
                return value
            except BaseException:
                await self.close()
                raise


async def call_native(source, env, payload):
    loop = asyncio.get_running_loop()
    source = str(source)
    worker = _workers.get(loop)
    if worker is None or worker.source != source:
        if worker:
            await worker.close()
        worker = NativeWorker(source, env)
        _workers[loop] = worker
    return await worker.call(payload)


async def close_native():
    worker = _workers.pop(asyncio.get_running_loop(), None)
    if worker:
        await worker.close()
