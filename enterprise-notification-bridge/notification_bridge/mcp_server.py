from __future__ import absolute_import

import json
import sys

from .cli import CommandError, _json_value, build_commands


PROTOCOL_VERSION = "2024-11-05"
EXPECTED_TOOLS = (
    "notification_status",
    "bind_notification_profile",
    "configure_notification_recipient",
    "deliver_enterprise_report",
    "retry_enterprise_report",
)

TOOLS = (
    {
        "name": "notification_status",
        "description": "Show notification Bridge configuration status.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "bind_notification_profile",
        "description": "Discover and bind a stable platform profile.",
        "inputSchema": {
            "type": "object",
            "properties": {"platform": {"type": "string", "minLength": 1}},
            "required": ["platform"],
            "additionalProperties": False,
        },
    },
    {
        "name": "configure_notification_recipient",
        "description": "Configure a fixed recipient for a platform profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "minLength": 1},
                "profile": {"type": "string", "minLength": 1},
                "recipient": {"type": "string", "minLength": 1},
            },
            "required": ["platform", "recipient"],
            "additionalProperties": False,
        },
    },
    {
        "name": "deliver_enterprise_report",
        "description": "Deliver a validated enterprise report envelope.",
        "inputSchema": {
            "type": "object",
            "properties": {"envelope": {"type": "object"}},
            "required": ["envelope"],
            "additionalProperties": False,
        },
    },
    {
        "name": "retry_enterprise_report",
        "description": "Retry the same validated report envelope without redetection.",
        "inputSchema": {
            "type": "object",
            "properties": {"envelope": {"type": "object"}},
            "required": ["envelope"],
            "additionalProperties": False,
        },
    },
)


def handle_request(request, commands):
    request_id = request.get("id") if isinstance(request, dict) else None
    if (not isinstance(request, dict) or request.get("jsonrpc") != "2.0"
            or not isinstance(request.get("method"), str)):
        return _error(request_id, -32600, "Invalid Request")

    method = request["method"]
    params = request.get("params", {})
    is_notification = "id" not in request
    if not isinstance(params, dict):
        return _error(request_id, -32602, "Invalid params")

    if method == "notifications/initialized":
        return None if is_notification else _result(request_id, {})
    if method == "initialize":
        requested_version = params.get("protocolVersion")
        protocol_version = (requested_version if isinstance(requested_version, str)
                            else PROTOCOL_VERSION)
        response = {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "enterprise-notification-bridge", "version": "1.0.0",
            },
        }
        return None if is_notification else _result(request_id, response)
    if method == "tools/list":
        return None if is_notification else _result(
            request_id, {"tools": list(TOOLS)}
        )
    if method == "tools/call":
        response = _call_tool(params, commands)
        return None if is_notification else _result(request_id, response)
    if is_notification:
        return None
    return _error(request_id, -32601, "Method not found")


def serve(commands=None, input_stream=None, output_stream=None,
          error_stream=None):
    commands = commands or build_commands()
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    error_stream = error_stream or sys.stderr

    for line in input_stream:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except (TypeError, ValueError) as error:
            response = _error(None, -32700, "Parse error")
            error_stream.write("invalid JSON-RPC: {0}\n".format(error))
        else:
            try:
                response = handle_request(request, commands)
            except Exception as error:
                request_id = request.get("id") if isinstance(request, dict) else None
                response = _error(request_id, -32603, "Internal error")
                error_stream.write("internal JSON-RPC error: {0}\n".format(error))
        if response is not None:
            output_stream.write(json.dumps(
                _json_value(response), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ))
            output_stream.write("\n")
            output_stream.flush()
    return 0


def main():
    return serve()


def _call_tool(params, commands):
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return _tool_error("invalid_arguments")
    try:
        if name == "notification_status":
            result = commands.status()
        elif name == "bind_notification_profile":
            result = commands.bind(arguments.get("platform"))
        elif name == "configure_notification_recipient":
            result = commands.configure_recipients(
                arguments.get("platform"), [arguments.get("recipient")],
                arguments.get("profile"),
            )
        elif name == "deliver_enterprise_report":
            result = commands.deliver(arguments.get("envelope"))
        elif name == "retry_enterprise_report":
            result = commands.retry(arguments.get("envelope"))
        else:
            return _tool_error("tool_not_found")
    except CommandError as error:
        return _tool_error(error.reason)
    except Exception:
        return _tool_error("internal_error")
    return _tool_result(result)


def _tool_result(value):
    value = _json_value(value)
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        }],
        "structuredContent": value,
        "isError": False,
    }


def _tool_error(reason):
    value = {"status": "error", "reason": reason}
    result = _tool_result(value)
    result["isError"] = True
    return result


def _result(request_id, value):
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(request_id, code, message):
    return {
        "jsonrpc": "2.0", "id": request_id,
        "error": {"code": code, "message": message},
    }


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
