"""Route JSON provider contracts using trusted command registry metadata only."""
from ..domain.models import fail
from .registry import lookup


class ProviderRouter:
    def __init__(self, si, providers=None, tls=None):
        # Injected instances are a controlled composition boundary, never plan data.
        # ``tls`` is client connection config (verify_tls/ca_file), never persisted.
        self._tls = tls or {}
        if providers is None:
            from ..providers.vsphere.mutations import Mutations
            # Only Mutations is eager; guest/ovf/creation/etc lazily construct
            # their SDK boundary on first use so unrelated writes (and offline
            # CLI tests with a stubbed session) never touch those providers.
            providers = {"vm": Mutations(si)}
            self._default_si = si
        else:
            self._default_si = None
        self.providers = dict(providers)

    def configure_evidence(self, store, profile):
        # Every Engine entry point receives the same trusted local record resolver.
        vm = self.providers.get("vm")
        if vm is not None and hasattr(vm, "configure_evidence"):
            vm.configure_evidence(store, profile)

    def _provider(self, kind):
        if kind == "guest" and self._default_si is not None and kind not in self.providers:
            from ..providers.vsphere.guest import Guest
            self.providers[kind] = Guest(self._default_si, tls=self._tls)
        if kind == "creation" and self._default_si is not None and kind not in self.providers:
            from ..providers.vsphere.creation import Creation
            self.providers[kind] = Creation(self._default_si)
        if kind == "membership" and self._default_si is not None and kind not in self.providers:
            from ..providers.vsphere.membership import Membership
            self.providers[kind] = Membership(self._default_si)
        if kind == "cluster" and self._default_si is not None and kind not in self.providers:
            from ..providers.vsphere.clusters import Clusters
            self.providers[kind] = Clusters(self._default_si)
        if kind == "host" and self._default_si is not None and kind not in self.providers:
            from ..providers.vsphere.hosts import Hosts
            self.providers[kind] = Hosts(self._default_si)
        if kind == "ovf" and self._default_si is not None and kind not in self.providers:
            from ..providers.vsphere.ovf_deploy import OvfDeploy
            self.providers[kind] = OvfDeploy(self._default_si, tls=self._tls)
        if kind == "template_clone" and self._default_si is not None and kind not in self.providers:
            from ..providers.vsphere.template_clone import TemplateClone
            self.providers[kind] = TemplateClone(self._default_si)
        if not isinstance(kind, str) or kind not in self.providers:
            fail("provider_unknown", "Provider 未注册或不可用，禁止调用远端", 4)
        return self.providers[kind]

    def _command(self, command):
        spec = lookup(command)
        if spec.category != "remote_write":
            fail("plan_command_invalid", "Provider 仅接受已注册远端原子写命令", 2)
        return spec

    def _binding(self, binding):
        kind = binding.get("provider_kind") if isinstance(binding, dict) else None
        provider = self._provider(kind)
        return kind, provider, {key: value for key, value in binding.items() if key != "provider_kind"}

    def _owned_binding(self, command, binding):
        spec = self._command(command)
        kind, provider, value = self._binding(binding)
        if spec.provider_kind != kind:
            fail("provider_mismatch", "命令与固定绑定的 Provider 不匹配", 4)
        return spec, provider, value

    def preflight(self, command, params):
        spec = self._command(command)
        binding = self._provider(spec.provider_kind).preflight(spec.path, params)
        return {**binding, "provider_kind": spec.provider_kind}

    def bind_steps(self, steps):
        if not steps:
            return []
        specs = [self._command(step["command"]) for step in steps]
        kinds = {spec.provider_kind for spec in specs}
        if len(kinds) != 1:
            fail("plan_dependency_unsupported", "跨 Provider 计划尚不支持依赖投影，请拆分计划", 4)
        kind = specs[0].provider_kind
        provider = self._provider(kind)
        inputs = [{**step, "command": spec.path} for step, spec in zip(steps, specs)]
        if hasattr(provider, "bind_steps"):
            bound = provider.bind_steps(inputs)
        elif len(inputs) == 1:
            step = inputs[0]
            bound = [{**step, "binding": provider.preflight(step["command"], step["params"])}]
        else:
            fail("plan_dependency_unsupported", "Provider 未提供多步骤状态投影，禁止逐步按现状预检", 4)
        return [{**step, "binding": {**step["binding"], "provider_kind": kind}} for step in bound]

    def matches(self, expected, actual):
        kind, provider, expected_value = self._binding(expected)
        actual_kind, _, actual_value = self._binding(actual)
        if kind != actual_kind:
            fail("provider_mismatch", "待比较绑定的 Provider 不匹配", 4)
        matches = getattr(provider, "matches", lambda a, b: a == b)
        return matches(expected_value, actual_value)

    def submit(self, command, params, binding):
        spec, provider, value = self._owned_binding(command, binding)
        return provider.submit(spec.path, params, value)

    def observe(self, receipt, binding):
        _, provider, value = self._binding(binding)
        return provider.observe(receipt, value)

    def verify(self, command, params, binding, observation):
        spec, provider, value = self._owned_binding(command, binding)
        return provider.verify(spec.path, params, value, observation)

    def cancel(self, receipt, binding):
        _, provider, value = self._binding(binding)
        return provider.cancel(receipt, value)

    def recover_receipt(self, command, params, binding):
        spec, provider, value = self._owned_binding(command, binding)
        if spec.provider_kind != "guest" or spec.path != "vm guest-exec":
            return None
        return provider.recover_receipt(spec.path, params, value)
