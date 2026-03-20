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
            # === 预扫描：一次性遍历收集所有对象 + 宿主机→VM 映射 ===
            host_obj_to_count = {}  # 用 ManagedObject 引用作为 key（mo_ref）
            all_objs = []
            for obj in container_view.view:
                all_objs.append(obj)
                if isinstance(obj, vim.VirtualMachine) and not obj.config.template:
                    host_ref = obj.runtime.host
                    if host_ref:
                        # 使用 ManagedObject 的 _moId 作为唯一标识
                        host_key = getattr(host_ref, '_moId', id(host_ref))
                        host_obj_to_count[host_key] = host_obj_to_count.get(host_key, 0) + 1
            logger.info(f"预扫描完成: {len(host_obj_to_count)} 台宿主机有 VM 分布")

            for obj in all_objs:
                
                # --- [1] 数据中心 ---
                if isinstance(obj, vim.Datacenter):
                    report["datacenters"].append(obj.name)

                # --- [2] 计算集群 ---
                elif isinstance(obj, vim.ClusterComputeResource):
                    # 安全获取父节点数据中心名称
                    dc_name = "N/A"
                    try:
                        curr = obj.parent
                        while curr and not isinstance(curr, vim.Datacenter):
                            curr = curr.parent
                        if curr: dc_name = curr.name
                    except: pass

                    report["clusters"].append({
                        "name": obj.name,
                        "dc_parent": dc_name,
                        "overall_status": str(obj.overallStatus)
                    })

                # --- [3] 物理宿主机 (HostSystem) ---
                elif isinstance(obj, vim.HostSystem):
                    hw = obj.hardware
                    cpu_desc = "Unknown"
                    if hw.cpuPkg and len(hw.cpuPkg) > 0:
                        cpu_desc = hw.cpuPkg[0].description

                    # 提取实时负载指标
                    cpu_usage_mhz = obj.summary.quickStats.overallCpuUsage or 0
                    # 兼容 vSphere 7+: numCpuCores 改为通过 CpuInfo 获取
                    num_cores = 0
                    if hasattr(hw, 'numCpuCores') and hw.numCpuCores:
                        num_cores = hw.numCpuCores
                    elif hasattr(hw, 'cpuInfo') and hw.cpuInfo and hasattr(hw.cpuInfo, 'numCpuCores'):
                        num_cores = hw.cpuInfo.numCpuCores
                    elif hasattr(hw, 'cpuInfo') and hw.cpuInfo and hasattr(hw.cpuInfo, 'numCpuPackages'):
                        num_cores = getattr(hw.cpuInfo, 'numCpuCores', 0) or (hw.cpuInfo.numCpuPackages * getattr(hw.cpuInfo, 'numCpuThreadsPerCore', 1) * getattr(hw.cpuInfo, 'numCpuPkgs', 1))

                    cpu_total_mhz = 0
                    if hasattr(hw, 'cpuMhz') and hw.cpuMhz:
                        cpu_total_mhz = hw.cpuMhz * num_cores
                    elif hasattr(hw, 'cpuInfo') and hw.cpuInfo:
                        hz = getattr(hw.cpuInfo, 'hz', 0) or 0
                        cpu_total_mhz = (hz // 1000000) * num_cores
                    cpu_usage_pct = round((cpu_usage_mhz / cpu_total_mhz) * 100, 2) if cpu_total_mhz > 0 else 0

                    mem_total_gb = round(hw.memorySize / (1024**3), 2)
                    mem_usage_gb = round((obj.summary.quickStats.overallMemoryUsage or 0) / 1024, 2)
                    mem_usage_pct = round((mem_usage_gb / mem_total_gb) * 100, 2) if mem_total_gb > 0 else 0

                    # 从预构建映射获取 VM 数量（通过 moId 匹配）
                    vm_count = host_obj_to_count.get(getattr(obj, '_moId', id(obj)), 0)

                    report["hosts"].append({
                        "name": obj.name,
                        "cluster_parent": obj.parent.name if obj.parent else "N/A",
                        "status": str(obj.overallStatus),
                        "maintenance_mode": obj.runtime.inMaintenanceMode,
                        "power_state": str(obj.runtime.powerState),
                        "cpu_model": cpu_desc,
                        "cpu_cores": num_cores,
                        "cpu_total_mhz": cpu_total_mhz,
                        "cpu_usage_mhz": cpu_usage_mhz,
                        "cpu_usage_pct": cpu_usage_pct,
                        "cpu_free_pct": round(100 - cpu_usage_pct, 2),
                        "memory_total_gb": mem_total_gb,
                        "memory_usage_gb": mem_usage_gb,
                        "memory_free_gb": round(mem_total_gb - mem_usage_gb, 2),
                        "memory_usage_pct": mem_usage_pct,
                        "memory_free_pct": round(100 - mem_usage_pct, 2),
                        "vm_count": vm_count
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
                                # 兼容性写法：pyVmomi 旧版本使用 capacityInKB
                                total_storage_gb += device.capacityInKB / (1024**2)

                    vm_profile = {
                        "metadata": {
                            "name": obj.name,
                            "uuid": config.uuid,
                            "guest_os": config.guestFullName,
                        },
                        "hardware": {
                            "cpu_cores": config.hardware.numCPU,
                            "ram_gb": round(config.hardware.memoryMB / 1024, 2),
                            "disk_gb": round(total_storage_gb, 2)
                        },
                        "runtime": {
                            "power_state": str(runtime.powerState),
                            "ip_address": guest.ipAddress or self._extract_vm_ips(obj) or "N/A",
                            "host_node": runtime.host.name if runtime.host else "Unknown",
                            "tools_status": str(guest.toolsStatus)
                        },
                        "performance": {
                            "cpu_usage_mhz": summary.quickStats.overallCpuUsage,
                            "mem_usage_gb": round(summary.quickStats.guestMemoryUsage / 1024, 2)
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

    def _extract_vm_ips(self, obj) -> str:
        """从 guest.net 提取第一个非空 IP（兼容关机 VM）。"""
        try:
            for nic in (obj.guest.net or []):
                for ip in (nic.ipAddress or []):
                    if ip and '.' in ip and not ip.startswith('fe80') and not ip.startswith('169.254'):
                        return ip
        except Exception:
            pass
        return ""

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
            
            summary = vm.summary
            config = vm.config
            stats = summary.quickStats
            
            # 计算总磁盘容量
            total_disk_gb = 0
            for device in config.hardware.device:
                if isinstance(device, vim.vm.device.VirtualDisk):
                    total_disk_gb += device.capacityInKB / (1024**2)
            
            return {
                "name": vm.name,
                "power": str(vm.runtime.powerState),
                "ip": summary.guest.ipAddress or "等待 VMware Tools 启动...",
                "host": vm.runtime.host.name if vm.runtime.host else "Unknown",
                "config": {
                    "cpu": config.hardware.numCPU,
                    "memory_gb": round(config.hardware.memoryMB / 1024, 2),
                    "disk_gb": round(total_disk_gb, 2)
                },
                "perf": {
                    "cpu_mhz": stats.overallCpuUsage or 0,
                    "mem_gb": round((stats.guestMemoryUsage or 0) / 1024, 2)
                }
            }
        finally:
            container_view.Destroy()

    # ========================================================================
    # 宿主机调度评分
    # ========================================================================

    # 评分权重配置
    SCORE_WEIGHTS = {
        "cpu_free_pct": 0.40,       # CPU 空闲率权重
        "mem_free_pct": 0.35,       # 内存空闲率权重
        "load_balance": 0.25,       # 负载均衡因子（VM 数量越少分越高）
    }

    def score_hosts(self, hosts: List[Dict], top_n: int = 5,
                    cluster_filter: str = None) -> List[Dict]:
        """
        对宿主机进行评分排序，返回 TopN 推荐列表。

        评分模型:
          Score = CPU空闲率 × 0.40
                + 内存空闲率 × 0.35
                + 负载均衡因子 × 0.25

        其中负载均衡因子计算方式：
          - 找出所有宿主机中最大的 VM 数量 max_vm
          - 每台宿主机的负载因子 = (max_vm - vm_count) / max_vm × 100
          - 即 VM 越少得分越高

        :param hosts: fetch_all_inventory() 返回的 hosts 列表
        :param top_n: 返回前 N 名
        :param cluster_filter: 可选，按集群名称过滤
        :return: 按 Score 降序排列的宿主机列表（含 score 字段）
        """
        # 过滤条件
        candidates = []
        for h in hosts:
            # 跳过维护模式
            if h.get("maintenance_mode"):
                continue
            # 跳过非开机状态
            if str(h.get("power_state")) != "poweredOn":
                continue
            # 跳过异常状态
            if str(h.get("status")) not in ["green", "gray"]:
                continue
            # 集群过滤
            if cluster_filter and h.get("cluster_parent") != cluster_filter:
                continue
            candidates.append(h)

        if not candidates:
            return []

        # 计算负载均衡因子
        vm_counts = [h.get("vm_count", 0) for h in candidates]
        max_vm = max(vm_counts) if vm_counts else 1
        if max_vm == 0:
            max_vm = 1  # 避免除零

        w = self.SCORE_WEIGHTS
        scored = []
        for h in candidates:
            cpu_free = h.get("cpu_free_pct", 0)
            mem_free = h.get("memory_free_pct", 0)
            vm_count = h.get("vm_count", 0)

            # 负载均衡因子: VM 越少，分越高
            load_factor = ((max_vm - vm_count) / max_vm) * 100

            score = round(
                cpu_free * w["cpu_free_pct"]
                + mem_free * w["mem_free_pct"]
                + load_factor * w["load_balance"],
                2
            )

            scored.append({**h, "score": score})

        # 按 Score 降序排列
        scored.sort(key=lambda x: x["score"], reverse=True)

        # 添加排名
        for i, h in enumerate(scored):
            h["rank"] = i + 1

        return scored[:top_n]

    def recommend_hosts(self, hosts: List[Dict], cluster_filter: str = None) -> Dict:
        """
        生成宿主机推荐报告，供 Agent 展示给用户选择。

        :return: 包含 recommended（Top5）和 best（最优）的报告
        """
        top5 = self.score_hosts(hosts, top_n=5, cluster_filter=cluster_filter)

        best = top5[0] if top5 else None

        return {
            "recommended": top5,
            "best": best,
            "total_candidates": len([h for h in hosts
                                      if not h.get("maintenance_mode")
                                      and str(h.get("power_state")) == "poweredOn"]),
            "total_excluded": len(hosts) - len([h for h in hosts
                                                 if not h.get("maintenance_mode")
                                                 and str(h.get("power_state")) == "poweredOn"]),
            "weights_used": self.SCORE_WEIGHTS
        }