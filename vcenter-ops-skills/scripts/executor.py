# scripts/executor.py
"""
动作处理逻辑：克隆、删除、更新
"""

from pyVmomi import vim
import time

class VCenterExecutor:
    """动作处理逻辑：克隆、删除、更新"""
    def __init__(self, si):
        self.si = si
        self.content = si.RetrieveContent()

    def _wait_for_task(self, task):
        """阻塞等待 vCenter 任务完成并返回结果"""
        while task.info.state not in [vim.TaskInfo.State.success, vim.TaskInfo.State.error]:
            time.sleep(1)
        if task.info.state == vim.TaskInfo.State.error:
            raise Exception(f"vCenter 任务失败: {task.info.error.msg}")
        return task.info.result

    def _get_obj_by_name(self, vim_type, name):
        """通用查找：根据名称获取受管对象 (ManagedObject)"""
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim_type], True
        )
        obj = next((o for o in container.view if o.name == name), None)
        container.Destroy()
        return obj

    def clone_vm(self, template_name, new_name, dc_name, cluster_name, ds_name):
        """从模板克隆虚拟机"""
        template = self._get_obj_by_name(vim.VirtualMachine, template_name)
        dc = self._get_obj_by_name(vim.Datacenter, dc_name)
        cluster = self._get_obj_by_name(vim.ClusterComputeResource, cluster_name)
        ds = self._get_obj_by_name(vim.Datastore, ds_name)

        if not all([template, dc, cluster, ds]):
            raise Exception("克隆所需的资源对象（模板/集群/存储）不完整，请检查参数。")

        # 配置位置：ResourcePool 和 Datastore
        relospec = vim.vm.RelocateSpec(datastore=ds, pool=cluster.resourcePool)
        # 配置克隆规范
        clonespec = vim.vm.CloneSpec(location=relospec, powerOn=False)

        # 在 DC 的默认虚拟机文件夹下开始克隆
        task = template.Clone(folder=dc.vmFolder, name=new_name, spec=clonespec)
        self._wait_for_task(task)
        return f"虚拟机 {new_name} 克隆任务已完成"

    def delete_vm(self, vm_name):
        """安全删除虚拟机：先关机后销毁"""
        vm = self._get_obj_by_name(vim.VirtualMachine, vm_name)
        if not vm:
            raise Exception(f"未找到名为 {vm_name} 的虚拟机")

        if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
            self._wait_for_task(vm.PowerOff())

        self._wait_for_task(vm.Destroy_Task())
        return f"虚拟机 {vm_name} 已成功删除"