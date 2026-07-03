from __future__ import annotations
import asyncio
import datetime as _dt
import json
import re
import shlex
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

from kage import privacy as _privacy
from kage import runtime

ARM_KEYWORDS: dict[str, list[str]] = {}

_SHELL_INTERPRETERS = frozenset({
    "bash", "sh", "zsh", "ksh", "fish",
    "python", "python3", "python2",
    "ruby", "perl", "node", "nodejs", "php", "lua",
    "pwsh", "powershell",
})
_arm_tool_cache: dict[str, list] = {}


# DORMANT (Cycle 11) — Google OAuth + remote SSE arm transport. Kept importable &
# test-covered; Workspace Developer Preview rejects Gmail-domain accounts so the SSE
# arms never complete a live call. Flips live when google_oauth.refresh_token exists.
async def _get_google_token() -> str:
    cfg = runtime.config.data
    oauth = cfg.get('google_oauth', {})
    client_id = oauth.get('client_id', '')
    client_secret = oauth.get('client_secret', '')
    refresh_token = oauth.get('refresh_token', '')
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError('google_oauth credentials missing — run: kage arm auth')
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())['access_token']


@asynccontextmanager
async def _connect_arm(arm_name: str):
    arm = runtime.config.data.get('arms', {}).get(arm_name, {})
    transport = arm.get('transport', 'stdio')
    if transport == 'sse':
        # DORMANT — see _get_google_token banner. Inert until a refresh_token exists.
        token = await _get_google_token()
        async with sse_client(url=arm['mcp_url'], headers={'Authorization': f'Bearer {token}'}) as streams:
            yield streams
    else:
        # ponytail: 'browser' transport intentionally falls here — it is stdio on the wire.
        # The 'browser' key selects _call_arm_browser via _TRANSPORT_HANDLERS, not a new
        # wire protocol. Don't add elif transport == 'browser': — it would break this.
        server_params = StdioServerParameters(command=arm['mcp_command'], args=arm.get('mcp_args', []))
        async with stdio_client(server_params) as streams:
            yield streams


def _serialize_arm_result(result) -> str | None:
    if getattr(result, 'isError', False):
        return None
    texts = [block.text for block in result.content if hasattr(block, 'text')]
    return '\n'.join(texts) if texts else None


def _select_tool(arm_name: str, question: str, tools: list) -> tuple[str, dict]:
    preferred = {'calendar': 'list_events', 'gmail': 'search_threads'}
    pref = preferred.get(arm_name)
    for t in tools:
        if t.name == pref:
            return t.name, {'query': question}
    if tools:
        return tools[0].name, {'query': question}
    raise RuntimeError(f'Arm {arm_name!r} has no tools')


