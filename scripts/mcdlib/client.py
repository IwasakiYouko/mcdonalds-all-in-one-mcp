"""Streamable HTTP MCP client with explicit no-retry behavior."""
import json
import re
import urllib.error
import urllib.request
from .storage import token

ENDPOINT = "https://mcp.mcd.cn"


class MCPError(RuntimeError):
    pass


def decode_message(raw, request_id):
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and obj.get("id") == request_id:
            return obj
    except json.JSONDecodeError:
        pass
    # SSE events may contain pretty-printed JSON across multiple data lines.
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip(" ") for line in block.splitlines() if line.startswith("data:"))
        if data:
            try:
                obj = json.loads(data)
                if isinstance(obj, dict) and obj.get("id") == request_id:
                    return obj
            except json.JSONDecodeError:
                continue
    raise MCPError("No matching JSON-RPC response; request was not retried")


def payload(result):
    """Extract a tool's structured result without discarding raw content."""
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    texts = [b.get("text", "") for b in result.get("content", []) if b.get("type") == "text"]
    for text in texts:
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            pass
    return {"text": "\n".join(texts)}


def assert_success(result):
    if result.get("isError"):
        raise MCPError("Tool reported an error; inspect the private response record")
    body = payload(result)
    if isinstance(body, dict):
        if body.get("success") is False or body.get("code") in (400, 401, 403, 429, 500, "400", "401", "403", "429", "500"):
            raise MCPError("Business request failed; inspect the private response record")
        status = body.get("status")
        if isinstance(status, dict) and status.get("code") not in (None, "SUCCESS", "200", 200):
            raise MCPError("Business status is not successful; inspect the private response record")
    return body


class Client:
    def __init__(self):
        self.secret = token()
        self.headers = {"Authorization": "Bearer " + self.secret, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self.counter = 0
        self.connected = False
        self.inventory = None
        self.server_info = {}

    def scrub(self, value):
        text = str(value).replace(self.secret, "[REDACTED]")
        return re.sub(r"Bearer\s+[^\s\"']+", "Bearer [REDACTED]", text)

    def request(self, method, params=None, notification=False):
        self.counter += 1
        request_id = self.counter
        data = {"jsonrpc": "2.0", "method": method}
        if not notification:
            data["id"] = request_id
        if params is not None:
            data["params"] = params
        req = urllib.request.Request(ENDPOINT, data=json.dumps(data, allow_nan=False).encode(), headers=self.headers, method="POST")
        # A redirect must never forward the bearer credential to another host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=40) as resp:
                session = resp.headers.get("Mcp-Session-Id")
                if session:
                    self.headers["Mcp-Session-Id"] = session
                raw = resp.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise MCPError("Response exceeds 8 MiB; stopped without retry")
                raw = raw.decode("utf-8")
        except urllib.error.HTTPError as e:
            raise MCPError(f"HTTP {e.code}; request was not retried. Check credentials (401), quota (429), or service status.") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise MCPError(self.scrub(f"Network request failed ({type(e).__name__}); outcome may be unknown. No automatic retry.")) from None
        if notification:
            return {}
        message = decode_message(raw, request_id)
        if "error" in message:
            raise MCPError(self.scrub("MCP error: " + json.dumps(message["error"], ensure_ascii=False)))
        return message.get("result", {})

    def connect(self):
        if self.connected:
            return
        result = self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "mcdonalds-all-in-one-mcp", "version": "1.0.0"}})
        self.headers["MCP-Protocol-Version"] = result.get("protocolVersion", "2024-11-05")
        self.server_info = result.get("serverInfo", {})
        self.request("notifications/initialized", notification=True)
        self.connected = True

    def tools(self):
        if self.inventory is not None:
            return self.inventory
        self.connect()
        tools = []
        cursor = None
        seen = set()
        for _ in range(20):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                self.inventory = {t["name"]: t for t in tools}
                return self.inventory
            if cursor in seen:
                break
            seen.add(cursor)
        raise MCPError("Tool pagination did not terminate")

    def call(self, name, arguments):
        from .catalog import validate
        tools = self.tools()
        if name not in tools:
            raise ValueError(f"Tool is not exposed by the server: {name}")
        validate(arguments, tools[name].get("inputSchema", {}))
        return self.request("tools/call", {"name": name, "arguments": arguments})
