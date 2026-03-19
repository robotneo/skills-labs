"""
Main Entry Point for vcenter-ops-skills (DeepNet-Ops Edition)
功能：自动化资源巡检、基于评分的最优宿主机决策、以及高级自定义克隆演示。
"""

from scripts.client import VCenterClient
from scripts.inventory import VCenterInventory
from scripts.executor import VCenterExecutor
import json
import logging

# 屏蔽繁琐的连接日志，只保留业务逻辑输出
logging.basicConfig(level=logging.ERROR)

def run_auto_provision_demo():
    # --- [1] 配置中心 (建议后期对接 DeepNet-Ops 的 config.yaml) ---
    VC_CONFIG = {
        "host": "192.168.1.10",
        "user": "administrator@vsphere.local",
        "pwd": "YourSecurePassword",
        "port": 443
    }

    # 模拟从 IP 池获取的静态网络信息
    STATIC_NET_CONFIG = {
        "ip": "192.168.1.105",
        "mask": "255.255.255.0",
        "gw": "192.168.1.1",
        "network_name": "VM-Network-VLAN10"
    }

    print("="*60)
    print("🚀 DeepNet-Ops: 自动化置备流程启动...")
    print("="*60)

    try:
        with VCenterClient(**VC_CONFIG) as si:
            # 初始化核心组件
            inv = VCenterInventory(si)
            exe = VCenterExecutor(si)

            # --- [2] 深度资源发现 ---
            print("\n🔍 [Step 1] 执行全栈巡检...")
            report = inv.fetch_all_inventory()
            
            if not report['templates']:
                print("❌ 错误: 未找到任何可用模板，流程终止。")
                return

            # --- [3] AIOps 智能决策逻辑 ---
            print("\n🧠 [Step 2] 正在进行资源建模与自动决策...")

            # 决策 A: 寻找空间最充足的存储池 (Datastore)
            sorted_ds = sorted(report['datastores'], key=lambda x: x['free_gb'], reverse=True)
            target_ds = sorted_ds[0]

            # 决策 B: 寻找最优物理宿主机 (基于负载评分)
            # 过滤掉维护模式的机器，并选择内存充足的节点
            available_hosts = [h for h in report['hosts'] if not h['maintenance_mode']]
            if not available_hosts:
                print("❌ 错误: 没有可用的物理宿主机 (均在维护中)。")
                return
            
            # 简单评分逻辑：按内存大小排序 (实际可增加 CPU 实时使用率维度)
            target_host = sorted(available_hosts, key=lambda x: x['memory_gb'], reverse=True)[0]

            # 决策 C: 选择首个可用模板
            template_vm = report['templates'][0]
            new_vm_name = f"DeepNet-Node-{STATIC_NET_CONFIG['ip'].split('.')[-1]}"

            print(f"   > 目标模板: {template_vm['metadata']['name']}")
            print(f"   > 目标存储: {target_ds['name']} (剩余: {target_ds['free_gb']} GB)")
            print(f"   > 目标宿主机: {target_host['name']} (内存: {target_host['memory_gb']} GB)")
            print(f"   > 规划 IP: {STATIC_NET_CONFIG['ip']}")

            # --- [4] 执行高级克隆任务 ---
            print(f"\n⚡ [Step 3] 开始下发高级克隆任务...")
            print(f"   [配置参数] 4C / 8G / 100G 磁盘扩容 / 静态网络注入")
            
            msg = exe.clone_vm_advanced(
                template_name=template_vm['metadata']['name'],
                new_name=new_vm_name,
                dc_name=report['datacenters'][0],
                cluster_name=report['clusters'][0]['name'],
                ds_name=target_ds['name'],
                network_name=STATIC_NET_CONFIG['network_name'],
                host_name=target_host['name'],  # 定向调度
                cpus=4,                         # 规格自定义
                memory_mb=8192,
                disk_gb=100,                    # 自动扩容磁盘
                ip_address=STATIC_NET_CONFIG['ip'],
                subnet=STATIC_NET_CONFIG['mask'],
                gateway=STATIC_NET_CONFIG['gw']
            )
            print(f"✅ 任务结果: {msg}")

            # --- [5] 验证与画像输出 ---
            print(f"\n📊 [Step 4] 获取新部署虚拟机实时画像...")
            final_detail = inv.get_single_vm_detail(new_vm_name)
            if final_detail:
                print(json.dumps(final_detail, indent=4, ensure_ascii=False))

    except Exception as e:
        print(f"\n❌ 流程异常中断: {str(e)}")

if __name__ == "__main__":
    run_auto_provision_demo()