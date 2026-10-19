"""Transport-neutral command contracts. Importing them never loads the SDK."""
from dataclasses import dataclass
from importlib import import_module
from .models import OperationError, fail


@dataclass(frozen=True)
class Parameter:
    name: str
    type: str = "string"
    required: bool = False
    default: object = None
    positional: bool = False
    choices: tuple = ()
    minimum: int | None = None
    maximum: int | None = None
    description: str = ""
    item_variants: tuple = ()

    def schema(self):
        value = {"type": self.type, "description": self.description}
        for key in ("default", "minimum", "maximum"):
            if getattr(self, key) is not None:
                value[key] = getattr(self, key)
        if self.choices:
            value["enum"] = list(self.choices)
        if self.item_variants:
            value["minItems"] = 1
            value["items"] = {"oneOf": [Command("", "", "", "", fields).input_schema() for fields in self.item_variants]}
        return value


@dataclass(frozen=True)
class Command:
    path: str
    category: str
    description: str
    handler_ref: str
    parameters: tuple = ()
    one_of: tuple = ()
    privileges: tuple = ()
    risk: str = "read_only"
    asynchronous: bool = False
    compensation: str = "none"
    mcp: bool = True
    provider_kind: str = "vm"

    @property
    def operation_id(self):
        return self.path.replace(" ", ".").replace("-", "_")

    def handler(self):
        module, name = self.handler_ref.split(":")
        return getattr(import_module("vcenter_aiops." + module), name)

    def input_schema(self):
        schema = {"type": "object", "properties": {p.name: p.schema() for p in self.parameters},
                  "required": [p.name for p in self.parameters if p.required], "additionalProperties": False}
        if self.one_of:
            schema["oneOf"] = [{"required": [name]} for name in self.one_of]
        return schema

    def validate(self, values):
        if not isinstance(values, dict) or set(values) - {p.name for p in self.parameters}:
            fail("invalid_arguments", "参数不是对象或包含不支持的参数", 2)
        output = dict(values)
        types = {"string": str, "integer": int, "boolean": bool, "object": dict, "array": list, "number": (int, float)}
        for p in self.parameters:
            if p.name not in output:
                if p.required:
                    fail("invalid_arguments", f"缺少参数 {p.name}", 2)
                if p.default is not None:
                    output[p.name] = p.default
                continue
            value = output[p.name]
            if not isinstance(value, types[p.type]) or (p.type in ("integer", "number") and isinstance(value, bool)):
                fail("invalid_arguments", f"参数 {p.name} 类型错误", 2)
            if p.type == "string" and (not value or "\x00" in value):
                fail("invalid_arguments", f"参数 {p.name} 不能为空或含空字符", 2)
            if p.choices and value not in p.choices:
                fail("invalid_arguments", f"参数 {p.name} 不在允许值中", 2)
            if p.minimum is not None and value < p.minimum or p.maximum is not None and value > p.maximum:
                fail("invalid_arguments", f"参数 {p.name} 超出范围", 2)
            if p.item_variants:
                if not value:
                    fail("invalid_arguments", f"参数 {p.name} 不能为空列表", 2)
                for item in value:
                    matches = 0
                    for fields in p.item_variants:
                        try:
                            Command("", "", "", "", fields).validate(item)
                            matches += 1
                        except OperationError:
                            pass
                    if matches != 1:
                        fail("invalid_arguments", f"参数 {p.name} 的项不符合唯一规格", 2)
        if self.one_of and sum(name in output for name in self.one_of) != 1:
            fail("invalid_arguments", "须且只能提供一个目标选择参数", 2)
        return output

    def describe(self):
        from .risk import risk_level, risk_tags
        sensitive, irreversible = risk_tags(self)
        return {"path": self.path, "operation_id": self.operation_id, "category": self.category,
                "description": self.description, "input_schema": self.input_schema(),
                "result_schema": {"type": "object", "required": ["schema_version", "operation_id", "status", "target", "data", "warnings", "error", "next_action"]},
                "privileges": list(self.privileges), "risk": self.risk,
                "risk_level": risk_level(self),
                "sensitive_categories": list(sensitive),
                "irreversible_categories": list(irreversible),
                "asynchronous": self.asynchronous,
                "compensation": self.compensation, "mcp": self.mcp, "implemented": True,
                "provider_kind": self.provider_kind,
                "idempotency": "request_id_bound_to_target_and_parameters" if self.category == "remote_write" else "not_applicable",
                "timeout_behavior": "reconcile_original_operation" if self.category == "remote_write" else "bounded_error",
                "vsphere": {v: "not_lab_verified" for v in ("6.5", "6.7", "7.0", "8.0")}}
