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

def get_user_choice(options, prompt):
    """
    通用交互选择函数
    """
    print(f"\n{prompt}:")
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")
    
    while True:
        try:
            choice = int(input(f"请输入编号 (1-{len(options)}): "))
            if 1 <= choice <= len(options):
                return options[choice-1]
        except ValueError:
            pass
        print(f"⚠️ 输入无效，请输入 1 到 {len(options)} 之间的数字。")

def run_auto_provision_demo():
    # --- [1] 配置中心 (建议后期对接 DeepNet-Ops 的 config.yaml) ---
    VC_CONFIG = {
        "host": "172.17.41.101",
        "user": "administrator@vsphere.local",
        "pwd": "59qe5ff&tXAm@24",
        "port": 443
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
            
            # 基础资源存在性校验
            if not report['datacenters']:
                print("❌ 错误: 未发现数据中心，流程终止。")
                return
            if not report['clusters']:
                print("❌ 错误: 未发现计算集群，流程终止。")
                return
            if not report['datastores']:
                print("❌ 错误: 未找到可用存储池，流程终止。")
                return
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

            # --- [交互选择逻辑] ---
            # 1. 交互选择模板
            template_names = [t['metadata']['name'] for t in report['templates']]
            target_template_name = get_user_choice(template_names, "请选择要克隆的源模板")

            # 2. 交互选择网络
            target_network_name = get_user_choice(report['networks'], "请选择虚拟机网络")

            # 3. 输入网络配置
            print("\n⚙️ 请输入静态网络配置:")
            ip_addr = input("  IP 地址: ").strip()
            subnet_mask = input("  子网掩码 (默认 255.255.255.0): ").strip() or "255.255.255.0"
            gateway_addr = input("  默认网关: ").strip()
            
            new_vm_name = f"DeepNet-Node-{ip_addr.split('.')[-1]}" if ip_addr else "DeepNet-New-VM"

            # --- [参数确认环节] ---
            print("\n" + "="*40)
            print("📝 请确认克隆任务参数:")
            print(f"  > 虚拟机名称: {new_vm_name}")
            print(f"  > 源 模 板  : {target_template_name}")
            print(f"  > 目标存储  : {target_ds['name']} (剩余: {target_ds['free_gb']} GB)")
            print(f"  > 目标宿主机: {target_host['name']}")
            print(f"  > 目标网络  : {target_network_name}")
            print(f"  > IP 配置   : {ip_addr} / {subnet_mask} / {gateway_addr}")
            print(f"  > 硬件规格  : 4C / 8G / 100G 磁盘")
            print("="*40)

            confirm = input("\n确认开始执行克隆动作吗? (y/n): ").strip().lower()
            if confirm != 'y':
                print("🚫 任务已取消。")
                return

            # --- [4] 执行高级克隆任务 ---
            print(f"\n⚡ [Step 3] 正在执行高级克隆任务...")
            
            msg = exe.clone_vm_advanced(
                template_name=target_template_name,
                new_name=new_vm_name,
                dc_name=report['datacenters'][0],
                cluster_name=report['clusters'][0]['name'],
                ds_name=target_ds['name'],
                network_name=target_network_name,
                host_name=target_host['name'],  # 定向调度
                cpus=4,                         # 规格自定义
                memory_mb=8192,
                disk_gb=100,                    # 自动扩容磁盘
                ip_address=ip_addr,
                subnet=subnet_mask,
                gateway=gateway_addr
            )
            print(f"✅ 任务结果: {msg}")

            # --- [5] 验证与画像输出 ---
            print(f"\n📊 [Step 4] 获取新部署虚拟机实时画像...")
            # 给 vCenter 一点时间刷新对象缓存
            import time
            time.sleep(2) 
            
            final_detail = inv.get_single_vm_detail(new_vm_name)
            if final_detail:
                print("--- 虚拟机资产画像 ---")
                print(f"  名称: {final_detail['name']}")
                print(f"  电源: {final_detail['power']}")
                print(f"  主机: {final_detail['host']}")
                print(f"  配置: {final_detail['config']['cpu']}核 / {final_detail['config']['memory_mb']}MB / {final_detail['config']['disk_gb']}GB")
                print(f"  网络: {final_detail['ip']}")
                print(f"  性能: CPU {final_detail['perf']['cpu_mhz']} MHz, MEM {final_detail['perf']['mem_mb']} MB")
                print("----------------------")
                
                if "等待" in final_detail['ip']:
                    print("💡 提示：静态 IP 注入需要系统启动并运行 VMware Tools。请稍后在 vSphere 客户端查看。")

    except Exception as e:
        import traceback
        print(f"\n❌ 流程异常中断: {str(e)}")
        print("-" * 30)
        traceback.print_exc()
        print("-" * 30)

if __name__ == "__main__":
    run_auto_provision_demo()