async def _call_arm_shell(
    arm_name: str, arm_cfg: dict, _question: str, identity: str, timeout: float,
) -> str | None:
    ts = _dt.datetime.now().astimezone().isoformat(timespec='seconds')
    cmd = arm_cfg.get('command', '')
    if not cmd:
        _privacy._write_audit({'type': 'arm_call', 'arm': arm_name, 'tool': 'shell', 'identity': identity, 'ts': ts, 'success': False})
        return None
    try:
        if shlex.split(cmd)[0].rsplit("/", 1)[-1] in _SHELL_INTERPRETERS:
            _privacy._write_audit({'type': 'arm_call', 'arm': arm_name, 'tool': 'shell', 'identity': identity, 'ts': ts, 'success': False, 'blocked': 'interpreter'})
            return None
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(cmd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        chunks: list[bytes] = []
        assert proc.stdout is not None
        try:
            # ponytail: chunk-read so output already received survives a hang timeout.
            # Ceiling: output must be fully written before timeout fires.
            async with asyncio.timeout(timeout):
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
            await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        stdout = b"".join(chunks)
        data = stdout.decode().strip() if stdout else None
        _privacy._write_audit({'type': 'arm_call', 'arm': arm_name, 'tool': 'shell', 'identity': identity, 'ts': ts, 'success': bool(data)})
        return data
    except Exception:
        _privacy._write_audit({'type': 'arm_call', 'arm': arm_name, 'tool': 'shell', 'identity': identity, 'ts': ts, 'success': False})
        return None


async def _call_arm_mcp(
    arm_name: str, _arm_cfg: dict, question: str, identity: str, timeout: float,
) -> str | None:
    ts = _dt.datetime.now().astimezone().isoformat(timespec='seconds')
    try:
        async with asyncio.timeout(timeout):
            async with _connect_arm(arm_name) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if arm_name not in _arm_tool_cache:
                        tools_result = await session.list_tools()
                        _arm_tool_cache[arm_name] = tools_result.tools
                    tool_name, params = _select_tool(arm_name, question, _arm_tool_cache[arm_name])
                    result = await session.call_tool(tool_name, params)
                    data = _serialize_arm_result(result)
                    _privacy._write_audit({'type': 'arm_call', 'arm': arm_name, 'tool': tool_name, 'identity': identity, 'ts': ts, 'success': data is not None})
                    return data
    except Exception:
        _privacy._write_audit({'type': 'arm_call', 'arm': arm_name, 'tool': 'unknown', 'identity': identity, 'ts': ts, 'success': False})
        return None


async def _call_arm_browser(
    arm_name: str, _arm_cfg: dict, question: str, identity: str, timeout: float,
) -> str | None:
    ts = _dt.datetime.now().astimezone().isoformat(timespec='seconds')
    try:
        async with asyncio.timeout(timeout):
            async with _connect_arm(arm_name) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    m = re.search(r'https?://\S+', question)
                    url = m.group().rstrip('.,;:!?)\\]>') if m else (
                        'https://search.brave.com/search?q='
                        + urllib.parse.quote_plus(question[:300])
                    )
                    nav = await session.call_tool('browser_navigate', {'url': url})
                    if getattr(nav, 'isError', False):
                        _privacy._write_audit({'type': 'arm_call', 'arm': arm_name, 'tool': 'browser_navigate', 'identity': identity, 'ts': ts, 'success': False})
                        return None
                    result = await session.call_tool('browser_snapshot', {})
                    data = _serialize_arm_result(result)
                    _privacy._write_audit({'type': 'arm_call', 'arm': arm_name, 'tool': 'browser_navigate+snapshot', 'identity': identity, 'ts': ts, 'success': data is not None})
                    return data
    except Exception:
        _privacy._write_audit({'type': 'arm_call', 'arm': arm_name, 'tool': 'browser', 'identity': identity, 'ts': ts, 'success': False})
        return None


_TRANSPORT_HANDLERS: dict[str, Callable] = {}


def register_arm(
    name: str,
    keywords: list[str],
    transport: str,
    handler: Callable,
) -> None:
    ARM_KEYWORDS[name] = keywords
    _TRANSPORT_HANDLERS[transport] = handler


register_arm('calendar', ['calendar', 'schedule', 'meeting', 'event', 'appointment', 'today', 'tomorrow', 'this week'], 'shell', _call_arm_shell)
register_arm('gmail', ['email', 'mail', 'inbox', 'thread', 'draft', 'unread', 'reply', 'newsletter', 'attachment'], 'shell', _call_arm_shell)
_TRANSPORT_HANDLERS.setdefault('stdio', _call_arm_mcp)
_TRANSPORT_HANDLERS.setdefault('sse', _call_arm_mcp)

register_arm(
    'browser',
    ['search', 'browse', 'website', 'article', 'web', 'news',
     'look up', 'find online', 'read about'],
    'browser',
    _call_arm_browser,
)


async def _call_arm(arm_name: str, question: str, identity: str, timeout: float = 30.0) -> str | None:
    arm = runtime.config.data.get('arms', {}).get(arm_name, {})
    transport = arm.get('transport', 'stdio')
    handler = _TRANSPORT_HANDLERS.get(transport)
    if handler is None:
        return None
    if transport == 'sse':
        from kage import gate  # B2: sse sends query off-machine; mask before dispatch
        question = gate.two_pass_gate(question, source='sse-arm')[0]
    return await handler(arm_name, arm, question, identity, timeout)


def _detect_arms(question: str, identity: str) -> list[str]:
    arms = runtime.config.data.get('arms', {})
    q = question.lower()
    return [
        name for name, arm in arms.items()
        if arm.get('enabled')
        and isinstance(arm.get('identity'), str)
        and arm['identity'] == identity
        and arm.get('permission') == 'read'
        and any(kw in q for kw in ARM_KEYWORDS.get(name, []))
    ]


def _resolve_repo_root() -> str:
    # Walk up from arms.py: src/kage/arms.py → src/kage → src → repo root
    # config.home is ~/.kage — its parent is ~ (wrong). Use __file__ instead.
    from pathlib import Path
    return str(Path(__file__).resolve().parent.parent.parent)


_INTERNAL_ARMS: dict[str, dict] = {
    "kage-mcp": {
        "transport": "stdio",
        "command": ["uv", "run", "--project", _resolve_repo_root(), "kage", "mcp", "serve"],
        "tools": ["kage_recall", "kage_remember", "kage_ask", "kage_status"],
        "description": "kage's own MCP server — agent-to-agent bus",
    }
}


async def _call_internal_arm(
    arm_name: str, tool_name: str, input: str, timeout: float = 10.0,
) -> dict:
    """Call a tool on a hardcoded internal arm (not user-configured).
    Raises ValueError for unknown arm_name. Returns tool result as dict."""
    arm = _INTERNAL_ARMS.get(arm_name)
    if arm is None:
        raise ValueError(f"Unknown internal arm: {arm_name!r}")
    ts = _dt.datetime.now().astimezone().isoformat(timespec='seconds')
    try:
        async with asyncio.timeout(timeout):
            server_params = StdioServerParameters(
                command=arm["command"][0], args=arm["command"][1:]
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, {"input": input})
                    texts = [block.text for block in result.content if hasattr(block, "text")]
                    data = "\n".join(texts) if texts else ""
                    _privacy._write_audit({
                        "type": "internal_arm_call", "arm": arm_name,
                        "tool": tool_name, "ts": ts, "success": True,
                    })
                    return {"output": data, "arm": arm_name, "tool": tool_name}
    except Exception as e:
        _privacy._write_audit({
            "type": "internal_arm_call", "arm": arm_name,
            "tool": tool_name, "ts": ts, "success": False,
        })
        return {"output": "", "arm": arm_name, "tool": tool_name, "error": str(e)}


async def _check_arm_health(arm_name: str) -> bool:
    arm = runtime.config.data.get('arms', {}).get(arm_name, {})
    if arm.get('transport') == 'shell':
        cmd = arm.get('health_command') or arm.get('command', '')
        if not cmd:
            return False
        try:
            if shlex.split(cmd)[0].rsplit("/", 1)[-1] in _SHELL_INTERPRETERS:
                return False
            proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=10.0)
            return proc.returncode == 0
        except Exception:
            return False
    try:
        async with asyncio.timeout(10.0):
            async with _connect_arm(arm_name) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.list_tools()
        return True
    except Exception:
        return False
