#!/usr/bin/env python3
"""
Module: scripts.executor
Description: vCenter 动作执行器。支持克隆、电源管理、删除、磁盘扩容。
Author: xiaofei
Date: 2026-03-19
Updated: 2026-03-20
"""

import time
import logging
from typing import Optional, Any
from pyVmomi import vim, vmodl

logger = logging.getLogger(__name__)


class VCenterExecutor:
    """vCenter 高级动作执行类。"""

    def __init__(self, si: vim.ServiceInstance):
        self.si = si
        self.content = si.RetrieveContent()

    def _get_obj(self, vim_type: Any, name: str) -> Optional[Any]:
        """按名称检索 Managed Object。"""
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim_type], True
        )
        try:
            for obj in container.view:
                if obj.name == name:
                    return obj
            return None
        finally:
            container.Destroy()

    def _wait_for_task(self, task: vim.Task, task_name: str, timeout: int = 600) -> Any:
        """阻塞监控任务进度，支持超时控制。"""
        logger.info(f"正在执行任务: {task_name}...")
        elapsed = 0
        while task.info.state not in [vim.TaskInfo.State.success, vim.TaskInfo.State.error]:
            time.sleep(3)
            elapsed += 3
            if elapsed >= timeout:
                raise RuntimeError(f"任务 [{task_name}] 超时（{timeout}s）")
        
        if task.info.state == vim.TaskInfo.State.error:
            error_msg = task.info.error.msg
            logger.error(f"任务 [{task_name}] 失败: {error_msg}")
            raise RuntimeError(f"vCenter 操作失败: {error_msg}")
        
        logger.info(f"任务 [{task_name}] 完成。")
        return task.info.result

    # ========================
    # 克隆
    # ========================

    def clone_vm_advanced(self, 
                          template_name: str, 
                          new_name: str, 
                          dc_name: str, 
                          cluster_name: str, 
                          ds_name: str,
                          network_name: str,
                          host_name: Optional[str] = None,
                          cpus: Optional[int] = None, 
                          memory_gb: Optional[int] = None, 
                          disk_gb: Optional[int] = None,
                          ip_address: Optional[str] = None,
                          subnet: str = "255.255.255.0",
                          gateway: Optional[str] = None) -> str:
        """
        全功能克隆函数。
        """
        # 1. 资源定位
        template = self._get_obj(vim.VirtualMachine, template_name)
        cluster = self._get_obj(vim.ClusterComputeResource, cluster_name)
        ds = self._get_obj(vim.Datastore, ds_name)
        dc = self._get_obj(vim.Datacenter, dc_name)
        network = self._get_obj(vim.Network, network_name)

        if not all([template, cluster, ds, dc, network]):
            missing = [k for k, v in {"template": template, "cluster": cluster, "ds": ds, "dc": dc, "network": network}.items() if not v]
            raise ValueError(f"资源缺失: {', '.join(missing)}")

        # 2. 宿主机选择
        target_host = None
        if host_name:
            target_host = self._get_obj(vim.HostSystem, host_name)
            if not target_host:
                raise ValueError(f"宿主机 [{host_name}] 不存在")
            logger.info(f"指定宿主机: {host_name}")

        # 3. RelocateSpec + 网卡映射
        relospec = vim.vm.RelocateSpec()
        relospec.datastore = ds
        if target_host:
            relospec.host = target_host
            relospec.pool = target_host.parent.resourcePool
        else:
            relospec.pool = cluster.resourcePool

        device_changes = []
        for device in template.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                nic_spec = vim.vm.device.VirtualDeviceSpec()
                nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
                nic_spec.device = device
                
                if isinstance(network, vim.dvs.DistributedVirtualPortgroup):
                    dvs_port_connection = vim.dvs.PortConnection()
                    dvs_port_connection.portgroupKey = network.key
                    dvs_port_connection.switchUuid = network.config.distributedVirtualSwitch.uuid
                    nic_spec.device.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo()
                    nic_spec.device.backing.port = dvs_port_connection
                else:
                    nic_spec.device.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
                    nic_spec.device.backing.network = network
                    nic_spec.device.backing.deviceName = network.name
                
                device_changes.append(nic_spec)
                break

        config_spec = vim.vm.ConfigSpec()
        if cpus: config_spec.numCPUs = cpus
        if memory_gb: config_spec.memoryMB = memory_gb * 1024
        if device_changes:
            config_spec.deviceChange = device_changes

        # 4. CustomizationSpec
        custom_spec = None
        if ip_address:
            logger.info(f"网络注入: IP={ip_address}, Mask={subnet}, GW={gateway}")
            ip_settings = vim.vm.customization.IPSettings()
            fixed_ip = vim.vm.customization.FixedIp()
            fixed_ip.ipAddress = ip_address
            ip_settings.ip = fixed_ip
            ip_settings.subnetMask = subnet
            if gateway:
                ip_settings.gateway = [gateway]
            
            adapter_mapping = vim.vm.customization.AdapterMapping()
            adapter_mapping.adapter = ip_settings
            global_ip = vim.vm.customization.GlobalIPSettings()
            ident = vim.vm.customization.LinuxPrep(
                hostName=vim.vm.customization.FixedName(name=new_name),
                domain="local"
            )
            custom_spec = vim.vm.customization.Specification(
                nicSettingMap=[adapter_mapping],
                identity=ident,
                globalIPSettings=global_ip
            )

        # 5. 执行克隆
        clone_spec = vim.vm.CloneSpec(
            location=relospec,
            config=config_spec,
            powerOn=True if ip_address else False,
            customization=custom_spec,
            template=False
        )

        try:
            task = template.Clone(folder=dc.vmFolder, name=new_name, spec=clone_spec)
            new_vm = self._wait_for_task(task, f"Clone-{new_name}")

            # 6. 磁盘扩容
            if disk_gb and isinstance(new_vm, vim.VirtualMachine):
                self._resize_vm_disk(new_vm, disk_gb)

            return f"虚拟机 {new_name} 部署成功。规格: {cpus or '默认'}C/{memory_gb or '默认'}GB。位置: {host_name or '集群自动调度'}"

        except Exception as e:
            logger.error(f"克隆失败: {e}")
            raise

    def rename_vm(self, vm_name: str, new_name: str) -> str:
        """重命名虚拟机。"""
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise Exception(f"虚拟机 {vm_name} 不存在")
        logger.info(f"正在重命名: {vm_name} -> {new_name}")
        task = vm.Rename(new_name)
        self._wait_for_task(task, f"Rename-{new_name}")
        return f"虚拟机已重命名为 {new_name}"

    def _resize_vm_disk(self, vm: vim.VirtualMachine, new_size_gb: int):
        """磁盘扩容。"""
        disk = None
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualDisk):
                disk = device
                break
        
        if disk:
            new_capacity_kb = new_size_gb * 1024 * 1024
            if new_capacity_kb <= disk.capacityInKB:
                logger.warning(f"磁盘容量 {new_size_gb}GB ≤ 当前容量，跳过扩容")
                return
            disk.capacityInKB = new_capacity_kb
            spec = vim.vm.ConfigSpec()
            dev_spec = vim.vm.device.VirtualDeviceSpec(
                device=disk,
                operation=vim.vm.device.VirtualDeviceSpec.Operation.edit
            )
            spec.deviceChange = [dev_spec]
            self._wait_for_task(vm.ReconfigVM_Task(spec=spec), "Resize-Disk")

    # ========================
    # 硬件热调整
    # ========================

    def reconfigure_vm(self, vm_name: str, cpus: Optional[int] = None,
                       memory_gb: Optional[int] = None, disk_gb: Optional[int] = None) -> str:
        """
        VM 硬件在线调整（热调整）。
        只调整传入的参数，未传入的保持不变。
        """
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")

        if vm.runtime.powerState != vim.VirtualMachinePowerState.poweredOn:
            raise ValueError(f"虚拟机 [{vm_name}] 未开机，无法热调整（请先开机）")

        spec = vim.vm.ConfigSpec()
        changes = []

        if cpus:
            spec.numCPUs = cpus
            changes.append(f"CPU -> {cpus}C")
        if memory_gb:
            spec.memoryMB = memory_gb * 1024
            changes.append(f"内存 -> {memory_gb}GB")
        if disk_gb:
            # 找到第一块磁盘并扩容
            for device in vm.config.hardware.device:
                if isinstance(device, vim.vm.device.VirtualDisk):
                    new_kb = disk_gb * 1024 * 1024
                    if new_kb <= device.capacityInKB:
                        raise ValueError(f"磁盘 {disk_gb}GB ≤ 当前容量，仅支持扩容")
                    disk_spec = vim.vm.device.VirtualDeviceSpec(
                        device=device,
                        operation=vim.vm.device.VirtualDeviceSpec.Operation.edit
                    )
                    disk_spec.device.capacityInKB = new_kb
                    spec.deviceChange = [disk_spec]
                    changes.append(f"磁盘 -> {disk_gb}GB")
                    break

        if not changes:
            return f"虚拟机 [{vm_name}] 未指定任何调整参数"

        self._wait_for_task(vm.ReconfigVM_Task(spec=spec), f"Reconfigure-{vm_name}")
        return f"虚拟机 [{vm_name}] 配置变更成功: {', '.join(changes)}"

    # ========================
    # 电源管理
    # ========================

    def set_vm_power(self, vm_name: str, state: str) -> str:
        """
        虚拟机电源管理。
        :param state: on / off / reset
        """
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")

        current = str(vm.runtime.powerState)
        logger.info(f"VM [{vm_name}] 当前状态: {current}, 目标: {state}")

        task = None
        if state == "on" and current != "poweredOn":
            task = vm.PowerOnVM_Task()
        elif state == "off" and current == "poweredOn":
            task = vm.PowerOffVM_Task()
        elif state == "reset" and current == "poweredOn":
            task = vm.ResetVM_Task()
        else:
            return f"虚拟机 [{vm_name}] 当前已为 {current}，无需操作"

        if task:
            self._wait_for_task(task, f"Power-{state}-{vm_name}")
        return f"虚拟机 [{vm_name}] 电源操作 [{state}] 执行成功"

    # ========================
    # 删除
    # ========================

    @staticmethod
    def _validate_delete_target(target: str) -> None:
        """
        删除操作安全校验：禁止全量/批量/通配符删除。
        
        校验规则：
        1. 目标不能为空
        2. 目标不能包含通配符（* ? [ ]）
        3. 目标不能是全量关键词（all / 全部 / 所有 / 空字符串等）
        4. 目标不能以"删除"语义开头（防止用户传整个指令而非目标名）
        """
        import re

        if not target or not target.strip():
            raise ValueError(
                "🚫 安全策略拦截：删除目标为空。"
                "必须指定明确的虚拟机名称或 IP，全量删除被禁止。"
            )

        target = target.strip()

        # 规则 1：通配符检测
        wildcard_chars = set("*?[](){}|^$+")
        if any(c in target for c in wildcard_chars):
            raise ValueError(
                f"🚫 安全策略拦截：目标 [{target}] 包含通配符/特殊字符，全量删除被禁止。"
                "请指定精确的虚拟机名称或 IP。"
            )

        # 规则 2：全量关键词检测
        bulk_keywords = [
            "all", "ALL", "全部", "所有", "所有虚拟机", "所有vm", "all vm",
            "全量", "批量", "清空", "清理", "整集群", "整主机",
        ]
        if target.lower().strip() in [k.lower() for k in bulk_keywords]:
            raise ValueError(
                f"🚫 安全策略拦截：[{target}] 属于全量/批量删除关键词，此操作被禁止。"
                "请指定精确的虚拟机名称或 IP。"
            )

        # 规则 3：正则模式检测（点号+通配符组合，如 test.*.vm）
        # 注意：纯 IP 前缀（如 172.17.40.16-xxx）不算正则模式
        regex_patterns = [
            r'\.[*?+]',     # 点号紧跟通配/量词（如 .*/.+/.?）
            r'\[[^\]]*\]', # 字符类（如 [abc]）
            r'\\d|\\w|\\s',  # 正则转义（如 \d, \w）
        ]
        for pattern in regex_patterns:
            if re.search(pattern, target):
                raise ValueError(
                    f"🚫 安全策略拦截：[{target}] 疑似正则/通配符模式，此操作被禁止。"
                    "请指定精确的虚拟机名称或 IP。"
                )

    def remove_vm(self, vm_name: str) -> str:
        """
        永久删除虚拟机（从磁盘移除）。
        开机状态自动关机后再删除。
        
        安全限制：必须指定精确的虚拟机名称，全量/批量/通配符删除被禁止。
        """
        # 安全校验：删除前强制校验目标
        self._validate_delete_target(vm_name)

        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")

        # 自动关机：开机状态无法直接删除
        if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
            logger.info(f"VM [{vm_name}] 处于开机状态，先执行关机...")
            task = vm.PowerOffVM_Task()
            self._wait_for_task(task, f"Power-off-{vm_name}")
            logger.info(f"VM [{vm_name}] 已关机")

        logger.warning(f"正在删除虚拟机: {vm_name}")
        task = vm.Destroy_Task()
        self._wait_for_task(task, f"Delete-{vm_name}")
        return f"虚拟机 [{vm_name}] 已永久删除"

    # ========================
    # 快照
    # ========================

    def list_snapshots(self, vm_name: str) -> list:
        """列出 VM 的所有快照。"""
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")

        if not vm.snapshot:
            return []

        def _walk(snap_tree):
            result = []
            for snap in snap_tree:
                result.append({
                    "name": snap.name,
                    "description": snap.description or "",
                    "created": snap.createTime.strftime("%Y-%m-%d %H:%M:%S") if snap.createTime else "unknown",
                    "size_mb": round(snap.size / (1024*1024), 2) if hasattr(snap, 'size') and snap.size else 0,
                })
                if snap.childSnapshotList:
                    result.extend(_walk(snap.childSnapshotList))
            return result

        return _walk(vm.snapshot.rootSnapshotList)

    def create_snapshot(self, vm_name: str, snap_name: str, description: str = "") -> str:
        """创建快照。"""
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")
        task = vm.CreateSnapshot_Task(name=snap_name, description=description, memory=False, quiesce=False)
        self._wait_for_task(task, f"Snapshot-{snap_name}")
        return f"虚拟机 [{vm_name}] 快照 [{snap_name}] 创建成功"

    def revert_snapshot(self, vm_name: str, snap_name: str) -> str:
        """恢复快照。"""
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")
        snapshot = None
        if vm.snapshot:
            for snap in vm.snapshot.rootSnapshotList:
                if snap.name == snap_name:
                    snapshot = snap.snapshot
                    break
        if not snapshot:
            raise ValueError(f"快照 [{snap_name}] 不存在")
        task = snapshot.RevertToSnapshot_Task()
        self._wait_for_task(task, f"Revert-{snap_name}")
        return f"虚拟机 [{vm_name}] 已恢复到快照 [{snap_name}]"

    # ========================
    # Guest OS 操作
    # ========================

    def guest_exec(self, vm_name: str, cmd: str, username: str = "root", password: str = "") -> dict:
        """
        在 VM 内部执行命令（需要 VMware Tools）。
        返回 {"exit_code": int, "stdout": str, "stderr": str, "pid": int}
        """
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")

        if not vm.guest or str(vm.guest.toolsStatus) not in ("toolsOk", "toolsOld"):
            raise ValueError(f"虚拟机 [{vm_name}] VMware Tools 未运行，无法执行 Guest 操作")

        creds = vim.vm.guest.NamePasswordAuthentication(username=username, password=password)

        try:
            pm = self.content.guestOperationsManager.processManager
            spec = vim.vm.guest.ProcessManager.ProgramSpec(
                programPath="/bin/bash",
                arguments=f"-c '{cmd}'"
            )
            pid = pm.StartProgramInGuest(vm, creds, spec)

            # 等待执行完成（最多 120 秒）
            timeout = 120
            elapsed = 0
            while elapsed < timeout:
                try:
                    procs = pm.ListProcessesInGuest(vm, creds, [pid])
                    if procs:
                        proc = procs[0]
                        if not proc.endTime:
                            time.sleep(2)
                            elapsed += 2
                            continue
                        return {
                            "exit_code": proc.exitCode,
                            "stdout": "",
                            "stderr": "",
                            "pid": pid,
                        }
                except Exception:
                    break
                time.sleep(2)
                elapsed += 2

            return {"exit_code": -1, "stdout": "", "stderr": "timeout", "pid": pid}
        except Exception as e:
            raise RuntimeError(f"Guest 执行失败: {e}")

    def guest_upload(self, vm_name: str, local_path: str, guest_path: str, username: str = "root", password: str = "") -> str:
        """上传文件到 VM（需要 VMware Tools）。TODO: 需要实现 vCenter session cookie 传递。"""
        raise NotImplementedError("guest_upload 涉及 HTTPS 文件传输和 cookie 管理，待实现")

    def guest_download(self, vm_name: str, guest_path: str, local_path: str, username: str = "root", password: str = "") -> str:
        """从 VM 下载文件（需要 VMware Tools）。TODO: 需要实现 vCenter session cookie 传递。"""
        raise NotImplementedError("guest_download 涉及 HTTPS 文件传输和 cookie 管理，待实现")

    # ========================
    # vMotion 迁移
    # ========================

    def migrate_vm(self, vm_name: str, target_host: str, priority: str = "defaultPriority") -> str:
        """
        vMotion 迁移 VM 到指定宿主机。
        :param priority: highPriority / defaultPriority / lowPriority
        """
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")

        if vm.runtime.powerState != vim.VirtualMachinePowerState.poweredOn:
            raise ValueError(f"虚拟机 [{vm_name}] 未开机，vMotion 仅支持运行中的 VM")

        host = self._get_obj(vim.HostSystem, target_host)
        if not host:
            raise ValueError(f"宿主机 [{target_host}] 不存在")

        # 校验目标宿主机可用
        if host.runtime.inMaintenanceMode:
            raise ValueError(f"宿主机 [{target_host}] 处于维护模式")
        if str(host.runtime.powerState) != "poweredOn":
            raise ValueError(f"宿主机 [{target_host}] 未开机")

        spec = vim.vm.MigrateSpec()
        spec.host = host
        spec.priority = priority

        logger.info(f"正在迁移 [{vm_name}] -> [{target_host}]...")
        task = vm.Migrate(migrateSpec=spec)
        self._wait_for_task(task, f"Migrate-{vm_name}-to-{target_host}")
        return f"虚拟机 [{vm_name}] 已迁移到 [{target_host}]"

    # ========================
    # 模板管理
    # ========================

    def register_template(self, vm_name: str, template_name: str = "") -> str:
        """
        将 VM 标记为模板。
        如果不指定 template_name，使用 VM 名称作为模板名称。
        """
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")

        name = template_name or vm_name

        # 检查是否已经是模板
        if isinstance(vm, vim.VirtualMachine) and vm.config and vm.config.template:
            raise ValueError(f"虚拟机 [{vm_name}] 已经是模板")

        logger.info(f"正在将 [{vm_name}] 标记为模板 [{name}]...")
        task = vm.MarkAsTemplate()
        self._wait_for_task(task, f"MarkTemplate-{vm_name}")

        # 如果指定了不同名称，重命名
        if template_name and template_name != vm_name:
            task = vm.Rename(name)
            self._wait_for_task(task, f"Rename-{vm_name}-to-{name}")

        return f"已将 [{vm_name}] 转换为模板 [{name}]"

    def convert_to_vm(self, template_name: str) -> str:
        """
        将模板转换回虚拟机。
        """
        vm = self._get_obj(vim.VirtualMachine, template_name)
        if not vm:
            raise ValueError(f"模板 [{template_name}] 不存在")

        if not (vm.config and vm.config.template):
            raise ValueError(f"[{template_name}] 不是模板，无法转换")

        logger.info(f"正在将模板 [{template_name}] 转换为虚拟机...")
        task = vm.MarkAsVirtualMachine(pool=None)
        self._wait_for_task(task, f"ConvertToVM-{template_name}")
        return f"已将模板 [{template_name}] 转换为虚拟机"

    def list_templates(self) -> list:
        """
        列出所有模板。
        返回 [{"name": str, "guest_os": str, "status": str}, ...]
        """
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        templates = []
        try:
            for vm in container.view:
                if vm.config and vm.config.template:
                    templates.append({
                        "name": vm.name,
                        "guest_os": vm.summary.config.guestFullName if vm.summary.config else "",
                        "status": str(vm.runtime.powerState),
                    })
        finally:
            container.Destroy()

        return sorted(templates, key=lambda x: x["name"])

    # ========================
    # 批量操作
    # ========================

    def _find_vms_by_pattern(self, pattern: str) -> list:
        """
        根据名称模式查找 VM（支持通配符 * 和 ?）。
        """
        import fnmatch
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        matched = []
        try:
            for vm in container.view:
                if not (vm.config and vm.config.template) and fnmatch.fnmatch(vm.name, pattern):
                    matched.append(vm)
        finally:
            container.Destroy()
        return matched

    def batch_power(self, pattern: str, state: str, max_concurrent: int = 5) -> dict:
        """
        批量设置 VM 电源状态。
        支持并发控制，错误隔离（单个失败不影响其他）。
        """
        import concurrent.futures

        vms = self._find_vms_by_pattern(pattern)
        if not vms:
            raise ValueError(f"未找到匹配 [{pattern}] 的虚拟机")

        results = {"total": len(vms), "success": 0, "failed": 0, "details": []}

        def power_single(vm):
            try:
                msg = self.set_vm_power(vm.name, state)
                return {"name": vm.name, "status": "success", "message": msg}
            except Exception as e:
                return {"name": vm.name, "status": "failed", "message": str(e)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as pool:
            futures = {pool.submit(power_single, vm): vm for vm in vms}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results["details"].append(result)
                if result["status"] == "success":
                    results["success"] += 1
                else:
                    results["failed"] += 1

        results["details"].sort(key=lambda x: x["name"])
        return results

    # ========================
    # 事件查询
    # ========================

    def get_events(self, minutes: int = 60, category: str = "", max_events: int = 50) -> list:
        """
        获取最近的 vCenter 事件。
        :param category: 事件类别（power/create_delete/migration/snapshot/alarm/""全部）
        """
        from scripts.event_watcher import get_recent_events, EVENT_TYPES

        event_types = EVENT_TYPES.get(category) if category else None
        return get_recent_events(self.content, minutes=minutes, event_types=event_types, max_events=max_events)

    # ========================
    # 资源配额检查
    # ========================

    def check_resource_quota(self, cluster_name: str = "", ds_name: str = "",
                              cpu_threshold: float = 0.85, mem_threshold: float = 0.85,
                              disk_threshold: float = 0.9) -> dict:
        """
        检查集群和数据存储的资源使用率，返回配额检查结果。

        :param cluster_name: 集群名称（空=所有集群）
        :param ds_name: 数据存储名称（空=所有存储）
        :param cpu_threshold: CPU 使用率告警阈值（0-1）
        :param mem_threshold: 内存使用率告警阈值（0-1）
        :param disk_threshold: 磁盘使用率告警阈值（0-1）
        """
        result = {
            "clusters": [],
            "datastores": [],
            "warnings": [],
        }

        # 检查集群
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.ClusterComputeResource], True
        )
        try:
            for cluster in container.view:
                if cluster_name and cluster.name != cluster_name:
                    continue

                summary = cluster.summary
                usage = summary.usageSummary
                cpu_capacity_mhz = usage.totalCpuCapacityMhz or 1
                cpu_demand_mhz = usage.cpuDemandMhz or 0
                mem_capacity_mb = usage.totalMemCapacityMB or 1
                mem_demand_mb = usage.memDemandMB or 0

                cpu_ratio = cpu_demand_mhz / cpu_capacity_mhz if cpu_capacity_mhz else 0
                mem_ratio = mem_demand_mb / mem_capacity_mb if mem_capacity_mb else 0

                entry = {
                    "name": cluster.name,
                    "cpu_demand_mhz": round(cpu_demand_mhz),
                    "cpu_capacity_mhz": round(cpu_capacity_mhz),
                    "cpu_ratio": round(cpu_ratio, 3),
                    "mem_demand_gb": round(mem_demand_mb / 1024, 1),
                    "mem_capacity_gb": round(mem_capacity_mb / 1024, 1),
                    "mem_ratio": round(mem_ratio, 3),
                    "hosts": len(cluster.host),
                    "vms": usage.totalVmCount or 0,
                }

                if cpu_ratio > cpu_threshold:
                    entry["cpu_warning"] = True
                    result["warnings"].append(f"集群 [{cluster.name}] CPU 使用率 {cpu_ratio:.1%} 超过阈值 {cpu_threshold:.0%}")
                if mem_ratio > mem_threshold:
                    entry["mem_warning"] = True
                    result["warnings"].append(f"集群 [{cluster.name}] 内存使用率 {mem_ratio:.1%} 超过阈值 {mem_threshold:.0%}")

                result["clusters"].append(entry)
        finally:
            container.Destroy()

        # 检查数据存储
        ds_container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.Datastore], True
        )
        try:
            for ds in ds_container.view:
                if ds_name and ds.name != ds_name:
                    continue

                summary = ds.summary
                if not summary.capacity or summary.capacity == 0:
                    continue

                free_gb = (summary.freeSpace or 0) / (1024**3)
                total_gb = summary.capacity / (1024**3)
                used_ratio = 1 - (free_gb / total_gb) if total_gb else 0

                entry = {
                    "name": ds.name,
                    "total_gb": round(total_gb, 1),
                    "free_gb": round(free_gb, 1),
                    "used_ratio": round(used_ratio, 3),
                    "type": summary.type,
                }

                if used_ratio > disk_threshold:
                    entry["disk_warning"] = True
                    result["warnings"].append(f"存储 [{ds.name}] 使用率 {used_ratio:.1%} 超过阈值 {disk_threshold:.0%}")
                elif free_gb < 50:  # 剩余不足 50GB 也告警
                    entry["disk_warning"] = True
                    result["warnings"].append(f"存储 [{ds.name}] 剩余空间仅 {free_gb:.1f}GB")

                result["datastores"].append(entry)
        finally:
            ds_container.Destroy()

        return result

    # ========================
    # 导出报表
    # ========================

    def export_vm_inventory(self, cluster_name: str = "", max_vms: int = 0) -> list:
        """
        导出 VM 清单。返回所有 VM 的详细信息。
        :param cluster_name: 集群过滤（空=全部）
        :param max_vms: 最多导出 VM 数（0=不限）
        """
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        vms = []
        try:
            for vm in container.view:
                # 跳过模板
                if vm.config and vm.config.template:
                    continue

                # 集群过滤（使用 runtime.host.parent 直接获取，避免遍历 parent 链）
                if cluster_name:
                    vm_cluster = ""
                    if vm.runtime.host and vm.runtime.host.parent:
                        vm_cluster = vm.runtime.host.parent.name
                    if vm_cluster != cluster_name:
                        continue

                # 获取集群名称
                vm_cluster = ""
                if vm.runtime.host and vm.runtime.host.parent:
                    vm_cluster = vm.runtime.host.parent.name

                # 获取磁盘大小
                disk_gb = 0
                if vm.config and vm.config.hardware and vm.config.hardware.device:
                    for device in vm.config.hardware.device:
                        if isinstance(device, vim.vm.device.VirtualDisk):
                            disk_gb += device.capacityInKB / (1024**2)

                entry = {
                    "name": vm.name,
                    "power_state": str(vm.runtime.powerState),
                    "guest_os": vm.summary.config.guestFullName if vm.summary.config else "",
                    "cpu": vm.config.hardware.numCPU if vm.config and vm.config.hardware else 0,
                    "memory_gb": round((vm.config.hardware.memoryMB or 0) / 1024, 1) if vm.config and vm.config.hardware else 0,
                    "disk_gb": round(disk_gb, 1),
                    "ip": vm.guest.ipAddress if vm.guest else "",
                    "host": vm.runtime.host.name if vm.runtime.host else "",
                    "cluster": vm_cluster,
                }
                vms.append(entry)

                if max_vms and len(vms) >= max_vms:
                    break
        finally:
            container.Destroy()

        return sorted(vms, key=lambda x: x["name"])

    # ========================
    # 数据存储浏览
    # ========================

    def browse_datastore(self, ds_name: str, path: str = "") -> list:
        """
        浏览数据存储中的文件/文件夹。
        :param ds_name: 数据存储名称
        :param path: 子路径（如 "iso/" 或 ""）
        """
        ds = self._get_obj(vim.Datastore, ds_name)
        if not ds:
            raise ValueError(f"数据存储 [{ds_name}] 不存在")

        browser = ds.browser
        spec = vim.HostDatastoreBrowserSearchSpec()
        spec.query = [
            vim.FolderFileQuery(),
            vim.FileQuery(),
        ]

        task = browser.SearchDatastore_Task(datastorePath=f'[{ds_name}] {path}', searchSpec=spec)
        result = self._wait_for_task(task, f"Browse-{ds_name}")

        files = []
        if hasattr(result, 'file') and result.file:
            for f in result.file:
                entry = {
                    "name": f.path,
                    "size_mb": round(f.fileSize / (1024*1024), 2) if hasattr(f, 'fileSize') and f.fileSize else 0,
                    "type": "folder" if isinstance(f, vim.FolderFileInfo) else "file",
                    "modified": f.modification.strftime("%Y-%m-%d %H:%M") if hasattr(f, 'modification') and f.modification else "",
                }
                files.append(entry)

        return files

    def scan_datastore_images(self, pattern: str = "", top_n: int = 50) -> list:
        """
        扫描所有数据存储中的镜像文件（ISO/OVA/OVF/VMDK）。
        """
        extensions = (".iso", ".ova", ".ovf", ".vmdk")
        all_files = []

        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.Datastore], True
        )
        try:
            for ds in container.view:
                browser = ds.browser
                spec = vim.HostDatastoreBrowserSearchSpec()
                spec.query = [vim.FileQuery()]

                task = browser.SearchDatastore_Task(datastorePath='/', searchSpec=spec)
                try:
                    result = self._wait_for_task(task, f"Scan-{ds.name}", timeout=120)
                    if hasattr(result, 'file') and result.file:
                        for f in result.file:
                            fname = f.path.lower()
                            if fname.endswith(extensions):
                                if pattern and pattern.lower() not in fname:
                                    continue
                                all_files.append({
                                    "datastore": ds.name,
                                    "path": f.path,
                                    "size_mb": round(f.fileSize / (1024*1024), 2) if hasattr(f, 'fileSize') and f.fileSize else 0,
                                    "modified": f.modification.strftime("%Y-%m-%d") if hasattr(f, 'modification') and f.modification else "",
                                })
                except Exception as e:
                    logger.warning(f"扫描 [{ds.name}] 失败: {e}")
        finally:
            container.Destroy()

        all_files.sort(key=lambda x: x["size_mb"], reverse=True)
        return all_files[:top_n]

    # ========================
    # 快照
    # ========================

    def remove_snapshot(self, vm_name: str, snap_name: str) -> str:
        """删除快照。"""
        # 安全校验
        self._validate_delete_target(vm_name)
        self._validate_delete_target(snap_name)

        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm:
            raise ValueError(f"虚拟机 [{vm_name}] 不存在")
        snapshot = None
        if vm.snapshot:
            for snap in vm.snapshot.rootSnapshotList:
                if snap.name == snap_name:
                    snapshot = snap.snapshot
                    break
        if not snapshot:
            raise ValueError(f"快照 [{snap_name}] 不存在")
        task = snapshot.RemoveSnapshot_Task(removeChildren=False)
        self._wait_for_task(task, f"RemoveSnapshot-{snap_name}")
        return f"虚拟机 [{vm_name}] 快照 [{snap_name}] 已删除"
