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

    def remove_vm(self, vm_name: str) -> str:
        """
        永久删除虚拟机（从磁盘移除）。
        开机状态自动关机后再删除。
        """
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

    def remove_snapshot(self, vm_name: str, snap_name: str) -> str:
        """删除快照。"""
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
