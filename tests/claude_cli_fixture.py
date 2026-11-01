"""Synthetic CLI protocol fixture. Never calls Anthropic or any account."""
import json
import os
from pathlib import Path
import sys
import uuid

assert 'ANTHROPIC_API_KEY' not in os.environ
assert 'OPENAI_API_KEY' not in os.environ
if sys.argv[1:] == ['auth', 'status']:
    print(json.dumps({'authMethod': 'claude.ai', 'loggedIn': True}))
    raise SystemExit()
assert '--tools' in sys.argv and sys.argv[sys.argv.index('--tools') + 1] == ''
assert '--strict-mcp-config' in sys.argv
assert '--dangerously-skip-permissions' not in sys.argv

def emit(value):
    print(json.dumps(value), flush=True)

if 'json' in sys.argv and 'stream-json' not in sys.argv:
    raw = sys.stdin.read()
    emit({'type': 'result', 'subtype': 'success', 'result': 'SYNTHETIC_BACKGROUND_DIARY', 'usage': {'input_tokens': 10}})
    raise SystemExit()

sid = sys.argv[sys.argv.index('--resume') + 1] if '--resume' in sys.argv else str(uuid.uuid4())
emit({'type': 'system', 'subtype': 'init', 'session_id': sid})
for i, line in enumerate(sys.stdin):
    row = json.loads(line)
    if os.environ.get('LUNE_TEST_CLI_FRAMES'):
        with open(os.environ['LUNE_TEST_CLI_FRAMES'],'a') as frame_log:frame_log.write(line)
    if 'COMPACT_CLI_TRIGGER' in line:
        emit({'type':'system','subtype':'compact_boundary'})
    if 'FAIL_CLI_TRIGGER' in line:
        emit({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True})
        continue
    emit({'type': 'stream_event', 'event': {'delta': {'type': 'text_delta', 'text': 'FIXTURE_CLAUDE_REPLY'}}})
    emit({'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': 'opaque-fixture-not-displayed', 'signature': 'opaque-signature'}], 'usage': {'input_tokens': 100 + i, 'cache_read_input_tokens': 50}}})
    emit({'type': 'result', 'subtype': 'success', 'session_id': sid, 'result': 'FIXTURE_CLAUDE_REPLY', 'usage': {'input_tokens': 100 + i}})
