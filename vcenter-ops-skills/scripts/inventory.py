# scripts/inventory.py
"""
资源查询逻辑：负责获取 DC, Cluster, Datastore, Network, Template
"""

from pyVmomi import vim

class VCenterInventory:
    """资源查询逻辑：负责获取 DC, Cluster, Datastore, Network, Template"""
    def __init__(self, si):
        self.content = si.RetrieveContent()

    def get_all_resources(self):
        """一键扫描全库资源，返回结构化 JSON"""
        # 定义我们需要批量抓取的类型
        types = [vim.Datacenter, vim.ClusterComputeResource, 
                 vim.Datastore, vim.Network, vim.VirtualMachine]
        
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, types, True
        )
        
        data = {
            "datacenters": [],
            "clusters": [],
            "datastores": [],
            "networks": [],
            "templates": []
        }

        for obj in container.view:
            if isinstance(obj, vim.Datacenter):
                data["datacenters"].append(obj.name)
            elif isinstance(obj, vim.ClusterComputeResource):
                data["clusters"].append({
                    "name": obj.name,
                    "dc": obj.parent.parent.name # 溯源所属 DC
                })
            elif isinstance(obj, vim.Datastore):
                # 过滤出剩余空间，方便后续克隆决策
                free_gb = round(obj.summary.freeSpace / 1024**3, 2)
                data["datastores"].append({"name": obj.name, "free_gb": free_gb})
            elif isinstance(obj, vim.Network):
                data["networks"].append(obj.name)
            elif isinstance(obj, vim.VirtualMachine) and obj.config.template:
                data["templates"].append(obj.name)

        container.Destroy() # 必须销毁视图以释放服务器资源
        return data

    def find_vm_detail(self, vm_name):
        """获取单个虚拟机的详细配置信息"""
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        vm = next((v for v in container.view if v.name == vm_name), None)
        container.Destroy()

        if not vm:
            return None
            
        return {
            "name": vm.name,
            "status": vm.runtime.powerState,
            "ip": vm.summary.guest.ipAddress or "No IP",
            "cpu": vm.config.hardware.numCPU,
            "memory_mb": vm.config.hardware.memoryMB,
            "host": vm.runtime.host.name
        }