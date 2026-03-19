"""
Module: scripts.executor
Description: 深度自定义执行器。支持克隆时的宿主机定向调度、硬件规格调整（CPU/MEM/Disk）
             以及网络身份自定义（IP/Subnet/GW）。
Author: xiaofei
Date: 2026-03-19
"""

import time
import logging
from typing import Optional, Any
from pyVmomi import vim, vmodl

# 配置日志
logger = logging.getLogger(__name__)

class VCenterExecutor:
    """
    vCenter 高级动作执行类。
    处理复杂的克隆逻辑，包括硬件重配置和网络自定义规范注入。
    """

    def __init__(self, si: vim.ServiceInstance):
        """
        :param si: 有效的 ServiceInstance 连接
        """
        self.si = si
        self.content = si.RetrieveContent()

    def _get_obj(self, vim_type: Any, name: str) -> Optional[Any]:
        """
        内部辅助方法：按名称检索 Managed Object。
        """
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

    def _wait_for_task(self, task: vim.Task, task_name: str) -> Any:
        """
        阻塞监控任务进度，捕获异常。
        """
        logger.info(f"正在执行任务: {task_name}...")
        while task.info.state not in [vim.TaskInfo.State.success, vim.TaskInfo.State.error]:
            time.sleep(2)
        
        if task.info.state == vim.TaskInfo.State.error:
            error_msg = task.info.error.msg
            logger.error(f"任务 [{task_name}] 失败: {error_msg}")
            raise RuntimeError(f"vCenter 操作失败: {error_msg}")
        
        logger.info(f"任务 [{task_name}] 完成。")
        return task.info.result

    def clone_vm_advanced(self, 
                          template_name: str, 
                          new_name: str, 
                          dc_name: str, 
                          cluster_name: str, 
                          ds_name: str,
                          network_name: str,
                          host_name: Optional[str] = None,
                          cpus: Optional[int] = None, 
                          memory_mb: Optional[int] = None, 
                          disk_gb: Optional[int] = None,
                          ip_address: Optional[str] = None,
                          subnet: str = "255.255.255.0",
                          gateway: Optional[str] = None) -> str:
        """
        全功能克隆函数：
        
        :param host_name: 可选。指定物理宿主机名称，不指定则由集群负载均衡。
        :param ip_address: 可选。如果提供，将触发网络自定义注入。
        :param disk_gb: 可选。克隆后自动执行磁盘扩容。
        """
        
        # 1. 基础资源定位与校验
        template = self._get_obj(vim.VirtualMachine, template_name)
        cluster = self._get_obj(vim.ClusterComputeResource, cluster_name)
        ds = self._get_obj(vim.Datastore, ds_name)
        dc = self._get_obj(vim.Datacenter, dc_name)
        network = self._get_obj(vim.Network, network_name)

        if not all([template, cluster, ds, dc, network]):
            raise ValueError("克隆核心资源（模板/集群/存储/网络）缺失，请检查名称是否正确。")

        # 2. 定向宿主机选择逻辑
        target_host = None
        if host_name:
            target_host = self._get_obj(vim.HostSystem, host_name)
            if not target_host:
                raise ValueError(f"指定的宿主机 [{host_name}] 不存在。")
            logger.info(f"已指定目标宿主机: {host_name}")

        # 3. 构造位置与规格重配置 (RelocateSpec)
        relospec = vim.vm.RelocateSpec()
        relospec.datastore = ds
        relospec.pool = cluster.resourcePool # 默认进入集群根池
        
        if target_host:
            relospec.host = target_host # 强制指定宿主机

        # 修改 CPU 和 内存 (在克隆过程中直接应用)
        if cpus or memory_mb:
            config_spec = vim.vm.ConfigSpec()
            if cpus: config_spec.numCPUs = cpus
            if memory_mb: config_spec.memoryMB = memory_mb
            relospec.spec = config_spec

        # 4. 构造网络自定义规范 (CustomizationSpec)
        custom_spec = None
        if ip_address:
            logger.info(f"配置静态网络注入: IP={ip_address}, Mask={subnet}, GW={gateway}")
            
            # 设置 IP 地址
            ip_settings = vim.vm.customization.IPSettings()
            ip_settings.ip = vim.vm.customization.FixedIp(address=ip_address)
            ip_settings.subnetMask = subnet
            if gateway:
                ip_settings.gateway = [gateway]
            
            # 绑定网卡映射
            adapter_mapping = vim.vm.customization.AdapterMapping()
            adapter_mapping.adapter = ip_settings
            
            # 设置系统身份信息（以 Linux 为例，支持 Hostname 自动修改）
            ident = vim.vm.customization.LinuxPrep(
                hostName=vim.vm.customization.FixedName(name=new_name),
                domain="local"
            )
            
            custom_spec = vim.vm.customization.Specification(
                nicSettingMap=[adapter_mapping],
                identity=ident
            )

        # 5. 组装并执行克隆任务
        clone_spec = vim.vm.CloneSpec(
            location=relospec,
            powerOn=True if ip_address else False, # 配置了 IP 通常直接开机以触发 GuestOS 自定义
            customization=custom_spec,
            template=False
        )

        try:
            task = template.Clone(folder=dc.vmFolder, name=new_name, spec=clone_spec)
            self._wait_for_task(task, f"Clone-to-{new_name}")

            # 6. 后置处理：磁盘扩容
            # 限制：vSphere 不支持在克隆任务内直接改磁盘大小，需在克隆后 Reconfig
            if disk_gb:
                self._resize_main_disk(new_name, disk_gb)

            return f"成功：虚拟机 {new_name} 已部署。规格：{cpus}C/{memory_mb}MB。位置：{host_name or '集群自动选择'}"

        except Exception as e:
            logger.error(f"高级克隆流程中断: {e}")
            raise

    def _resize_main_disk(self, vm_name: str, new_size_gb: int):
        """
        克隆完成后，对虚拟机主磁盘执行在线扩容。
        """
        vm = self._get_obj(vim.VirtualMachine, vm_name)
        if not vm: return

        # 寻找第一个 VirtualDisk 设备
        disk = None
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualDisk):
                disk = device
                break
        
        if disk:
            # 校验：新容量必须大于旧容量
            new_capacity_kb = new_size_gb * 1024 * 1024
            if new_capacity_kb <= disk.capacityInKB:
                logger.warning("指定磁盘容量小于或等于当前容量，跳过扩容。")
                return

            disk.capacityInKB = new_capacity_kb
            spec = vim.vm.ConfigSpec()
            dev_spec = vim.vm.device.VirtualDeviceConfigSpec(
                device=disk, 
                operation=vim.vm.device.VirtualDeviceConfigSpec.Operation.edit
            )
            spec.deviceChange = [dev_spec]
            
            logger.info(f"正在调整磁盘大小至 {new_size_gb}GB...")
            self._wait_for_task(vm.ReconfigVM_Task(spec=spec), "Resize-Disk")