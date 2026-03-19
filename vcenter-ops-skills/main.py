"""
Main Entry Point for vcenter-ops-skills
此脚本展示了如何串联查询与动作逻辑：自动寻找资源并执行克隆。
"""

from scripts.client import VCenterClient
from scripts.inventory import VCenterInventory
from scripts.executor import VCenterExecutor
import json

def run_auto_provision_demo():
    # 配置信息（建议生产环境走环境变量或加密配置）
    VC_CONFIG = {
        "host": "192.168.1.10",
        "user": "administrator@vsphere.local",
        "pwd": "YourSecurePassword"
    }

    # 1. 初始化连接
    with VCenterClient(**VC_CONFIG) as si:
        print("--- [1] 成功连接 vCenter, 开始资源巡检 ---")
        inv = VCenterInventory(si)
        exe = VCenterExecutor(si)

        # 2. 获取所有资源信息
        resources = inv.get_all_resources()
        print(f"找到数据中心: {resources['datacenters']}")
        print(f"可用模板: {resources['templates']}")

        if not resources['templates']:
            print("错误: 未找到任何虚拟机模板，无法执行克隆测试。")
            return

        # 3. 自动化决策逻辑 (AIOps 雏形)
        # 目标：寻找一个空间剩余最大的 Datastore
        sorted_ds = sorted(resources['datastores'], key=lambda x: x['free_gb'], reverse=True)
        target_ds = sorted_ds[0]['name']
        target_dc = resources['datacenters'][0]
        target_cluster = resources['clusters'][0]['name']
        template_to_use = resources['templates'][0]
        new_vm_name = "DeepNet-Ops-Node-01"

        print(f"\n--- [2] 自动决策结果 ---")
        print(f"准备将模板 [{template_to_use}] 克隆为 [{new_vm_name}]")
        print(f"目标集群: {target_cluster} | 目标存储: {target_ds} (剩余 {sorted_ds[0]['free_gb']} GB)")

        # 4. 执行克隆动作
        print(f"\n--- [3] 开始执行克隆任务 (请稍候...) ---")
        try:
            msg = exe.clone_vm(
                template_name=template_to_use,
                new_vm_name=new_vm_name,
                dc_name=target_dc,
                cluster_name=target_cluster,
                ds_name=target_ds
            )
            print(f"结果: {msg}")

            # 5. 验证克隆后的 VM 详情
            print(f"\n--- [4] 检查新虚拟机详情 ---")
            vm_detail = inv.find_vm_detail(new_vm_name)
            print(json.dumps(vm_detail, indent=4, ensure_ascii=False))

        except Exception as e:
            print(f"操作失败: {str(e)}")

if __name__ == "__main__":
    run_auto_provision_demo()