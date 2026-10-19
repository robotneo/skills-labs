"""Whole-vCenter positive evidence scan for linked-disk consumers.

Deleting a VM that backs a linked-clone child corrupts the child's disk chain.
Before authorizing ``vm delete`` we enumerate **every** VirtualMachine and
template in this vCenter (running config and the whole snapshot tree) and look
for any object other than the target whose disk chain references one of the
target's physical backing files.

Scope limitation (why an explicit operator attestation is still required):
this scan only sees objects managed by *this* vCenter. A second vCenter or a
standalone ESXi host mounting the same shared datastore is invisible here, so
even a clean scan is not proof against external consumers. Absence of evidence
is therefore never treated as authorization on its own.
"""
from ...domain.models import OperationError, fail


def enumerate_virtual_machines(content):
    """All VM/template managed objects in the vCenter, or raise if unprovable."""
    from pyVmomi import vim
    view = None
    try:
        view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
        machines = list(view.view or [])
    except OperationError:
        raise
    except Exception as exc:  # any enumeration gap must fail closed, never look empty
        fail("dependency_unproven", "无法完整枚举 vCenter 虚拟机清单，不能据此排除链接磁盘消费者: " + type(exc).__name__, 4)
    finally:
        if view is not None:
            try:
                view.Destroy()
            except Exception:
                pass
    return machines


def _backing_identity(backing):
    """Physical (datastore moId, canonical fileName) of one backing, or None."""
    datastore = getattr(backing, "datastore", None)
    file_name = getattr(backing, "fileName", None)
    if datastore is None or not getattr(datastore, "_moId", None) or not file_name:
        return None
    return (datastore._moId, file_name)


def _chain_identities(backing):
    """All physical files from a leaf backing up its delta parent chain."""
    identities, seen = [], set()
    depth = 0
    while backing is not None:
        depth += 1
        if depth > 64 or id(backing) in seen:
            # Malformed/cyclic chain: cannot reason about its real files.
            fail("dependency_unproven", "检测到异常或环状磁盘父链，无法证明无外部链接依赖", 4)
        seen.add(id(backing))
        identity = _backing_identity(backing)
        if identity is not None:
            identities.append(identity)
        backing = getattr(backing, "parent", None)
    return identities


def _config_disk_identities(config):
    """Physical files referenced by a VM or snapshot ConfigInfo's hardware."""
    from pyVmomi import vim
    if config is None:
        fail("dependency_unproven", "清单中存在读取不到配置的虚拟机，无法证明它不引用目标磁盘", 4)
    hardware = getattr(config, "hardware", None)
    devices = getattr(hardware, "device", None)
    if devices is None:
        fail("dependency_unproven", "清单虚拟机的硬件设备列表不可读，无法证明无链接磁盘依赖", 4)
    identities = []
    for device in devices:
        if not isinstance(device, vim.vm.device.VirtualDisk):
            continue
        backing = getattr(device, "backing", None)
        if backing is None:
            fail("dependency_unproven", "存在缺少 backing 的虚拟磁盘，无法证明无链接磁盘依赖", 4)
        identities.extend(_chain_identities(backing))
    return identities


def _snapshot_nodes(vm):
    """Every SnapshotTree node (root + descendants) of a VM."""
    snapshot_info = getattr(vm, "snapshot", None)
    roots = getattr(snapshot_info, "rootSnapshotList", None) if snapshot_info is not None else None
    if not roots:
        return []
    output, stack = [], list(roots)
    while stack:
        node = stack.pop()
        output.append(node)
        children = getattr(node, "childSnapshotList", None)
        if children:
            stack.extend(children)
    return output


def machine_disk_identities(vm):
    """All physical backing files a VM/template references now or in snapshots."""
    identities = _config_disk_identities(vm.config)
    for node in _snapshot_nodes(vm):
        config = getattr(getattr(node, "snapshot", None), "config", None)
        identities.extend(_config_disk_identities(config))
    return set(identities)


def scan(provider, target_vm):
    """Whole-vCenter evidence about other objects sharing the target's disks.

    Returns a dict:
      protected: sorted [[datastore moId, fileName], ...] the target references
      scanned:   sorted moIds of every OTHER VM/template enumerated
      consumers: [(moId, name), ...] of those whose disk chain shares a file

    Raises OperationError(dependency_unproven) whenever the inventory evidence
    is incomplete; the returned structure is positive, complete evidence only.
    """
    target_id = target_vm._moId
    # Every physical file the target can touch (running config + every snapshot
    # delta/base). Destroy_Task reclaims the VM-owned files among these; sharing
    # any of them with another object means removal is unsafe, so we protect the
    # full set rather than guessing which file the host will delete.
    protected = machine_disk_identities(target_vm)
    # JSON-stable shapes: the evidence is bound into the plan payload and later
    # compared after a canonical/JSON round-trip (tuples become lists there).
    protected_rows = sorted([list(identity) for identity in protected])
    if not protected:
        # A diskless VM has no linked-disk file for a consumer to depend on;
        # still record the enumerated set so a concurrent add is detectable.
        machines = enumerate_virtual_machines(provider.content)
        return {"protected": [], "consumers": [],
                "scanned": sorted(m._moId for m in machines if getattr(m, "_moId", None) != target_id)}
    consumers = []
    scanned = []
    for candidate in enumerate_virtual_machines(provider.content):
        mo_id = getattr(candidate, "_moId", None)
        if mo_id == target_id:
            continue
        scanned.append(mo_id)
        try:
            identities = machine_disk_identities(candidate)
        except OperationError:
            raise
        except Exception as exc:
            fail("dependency_unproven",
                 "读取清单虚拟机磁盘链失败，不能证明其不引用目标磁盘: " + type(exc).__name__, 4)
        if protected.intersection(identities):
            consumers.append((mo_id, getattr(candidate, "name", None) or mo_id))
    return {"protected": protected_rows, "consumers": consumers, "scanned": sorted(scanned)}


def find_disk_consumers(provider, target_vm):
    """[(moId, name)] of OTHER VMs whose disk chain shares a target file."""
    return scan(provider, target_vm)["consumers"]
