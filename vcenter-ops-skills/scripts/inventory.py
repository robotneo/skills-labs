"""
Module: scripts.inventory
Description: vCenter 资源发现与深度资产画像模块。
功能：
1. 高性能 ContainerView 扫描，支持大规模集群。
2. 自动化区分虚拟机（VM）与模板（Template）。
3. 物理宿主机（Host）发现，支持定向调度决策。
4. 深度提取硬件配置、运行指标与存储水位预警。

Author: xiaofei
Date: 2026-03-19
"""

import logging
from typing import List, Dict, Any, Optional, Union
from pyVmomi import vim, vmodl

# 配置模块级日志记录器
logger = logging.getLogger(__name__)

class VCenterInventory:
    """
    vCenter 资源巡检与资产分析类。
    
    利用 vSphere 的 PropertyCollector 机制，通过 ContainerView 实现高效对象抓取。
    """

    # 存储剩余空间告警阈值（百分比）
    STORAGE_THRESHOLD_PERCENT: float = 10.0

    def __init__(self, si: vim.ServiceInstance):
        """
        初始化巡检类。
        :param si: 已建立的服务实例会话。
        """
        self.si = si
        self.content = si.RetrieveContent()

    def fetch_all_inventory(self) -> Dict[str, Any]:
        """
        对 vCenter 全域资源执行深度扫描。
        包含：DC、集群、存储、网络、物理宿主机、虚拟机及模板。

        :return: 结构化资产报表。
        """
        logger.info("正在启动全量深度资产扫描 [Infrastructure & Workload]...")

        # 定义需要被视图感知的受管对象类型，增加了 HostSystem
        target_types: List[type] = [
            vim.Datacenter,
            vim.ClusterComputeResource,
            vim.HostSystem,            # 新增：物理宿主机扫描
            vim.Datastore,
            vim.Network,
            vim.VirtualMachine
        ]

        # 创建容器视图
        container_view = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, target_types, True
        )

        # 初始化标准报表结构
        report: Dict[str, List[Any]] = {
            "datacenters": [],
            "clusters": [],
            "hosts": [],        # 新增：物理机资产列表
            "datastores": [],
            "networks": [],
            "vms": [],
            "templates": []
        }

        try:
            for obj in container_view.view:
                
                # --- [1] 数据中心 ---
                if isinstance(obj, vim.Datacenter):
                    report["datacenters"].append(obj.name)

                # --- [2] 计算集群 ---
                elif isinstance(obj, vim.ClusterComputeResource):
                    report["clusters"].append({
                        "name": obj.name,
                        "dc_parent": obj.parent.parent.name,
                        "overall_status": str(obj.overallStatus)
                    })

                # --- [3] 物理宿主机 (HostSystem) ---
                elif isinstance(obj, vim.HostSystem):
                    # 提取物理机关键指标，用于克隆时的定向调度参考
                    hw = obj.hardware
                    report["hosts"].append({
                        "name": obj.name,
                        "cluster_parent": obj.parent.name if obj.parent else "N/A",
                        "status": str(obj.overallStatus),
                        "maintenance_mode": obj.runtime.inMaintenanceMode, # 是否维护模式
                        "cpu_model": hw.cpuPkg[0].description if hw.cpuPkg else "Unknown",
                        "memory_gb": round(hw.memorySize / (1024**3), 2),
                        "power_state": str(obj.runtime.powerState)
                    })

                # --- [4] 存储池巡检 ---
                elif isinstance(obj, vim.Datastore):
                    sumry = obj.summary
                    cap_gb = round(sumry.capacity / (1024**3), 2)
                    free_gb = round(sumry.freeSpace / (1024**3), 2)
                    free_p = (sumry.freeSpace / sumry.capacity * 100) if sumry.capacity > 0 else 0
                    
                    report["datastores"].append({
                        "name": obj.name,
                        "total_gb": cap_gb,
                        "free_gb": free_gb,
                        "free_percent": round(free_p, 2),
                        "is_low_space": free_p < self.STORAGE_THRESHOLD_PERCENT
                    })

                # --- [5] 网络资源 ---
                elif isinstance(obj, vim.Network):
                    report["networks"].append(obj.name)

                # --- [6] 虚拟机与模板资产画像 ---
                elif isinstance(obj, vim.VirtualMachine):
                    config = obj.config
                    summary = obj.summary
                    runtime = obj.runtime
                    guest = summary.guest

                    # 硬件磁盘汇总
                    total_storage_gb = 0
                    if config.hardware.device:
                        for device in config.hardware.device:
                            if isinstance(device, vim.vm.device.VirtualDisk):
                                total_storage_gb += device.capacityInBytes / (1024**3)

                    vm_profile = {
                        "metadata": {
                            "name": obj.name,
                            "uuid": config.uuid,
                            "guest_os": config.guestFullName,
                        },
                        "hardware": {
                            "cpu_cores": config.hardware.numCPU,
                            "ram_mb": config.hardware.memoryMB,
                            "disk_gb": round(total_storage_gb, 2)
                        },
                        "runtime": {
                            "power_state": str(runtime.powerState),
                            "ip_address": guest.ipAddress or "N/A",
                            "host_node": runtime.host.name if runtime.host else "Unknown",
                            "tools_status": str(guest.toolsStatus)
                        },
                        "performance": {
                            "cpu_usage_mhz": summary.quickStats.overallCpuUsage,
                            "mem_usage_mb": summary.quickStats.guestMemoryUsage
                        }
                    }

                    if config.template:
                        report["templates"].append(vm_profile)
                    else:
                        report["vms"].append(vm_profile)

            logger.info(f"巡检成功: 发现 {len(report['hosts'])} 台物理机, {len(report['vms'])} 台虚拟机。")
            return report

        except Exception as e:
            logger.error(f"巡检失败: {str(e)}", exc_info=True)
            raise
        finally:
            container_view.Destroy()

    def get_single_vm_detail(self, vm_name: str) -> Optional[Dict[str, Any]]:
        """
        特定 VM 的高精度探测。
        """
        container_view = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            vm = next((v for v in container_view.view if v.name == vm_name), None)
            if not vm: return None
            
            stats = vm.summary.quickStats
            return {
                "name": vm.name,
                "power": str(vm.runtime.powerState),
                "ip": vm.summary.guest.ipAddress,
                "host": vm.runtime.host.name if vm.runtime.host else "Unknown",
                "perf": {
                    "cpu": stats.overallCpuUsage,
                    "mem": stats.guestMemoryUsage
                }
            }
        finally:
            container_view.Destroy()