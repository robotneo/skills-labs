from __future__ import absolute_import

import json
import re
import sys

from .cli import CommandError, _json_value, build_commands


PROTOCOL_VERSION = "2024-11-05"
EXPECTED_TOOLS = (
    "notification_status",
    "bind_notification_profile",
    "configure_notification_recipient",
    "deliver_enterprise_report",
    "retry_enterprise_report",
    "continue_enterprise_notification",
)

CAPABILITY_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string", "const": "1"},
        "platform": {
            "type": "string", "enum": ["dingtalk", "feishu", "wecom"],
        },
        "provider": {"type": "string", "const": "native"},
        "operations": {
            "type": "array", "minItems": 1, "uniqueItems": True,
            "items": {
                "type": "string", "enum": [
                    "auth_status", "login", "list_profiles",
                    "resolve_recipient", "send_report", "delivery_status",
                ],
            },
        },
    },
    "required": ["schema_version", "platform", "provider", "operations"],
    "additionalProperties": False,
}
CAPABILITY_BUNDLE_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string", "const": "1"},
        "capabilities": {
            "type": "array", "items": CAPABILITY_SCHEMA,
        },
    },
    "required": ["schema_version", "capabilities"],
    "additionalProperties": False,
}
OPERATION_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string", "const": "1"},
        "action_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
        "report_id": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "platform": {
            "type": "string",
            "enum": ["host", "dingtalk", "feishu", "wecom"],
        },
        "provider": {"type": "string", "minLength": 1},
        "operation": {
            "type": "string", "enum": [
                "auth_status", "login", "list_profiles", "select_profile",
                "resolve_recipient", "confirm_delivery", "send_report",
                "delivery_status", "summarize_report",
            ],
        },
        "status": {
            "type": "string",
            "enum": ["succeeded", "failed", "cancelled", "unavailable"],
        },
        "reason": {"type": "string"},
        "retryable": {"type": "boolean"},
        "data": {"type": "object"},
    },
    "required": [
        "schema_version", "action_id", "report_id", "platform", "provider",
        "operation", "status", "reason", "retryable", "data",
    ],
    "additionalProperties": False,
}

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
            "properties": {
                "platform": {"type": "string", "minLength": 1},
                "capabilities": CAPABILITY_BUNDLE_SCHEMA,
            },
            "required": ["platform"],
            "additionalProperties": False,
        },
    },
    {
        "name": "configure_notification_recipient",
        "description": "Explicitly enable a configured channel and set a fixed recipient for a platform profile.",
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
            "properties": {
                "envelope": {"type": "object"},
                "capabilities": CAPABILITY_BUNDLE_SCHEMA,
                "requestHostSummary": {"type": "boolean"},
            },
            "required": ["envelope"],
            "additionalProperties": False,
        },
    },
    {
        "name": "retry_enterprise_report",
        "description": "Retry the same validated report envelope without redetection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reportId": {
                    "type": "string", "pattern": "^[0-9a-f]{64}$",
                },
                "capabilities": CAPABILITY_BUNDLE_SCHEMA,
            },
            "required": ["reportId"],
            "additionalProperties": False,
        },
    },
    {
        "name": "continue_enterprise_notification",
        "description": "Resume one exactly correlated pending native or host operation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operationResult": OPERATION_RESULT_SCHEMA,
            },
            "required": ["operationResult"],
            "additionalProperties": False,
        },
    },
)
TOOLS_BY_NAME = dict((tool["name"], tool) for tool in TOOLS)


class RpcError(ValueError):
    def __init__(self, code, message):
        ValueError.__init__(self, message)
        self.code = code
        self.message = message


