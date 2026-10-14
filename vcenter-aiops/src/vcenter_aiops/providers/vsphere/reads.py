from datetime import datetime, timezone
from ...domain.models import fail


class Reads:
    def __init__(self, provider):
        self.provider = provider

    def preset_hardware(self, vm_id):
        """Return only representable CPU/memory values, never an SDK object."""
        vm = self.provider.vm(vm_id)
        hardware = vm.config.hardware
        cpu, memory_mb = hardware.numCPU, hardware.memoryMB
        if type(cpu) is not int or cpu < 1 or type(memory_mb) is not int or memory_mb < 1024 or memory_mb % 1024:
            fail("preset_hardware_unsupported", "CPU 或内存不可表示为正整数 CPU 与整 GiB 内存，不会取整", 4)
        return {"cpu": cpu, "memory_gb": memory_mb // 1024}

    def snapshots(self, vm_id, limit):
        vm = self.provider.vm(vm_id)
        roots = vm.snapshot.rootSnapshotList if vm.snapshot else []
        stack, items = [(n, None) for n in reversed(roots)], []
        while stack and len(items) < limit:
            node, parent = stack.pop()
            items.append({"id": node.snapshot._moId, "parent_id": parent, "name": node.name,
                          "description": (node.description or "")[:4096], "power_state": str(node.state),
                          "created_at": node.createTime.isoformat() if node.createTime else None})
            stack.extend((n, node.snapshot._moId) for n in reversed(node.childSnapshotList or []))
        return {"items": items, "truncated": bool(stack), "untrusted_content": True,
                "collected_at": datetime.now(timezone.utc).isoformat()}

    def tools(self, vm_id):
        vm = self.provider.vm(vm_id)
        guest = vm.guest
        ready = vm.runtime.powerState == "poweredOn" and guest.toolsRunningStatus == "guestToolsRunning"
        return {"ready": ready, "running_status": guest.toolsRunningStatus,
                "version_status": guest.toolsVersionStatus2, "guest_family": guest.guestFamily,
                "ip_address": guest.ipAddress, "collected_at": datetime.now(timezone.utc).isoformat(),
                "source": "vcenter_guest_info", "warnings": [] if ready else ["关机或 Tools 未就绪；Guest 字段可能是历史记录"]}
