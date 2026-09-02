from __future__ import absolute_import

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import tempfile
import uuid


class ContinuationError(ValueError):
    pass


SCHEMA_VERSION = "1"
PLATFORMS = frozenset(("dingtalk", "feishu", "wecom"))
NATIVE_OPERATIONS = frozenset((
    "auth_status", "login", "list_profiles", "resolve_recipient",
    "send_report", "delivery_status",
))
HOST_OPERATIONS = frozenset((
    "summarize_report", "select_profile", "confirm_delivery",
    "install_dependency",
))
ALL_OPERATIONS = NATIVE_OPERATIONS | HOST_OPERATIONS
ACTION_KEYS = frozenset((
    "schema_version", "action_id", "report_id", "platform", "provider",
    "operation", "data",
))
RESULT_KEYS = frozenset((
    "schema_version", "action_id", "report_id", "platform", "provider",
    "operation", "status", "reason", "retryable", "data",
))
CONTEXT_KEYS = frozenset((
    "kind", "stage", "channel_index", "recipient_index",
    "resolved_recipients", "claim", "request_host_summary", "platform",
    "provider",
))
CONTEXT_STAGES = ALL_OPERATIONS | frozenset(("auth_recheck",))
HEX_32 = re.compile(r"^[0-9a-f]{32}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def normalize_capabilities(value):
    """Validate the public, versioned host capability bundle."""
    if value is None:
        return []
    if not isinstance(value, dict) or set(value) != set((
            "schema_version", "capabilities")):
        raise ContinuationError("capability bundle fields are invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContinuationError("capability bundle version is unsupported")
    descriptors = value.get("capabilities")
    return validate_capability_list(descriptors)


def validate_capability_list(descriptors):
    if not isinstance(descriptors, list):
        raise ContinuationError("capabilities must be a list")
    normalized = []
    platforms = []
    for descriptor in descriptors:
        if not isinstance(descriptor, dict) or set(descriptor) != set((
                "schema_version", "platform", "provider", "operations")):
            raise ContinuationError("native capability fields are invalid")
        if descriptor.get("schema_version") != SCHEMA_VERSION:
            raise ContinuationError("native capability version is unsupported")
        platform = descriptor.get("platform")
        if platform not in PLATFORMS or descriptor.get("provider") != "native":
            raise ContinuationError("native capability identity is unsupported")
        operations = descriptor.get("operations")
        if (not isinstance(operations, list) or not operations
                or not all(isinstance(item, str) and item in NATIVE_OPERATIONS
                           for item in operations)
                or len(operations) != len(set(operations))):
            raise ContinuationError("native capability operations are invalid")
        platforms.append(platform)
        normalized.append(copy.deepcopy(descriptor))
    if len(platforms) != len(set(platforms)):
        raise ContinuationError("duplicate native capability platform")
    return normalized


def create_action(report_id, platform, provider, operation, data):
    action = {
        "schema_version": SCHEMA_VERSION,
        "action_id": uuid.uuid4().hex,
        "report_id": report_id,
        "platform": platform,
        "provider": provider,
        "operation": operation,
        "data": copy.deepcopy(data),
    }
    validate_action(action)
    return action


def validate_action(value):
    if not isinstance(value, dict) or set(value) != ACTION_KEYS:
        raise ContinuationError("action fields are invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContinuationError("action version is unsupported")
    if not isinstance(value.get("action_id"), str) or not HEX_32.match(value["action_id"]):
        raise ContinuationError("action identifier is invalid")
    if not isinstance(value.get("report_id"), str) or not HEX_64.match(value["report_id"]):
        raise ContinuationError("action report identifier is invalid")
    operation = value.get("operation")
    if operation not in ALL_OPERATIONS:
        raise ContinuationError("action operation is unsupported")
    if operation == "summarize_report":
        if value.get("platform") != "host" or value.get("provider") != "host_agent":
            raise ContinuationError("summary action identity is invalid")
    elif (value.get("platform") not in PLATFORMS
          or not _non_empty_string(value.get("provider"))):
        raise ContinuationError("action provider identity is invalid")
    _validate_action_data(operation, value.get("data"))
    return copy.deepcopy(value)


def validate_operation_result(value, expected_action):
    action = validate_action(expected_action)
    if not isinstance(value, dict) or set(value) != RESULT_KEYS:
        raise ContinuationError("operation result fields are invalid")
    correlation = (
        "schema_version", "action_id", "report_id", "platform", "provider",
        "operation",
    )
    if any(value.get(key) != action.get(key) for key in correlation):
        raise ContinuationError("operation result correlation is invalid")
    status = value.get("status")
    if status not in ("succeeded", "failed", "cancelled", "unavailable"):
        raise ContinuationError("operation result status is invalid")
    if not isinstance(value.get("reason"), str) or not isinstance(value.get("retryable"), bool):
        raise ContinuationError("operation result metadata is invalid")
    data = value.get("data")
    if not isinstance(data, dict):
        raise ContinuationError("operation result data is invalid")
    if status == "succeeded":
        _validate_success_data(action["operation"], data)
    elif data:
        raise ContinuationError("unsuccessful operation result data must be empty")
    return copy.deepcopy(value)


class PendingStateStore(object):
    """Durable sensitive workflow state, separate from the metadata ledger."""

    def __init__(self, directory):
        self.directory = os.path.abspath(directory)
        _ensure_private_directory(self.directory)
        for name in ("pending", "retry", "confirmations"):
            _ensure_private_directory(os.path.join(self.directory, name))

    def save_pending(self, action, envelope, capabilities, context):
        action = validate_action(action)
        capabilities = validate_capability_list(capabilities)
        _validate_context(context)
        _validate_pending_consistency(action, envelope, capabilities, context)
        record = {
            "schema_version": SCHEMA_VERSION,
            "action": action,
            "envelope": copy.deepcopy(envelope),
            "capabilities": capabilities,
            "context": copy.deepcopy(context),
            "created_at": _timestamp(),
        }
        _write_json(self._pending_path(action["action_id"]), record)

    def load_pending(self, action_id):
        if not isinstance(action_id, str) or not HEX_32.match(action_id):
            raise ContinuationError("action identifier is invalid")
        record = _read_json(self._pending_path(action_id))
        if not isinstance(record, dict) or set(record) != set((
                "schema_version", "action", "envelope", "capabilities",
                "context", "created_at")):
            raise ContinuationError("pending state fields are invalid")
        if record.get("schema_version") != SCHEMA_VERSION:
            raise ContinuationError("pending state version is unsupported")
        validate_action(record.get("action"))
        validate_capability_list(record.get("capabilities"))
        _validate_context(record.get("context"))
        _validate_pending_consistency(
            record["action"], record["envelope"], record["capabilities"],
            record["context"],
        )
        return copy.deepcopy(record)

    def delete_pending(self, action_id):
        _unlink(self._pending_path(action_id))

    def save_retry(self, envelope, capabilities, request_host_summary=False):
        capabilities = validate_capability_list(capabilities)
        if not isinstance(envelope, dict):
            raise ContinuationError("retry envelope must be an object")
        report_id = envelope.get("report_id")
        if not isinstance(report_id, str) or not HEX_64.match(report_id):
            raise ContinuationError("retry report identifier is invalid")
        if not isinstance(request_host_summary, bool):
            raise ContinuationError("retry summary flag is invalid")
        record = {
            "schema_version": SCHEMA_VERSION,
            "envelope": copy.deepcopy(envelope),
            "capabilities": capabilities,
            "request_host_summary": request_host_summary,
            "updated_at": _timestamp(),
        }
        _write_json(self._retry_path(report_id), record)

    def load_retry(self, report_id):
        if not isinstance(report_id, str) or not HEX_64.match(report_id):
            raise ContinuationError("retry report identifier is invalid")
        record = _read_json(self._retry_path(report_id))
        if not isinstance(record, dict) or set(record) != set((
                "schema_version", "envelope", "capabilities",
                "request_host_summary", "updated_at")):
            raise ContinuationError("retry state fields are invalid")
        if record.get("schema_version") != SCHEMA_VERSION:
            raise ContinuationError("retry state version is unsupported")
        validate_capability_list(record.get("capabilities"))
        if not isinstance(record.get("request_host_summary"), bool):
            raise ContinuationError("retry summary flag is invalid")
        return copy.deepcopy(record)

    def delete_retry(self, report_id):
        _unlink(self._retry_path(report_id))

    def confirm(self, scope):
        normalized = _normalize_scope(scope)
        record = {
            "schema_version": SCHEMA_VERSION,
            "scope": normalized,
            "confirmed_at": _timestamp(),
        }
        _write_json(self._confirmation_path(normalized), record)

    def is_confirmed(self, scope):
        normalized = _normalize_scope(scope)
        path = self._confirmation_path(normalized)
        if not os.path.exists(path):
            return False
        record = _read_json(path)
        return (isinstance(record, dict)
                and set(record) == set(("schema_version", "scope", "confirmed_at"))
                and record.get("schema_version") == SCHEMA_VERSION
                and record.get("scope") == normalized)

    def pending_actions(self):
        directory = os.path.join(self.directory, "pending")
        actions = []
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".json"):
                continue
            try:
                actions.append(self.load_pending(filename[:-5])["action"])
            except (ContinuationError, IOError, OSError, ValueError):
                continue
        return actions

    def _pending_path(self, action_id):
        return os.path.join(self.directory, "pending", action_id + ".json")

    def _retry_path(self, report_id):
        return os.path.join(self.directory, "retry", report_id + ".json")

    def _confirmation_path(self, scope):
        payload = json.dumps(
            scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        identifier = hashlib.sha256(payload).hexdigest()
        return os.path.join(self.directory, "confirmations", identifier + ".json")


class MemoryStateStore(object):
    """In-memory implementation used only by injected unit-test services."""

    def __init__(self):
        self.pending = {}
        self.retries = {}
        self.confirmations = {}

    def save_pending(self, action, envelope, capabilities, context):
        action = validate_action(action)
        capabilities = validate_capability_list(capabilities)
        _validate_context(context)
        _validate_pending_consistency(action, envelope, capabilities, context)
        self.pending[action["action_id"]] = {
            "schema_version": SCHEMA_VERSION, "action": copy.deepcopy(action),
            "envelope": copy.deepcopy(envelope),
            "capabilities": copy.deepcopy(capabilities),
            "context": copy.deepcopy(context), "created_at": _timestamp(),
        }

    def load_pending(self, action_id):
        try:
            record = copy.deepcopy(self.pending[action_id])
        except KeyError:
            raise ContinuationError("pending action was not found")
        validate_action(record["action"])
        validate_capability_list(record["capabilities"])
        _validate_context(record["context"])
        _validate_pending_consistency(
            record["action"], record["envelope"], record["capabilities"],
            record["context"],
        )
        return record

    def delete_pending(self, action_id):
        self.pending.pop(action_id, None)

    def save_retry(self, envelope, capabilities, request_host_summary=False):
        capabilities = validate_capability_list(capabilities)
        if (not isinstance(envelope, dict)
                or not isinstance(envelope.get("report_id"), str)
                or not HEX_64.match(envelope["report_id"])):
            raise ContinuationError("retry envelope is invalid")
        if not isinstance(request_host_summary, bool):
            raise ContinuationError("retry summary flag is invalid")
        self.retries[envelope["report_id"]] = {
            "schema_version": SCHEMA_VERSION, "envelope": copy.deepcopy(envelope),
            "capabilities": capabilities,
            "request_host_summary": request_host_summary,
            "updated_at": _timestamp(),
        }

    def load_retry(self, report_id):
        try:
            return copy.deepcopy(self.retries[report_id])
        except KeyError:
            raise ContinuationError("retry state was not found")

    def delete_retry(self, report_id):
        self.retries.pop(report_id, None)

    def confirm(self, scope):
        normalized = _normalize_scope(scope)
        self.confirmations[_scope_key(normalized)] = normalized

    def is_confirmed(self, scope):
        normalized = _normalize_scope(scope)
        return self.confirmations.get(_scope_key(normalized)) == normalized

    def pending_actions(self):
        return [copy.deepcopy(item["action"]) for item in self.pending.values()]


def _validate_action_data(operation, data):
    if not isinstance(data, dict):
        raise ContinuationError("action data is invalid")
    if operation == "auth_status":
        if set(data) != set(("profile",)) or (
                data["profile"] is not None and not _non_empty_string(data["profile"])):
            raise ContinuationError("auth_status action data is invalid")
    elif operation in ("login", "list_profiles"):
        if data:
            raise ContinuationError("operation action data must be empty")
    elif operation == "install_dependency":
        if (set(data) != set(("minimum_version", "china_mirror"))
                or not _non_empty_string(data["minimum_version"])
                or not isinstance(data["china_mirror"], bool)):
            raise ContinuationError("dependency install action data is invalid")
    elif operation == "select_profile":
        if set(data) != set(("profiles",)):
            raise ContinuationError("select_profile action data is invalid")
        _validate_profiles(data["profiles"])
    elif operation == "resolve_recipient":
        if (set(data) != set(("profile", "selector"))
                or not _non_empty_string(data["profile"])
                or not _non_empty_string(data["selector"])):
            raise ContinuationError("resolve_recipient action data is invalid")
    elif operation == "confirm_delivery":
        if (set(data) != set(("profile", "recipients"))
                or not _non_empty_string(data["profile"])):
            raise ContinuationError("confirm_delivery action data is invalid")
        _validate_identifiers(data["recipients"], "confirmation recipients")
    elif operation == "send_report":
        if (set(data) != set(("profile", "recipient", "envelope", "claim_id"))
                or not _non_empty_string(data["profile"])
                or not _non_empty_string(data["recipient"])
                or not isinstance(data["envelope"], dict)
                or not _non_empty_string(data["claim_id"])):
            raise ContinuationError("send_report action data is invalid")
    elif operation == "delivery_status":
        if (set(data) != set(("profile", "recipient", "claim_id"))
                or not _non_empty_string(data["profile"])
                or not _non_empty_string(data["recipient"])
                or not _non_empty_string(data["claim_id"])):
            raise ContinuationError("delivery_status action data is invalid")
    elif operation == "summarize_report":
        if set(data) != set(("report_json",)) or not isinstance(data["report_json"], dict):
            raise ContinuationError("summarize_report action data is invalid")


def _validate_success_data(operation, data):
    if operation == "auth_status":
        if (set(data) != set(("authorization",))
                or data["authorization"] not in ("authorized", "missing", "expired")):
            raise ContinuationError("auth_status result data is invalid")
    elif operation == "login":
        if data:
            raise ContinuationError("login result data must be empty")
    elif operation == "list_profiles":
        if set(data) != set(("profiles",)):
            raise ContinuationError("list_profiles result data is invalid")
        _validate_profiles(data["profiles"])
    elif operation == "select_profile":
        if set(data) != set(("profile",)) or not _non_empty_string(data["profile"]):
            raise ContinuationError("select_profile result data is invalid")
    elif operation == "resolve_recipient":
        if set(data) != set(("recipient",)) or not _non_empty_string(data["recipient"]):
            raise ContinuationError("resolve_recipient result data is invalid")
    elif operation == "confirm_delivery":
        if set(data) != set(("confirmed",)) or not isinstance(data["confirmed"], bool):
            raise ContinuationError("confirm_delivery result data is invalid")
    elif operation == "send_report":
        if (set(data) != set(("external_id",))
                or not _non_empty_string(data["external_id"])):
            raise ContinuationError("send_report result data is invalid")
    elif operation == "delivery_status":
        if set(data) != set(("delivery", "external_id")):
            raise ContinuationError("delivery_status result data is invalid")
        if (data["delivery"] not in ("delivered", "not_delivered", "unknown")
                or not isinstance(data["external_id"], str)):
            raise ContinuationError("delivery_status result data is invalid")
        if ((data["delivery"] == "delivered"
             and not _non_empty_string(data["external_id"]))
                or (data["delivery"] != "delivered" and data["external_id"])):
            raise ContinuationError("delivery_status result data is invalid")
    elif operation == "summarize_report":
        if set(data) != set(("text",)) or not _non_empty_string(data["text"]):
            raise ContinuationError("summarize_report result data is invalid")
    elif operation == "install_dependency":
        if data:
            raise ContinuationError("dependency install result data must be empty")


def _validate_profiles(profiles):
    if not isinstance(profiles, list) or not profiles:
        raise ContinuationError("profiles must be a non-empty list")
    identifiers = []
    for profile in profiles:
        if (not isinstance(profile, dict)
                or set(profile) not in (set(("profile",)), set(("profile", "display_name")))
                or not _non_empty_string(profile.get("profile"))):
            raise ContinuationError("profile entry is invalid")
        if "display_name" in profile and not _non_empty_string(profile["display_name"]):
            raise ContinuationError("profile display name is invalid")
        identifiers.append(profile["profile"])
    if len(identifiers) != len(set(identifiers)):
        raise ContinuationError("duplicate profile identifier")


def _validate_context(value):
    if not isinstance(value, dict) or set(value) != CONTEXT_KEYS:
        raise ContinuationError("pending context fields are invalid")
    if value["kind"] not in ("deliver", "bind", "setup") or value["stage"] not in CONTEXT_STAGES:
        raise ContinuationError("pending context stage is invalid")
    if (value["platform"] not in PLATFORMS | frozenset(("host",))
            or not _non_empty_string(value["provider"])):
        raise ContinuationError("pending context provider is invalid")
    if (isinstance(value["channel_index"], bool)
            or not isinstance(value["channel_index"], int)
            or value["channel_index"] < 0
            or isinstance(value["recipient_index"], bool)
            or not isinstance(value["recipient_index"], int)
            or value["recipient_index"] < 0):
        raise ContinuationError("pending context index is invalid")
    if not isinstance(value["resolved_recipients"], list):
        raise ContinuationError("pending context recipients are invalid")
    for recipient in value["resolved_recipients"]:
        if not _non_empty_string(recipient):
            raise ContinuationError("pending context recipient is invalid")
    claim = value["claim"]
    if claim is not None:
        expected = set((
            "report_id", "platform", "provider", "profile", "recipient",
            "claim_id",
        ))
        if not isinstance(claim, dict) or set(claim) != expected:
            raise ContinuationError("pending context claim is invalid")
        if not all(_non_empty_string(item) for item in claim.values()):
            raise ContinuationError("pending context claim is invalid")
    if not isinstance(value["request_host_summary"], bool):
        raise ContinuationError("pending context summary flag is invalid")


def _validate_pending_consistency(action, envelope, capabilities, context):
    if (action["platform"] != context["platform"]
            or action["provider"] != context["provider"]):
        raise ContinuationError("pending provider correlation is invalid")
    if context["kind"] == "deliver":
        if (not isinstance(envelope, dict)
                or envelope.get("report_id") != action["report_id"]):
            raise ContinuationError("pending report correlation is invalid")
    elif envelope is not None:
        raise ContinuationError("binding pending state cannot contain a report")
    if action["operation"] in NATIVE_OPERATIONS and action["provider"] == "native":
        matching = [
            item for item in capabilities
            if item["platform"] == action["platform"]
        ]
        if (len(matching) != 1
                or action["operation"] not in matching[0]["operations"]):
            raise ContinuationError("pending native capability is invalid")
    if action["operation"] == "send_report":
        if action["data"]["envelope"] != envelope:
            raise ContinuationError("pending send envelope is invalid")
        claim = context["claim"]
        if (claim is None
                or claim["claim_id"] != action["data"]["claim_id"]):
            raise ContinuationError("pending send claim is invalid")
    if action["operation"] == "delivery_status":
        claim = context["claim"]
        if (claim is None
                or claim["claim_id"] != action["data"]["claim_id"]):
            raise ContinuationError("pending status claim is invalid")


def _normalize_scope(scope):
    expected = set(("platform", "provider", "profile", "recipients"))
    if not isinstance(scope, dict) or set(scope) != expected:
        raise ContinuationError("confirmation scope fields are invalid")
    if (scope["platform"] not in PLATFORMS
            or not _non_empty_string(scope["provider"])
            or not _non_empty_string(scope["profile"])):
        raise ContinuationError("confirmation scope identity is invalid")
    _validate_identifiers(scope["recipients"], "confirmation recipients")
    return {
        "platform": scope["platform"], "provider": scope["provider"],
        "profile": scope["profile"],
        "recipients": sorted(scope["recipients"]),
    }


def _validate_identifiers(values, label):
    if (not isinstance(values, list) or not values
            or not all(_non_empty_string(item) for item in values)
            or len(values) != len(set(values))):
        raise ContinuationError("{0} are invalid".format(label))


def _scope_key(scope):
    return json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _non_empty_string(value):
    return (isinstance(value, str) and bool(value.strip())
            and not any(ord(character) < 32 for character in value))


def _ensure_private_directory(path):
    if not os.path.exists(path):
        os.makedirs(path, mode=0o700)
    _chmod(path, 0o700)


def _write_json(path, value):
    directory = os.path.dirname(path)
    _ensure_private_directory(directory)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".state-", dir=directory)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                value, handle, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
        replace = getattr(os, "replace", os.rename)
        replace(temporary_path, path)
        _chmod(path, 0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        _unlink(temporary_path)
        raise


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (IOError, OSError, TypeError, ValueError) as error:
        raise ContinuationError("state could not be loaded") from error


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _chmod(path, mode):
    try:
        os.chmod(path, mode)
    except (AttributeError, OSError):
        pass


def _timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