def handle_request(request, commands):
    request_id = request.get("id") if isinstance(request, dict) else None
    is_notification = isinstance(request, dict) and "id" not in request
    if (not isinstance(request, dict) or request.get("jsonrpc") != "2.0"
            or not isinstance(request.get("method"), str)):
        return None if is_notification else _error(
            request_id, -32600, "Invalid Request"
        )

    method = request["method"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        return None if is_notification else _error(
            request_id, -32602, "Invalid params"
        )

    if method == "notifications/initialized":
        return None if is_notification else _result(request_id, {})
    if method == "initialize":
        requested_version = params.get("protocolVersion")
        if requested_version != PROTOCOL_VERSION:
            return None if is_notification else _error(
                request_id, -32602, "Unsupported protocol version"
            )
        response = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "enterprise-notification-bridge", "version": "1.1.0",
            },
        }
        return None if is_notification else _result(request_id, response)
    if method == "tools/list":
        return None if is_notification else _result(
            request_id, {"tools": list(TOOLS)}
        )
    if method == "tools/call":
        try:
            response = _call_tool(params, commands)
        except RpcError as error:
            return None if is_notification else _error(
                request_id, error.code, error.message
            )
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
        except (TypeError, ValueError):
            response = _error(None, -32700, "Parse error")
            error_stream.write("invalid_json\n")
        else:
            try:
                response = handle_request(request, commands)
            except Exception:
                request_id = request.get("id") if isinstance(request, dict) else None
                response = _error(request_id, -32603, "Internal error")
                error_stream.write("internal_error\n")
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
    if (set(params) - set(("name", "arguments")) or not isinstance(name, str)
            or not isinstance(arguments, dict)):
        raise RpcError(-32602, "Invalid tool arguments")
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        raise RpcError(-32602, "Unknown tool")
    _validate_arguments(arguments, tool["inputSchema"])
    try:
        if name == "notification_status":
            result = commands.status()
        elif name == "bind_notification_profile":
            result = commands.bind(
                arguments.get("platform"), arguments.get("capabilities")
            )
        elif name == "configure_notification_recipient":
            result = commands.configure_recipients(
                arguments.get("platform"), [arguments.get("recipient")],
                arguments.get("profile"),
            )
        elif name == "deliver_enterprise_report":
            result = commands.deliver(
                arguments.get("envelope"), arguments.get("capabilities"),
                arguments.get("requestHostSummary", False),
            )
        elif name == "retry_enterprise_report":
            result = commands.retry(
                arguments.get("reportId"), arguments.get("capabilities")
            )
        elif name == "continue_enterprise_notification":
            result = commands.continue_operation(
                arguments.get("operationResult")
            )
    except CommandError as error:
        return _tool_error(error.reason)
    except Exception:
        return _tool_error("internal_error")
    return _tool_result(result)


def _validate_arguments(arguments, schema):
    try:
        _validate_schema(arguments, schema)
    except (TypeError, ValueError):
        raise RpcError(-32602, "Invalid tool arguments")


def _validate_schema(value, schema):
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise ValueError("object required")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if any(name not in value for name in required):
            raise ValueError("required property missing")
        if (schema.get("additionalProperties") is False
                and set(value) - set(properties)):
            raise ValueError("additional property")
        for name, item in value.items():
            _validate_schema(item, properties.get(name, {}))
    elif expected_type == "array":
        if not isinstance(value, list):
            raise ValueError("array required")
        if len(value) < schema.get("minItems", 0):
            raise ValueError("array too short")
        if schema.get("uniqueItems"):
            serialized = [json.dumps(
                item, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ) for item in value]
            if len(serialized) != len(set(serialized)):
                raise ValueError("array items must be unique")
        for item in value:
            _validate_schema(item, schema.get("items", {}))
    elif expected_type == "string":
        if not isinstance(value, str):
            raise ValueError("string required")
        if len(value) < schema.get("minLength", 0):
            raise ValueError("string too short")
        if "pattern" in schema and not re.match(schema["pattern"], value):
            raise ValueError("string pattern mismatch")
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("boolean required")
    if "const" in schema and value != schema["const"]:
        raise ValueError("constant mismatch")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("enumeration mismatch")


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
