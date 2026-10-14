# vCenter AIops 整体收尾 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Continue task-by-task without requesting approval between tasks. The controller owns integration and final review; implementers must not spawn agents.

**Goal:** 完成已批准 PRD 的全部适用命令及离线交付，逐项暴露实机验收缺口，不再按零散命令中断用户。

**Architecture:** 保留统一 vcenter-aiops CLI、逐叶子契约和现有确认执行引擎。用明确的 Provider 路由接入各领域，避免继续扩张 VM 条件分支；所有真实任务复用意图、回执、核对与审计。业务域分文件，注册表只聚合。

**Tech Stack:** Python >=3.10、pyVmomi、SQLite、PyYAML；加密/MCP 依赖按需可选，不能在模块导入时安装。

**Spec:** docs/prd/vcenter-ops-3.0-prd.md（1.2，已审批）。本计划取代旧计划中未完成项的执行次序，不改变 PRD。

## Global Constraints

- 产品名为 vCenter AIops，唯一公共命令为 `vcenter-aiops`，Python 包为 `vcenter_aiops`。
- 兼容目标为 vSphere 6.5、6.7、7.0、8.0；模拟通过不能代替实机验证。
- 不保留 `scripts/handler.py --action ...`，不提供旧命令别名或转发兼容层。
- 不连接真实 vCenter，不外发通知，不迁移本机真实凭据；只实现代码及离线测试。
- 已有工作留在当前 `codex/vcenter-aiops-3` 分支，不创建额外功能工作树；不推送、合并或发布。
- 当前代码为未提交基线；使用文件快照生成任务审查 diff，不将其他现有改动混入任务提交。代理不执行 git add/commit。
- 业务输出统一 Result，不泄露凭据；SDK 对象不穿透 Provider；未知提交结果不得重发，普通预览不得写远端。
- 每项先写失败测试再实现，任务结束运行完整离线测试并记录实际证据，不注册占位命令。

## Task 1: 领域 Provider 路由与注册契约

**Files:** 新增 `vcenter-aiops/src/vcenter_aiops/application/providers.py`；修改 `domain/contracts.py`、`application/commands/changes.py`、`application/commands/plans.py`；新增 `tests/test_provider_routing.py`。现有 `application/registry.py` 的公共导入与所有已注册 CLI 路径保持有效。

**Interfaces:**
- `ProviderRouter(si, providers=None)` 提供当前 Engine 使用的 `preflight(command, params)`、`bind_steps(steps)`、`matches(expected, actual)`、`submit(command, params, binding)`、`observe(receipt, binding)`、`verify(command, params, binding, observation)`、`cancel(receipt, binding)`。
- `Command` 增加可选 `provider_kind: str = "vm"`，作为可信注册表元数据，现有命令保持默认路由。`describe()` 输出该字段。
- 默认 `vm` Provider 为现有 `Mutations(si)`，新增领域后通过显式可信映射接入。`providers` 是构造时注入的受控实例映射，用于后续领域及离线测试；不得从计划任意 import 类名。
- 路由后的 binding 加 `provider_kind`，固定到摘要中。向旧 Provider 传递前移除此路由字段，保持旧 binding 比较语义。
- submit/verify 同时检查注册命令归属与 binding 归属，observe/cancel 仅接受已注册的 Provider 键。未知/不匹配路由在远端调用前抛 OperationError。
- `bind_steps` 对同 Provider 的计划调用其既有投影；跨 Provider 计划先明确返回 `plan_dependency_unsupported`，Task 9 再接入跨领域类型化引用，不能不安全地逐步对现状校验。
- 三个应用入口 changes/plans 使用统一 Router；保留原 Mutations 的注入测试可维护适配，但不以复制执行器提供第二写路径。

- [ ] 写失败测试：现有 vm 电源预览/执行与原行为一致；额外受控 Provider 的 binding、submit、observe、verify、cancel 均按归属路由；篡改 provider_kind 不调用任一提交；未知 kind 明确错误；同域投影保留，跨域组合拒绝；help 不导入 pyVmomi。

```python
def test_wrong_provider_binding_never_submits(self):
    binding = router.preflight("vm power-on", {"vm_id": "vm-1"})
    binding["provider_kind"] = "unknown"
    with self.assertRaises(OperationError):
        router.submit("vm power-on", {"vm_id": "vm-1"}, binding)
    self.assertEqual(vm_provider.submissions, [])
```

- [ ] 运行定向测试，保存预期失败输出。
- [ ] 实现最小路由，接入应用处理器；不实现下一任务的业务命令。
- [ ] 运行 `PYTHONPATH=vcenter-aiops/src /tmp/vcenter-aiops-build-20260909/bin/python -m unittest discover -s vcenter-aiops/tests -q`，自查后提交报告文件，不提交 Git。

## Task 2: 集群与主机维护

交付 `cluster create/delete/add-host/remove-host/configure`、`host maintenance-enter/maintenance-exit`。Provider 位于 `providers/vsphere/clusters.py` 与 `hosts.py`，处理器/命令契约分别放 `application/commands/clusters.py` 与领域注册文件。对 vCenter 版本、许可证、实体身份、权限、空集群和维护模式进行预检。add-host 凭据只用受保护引用与明确证书指纹；remove-host 区分移出集群与注销，禁止隐式清空资源。每种操作都有成功、权限/前置条件失败、丢回执和后置校验测试，通过 Router 接入统一 Engine。

**实施分片（同一任务顺序审查，不并行写代码）：** 2a 主机维护、2b 集群生命周期及配置、2c 主机加入/移出。2c 使用现有 `env:NAME` 引用契约，Task 4 接入统一密钥解析；不等待密钥库而引入明文参数。

2026-09-26 审查修正：2a 中依赖 DRS 的撤离先引入最小共享 `licenses.py` 只读许可适配器，2b 复用并扩展。不能以当前启用配置代替功能授权；未知许可拒绝相关撤离，普通无撤离维护不要求 DRS 授权。任务观察/取消也须核对当前服务端身份，不能只比较初始化缓存。

**Task 2a 细化契约：**
- 新建 `providers/vsphere/hosts.py`、`application/commands/hosts.py`、`application/registrations/hosts.py`、`tests/test_host_maintenance.py`；Router 注册可信 `host` Provider，主注册表聚合领域命令。
- 两个独立远端写叶子均要求 `host_id`；提供 `task_timeout` 秒（默认 300，范围 1–86400）及现有 WRITE_OPTIONS。enter 额外提供 `evacuate_powered_off_vms` 默认 false、`allow_drs_migration` 默认 false；这两项授权也进入 binding 摘要。
- 精确 host-N、vCenter UUID、主机 hardware.systemInfo.uuid、parent、连接/维护状态绑定；版本检查仍为 6.5/6.7/7.0/8.0，权限 `Host.Config.Maintenance`。SDK 缺字段/无法确定关键状态不可视为安全。
- enter 预览列出 VM 身份与电源、DRS 模式及影响说明。不隐式关机；有开机 VM 且未显式允许 DRS 迁移则拒绝，允许时也须 fullyAutomated DRS 才提交，并告知容量不足仍可能失败。显式 PoweredOff 撤离也须显示范围。vSAN 管理不在 PRD 范围，发现启用或无法判断 vSAN 时拒绝进入，不依赖默认数据迁移行为。exit 不创建额外撤离操作。
- `EnterMaintenanceMode_Task(timeout=..., evacuatePoweredOffVms=...)` 与 `ExitMaintenanceMode_Task(timeout=...)` 使用真实 SDK 方法，不混用客户端等待超时。预检与提交前核对包含受影响 VM 集合，状态变化需重新确认。
- Provider 完整实现 Engine 协议，独立多主机步骤可用；同主机的进入/退出组合未实现安全投影前明确拒绝，不能以当前状态盲目预检未来步骤。
- task 回执绑定 server UUID、task-N；读取 info.key、info.entity 检查归属；只有远端真实 RequestCanceled 才为 cancelled。后置校验主机身份和维护状态，不用 task success 代替。
- 可以抽取无 VM 假设的内部任务适配器供此后 cluster Provider 使用，但不得复制 VM 执行器或改变现有 Mutations 的语义。
- TDD 覆盖进入/退出成功，真实 SDK 参数、disabledMethod/权限/身份/版本/状态拒绝、DRS 显式授权、vSAN 拒绝、错任务归属、丢回执不重发、后置不满足、确认前零写入。完整离线测试后记录报告与独立审查。

**API 核对入口：** Broadcom [HostSystem](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.HostSystem.html)、[ClusterComputeResource](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.ClusterComputeResource.html)、[Folder](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.Folder.html)。注意维护操作可能触发全自动 DRS；创建集群返回对象而非 Task；移出集群不等于注销。实现其余分片前继续核对具体 API。

**2b/2c 继续实施时必须处理：**
- HA/DRS 配置只设置用户指定字段，`modify=True`，不得用默认值重置其他配置。DRS 的 enabled 字段自 7.0 弃用，不能把设置 manual/最低激进度冒充同义的完全禁用；提供明确的 automation 参数并按版本解释实际能力。
- 许可证读取不得导出 licenseKey。不得仅凭版本、产品名或当前功能启用推断许可；证据缺失时返回不确定/拒绝启用。许可证适配器应独立可测试，不静默使用已经弃用且当前平台不支持的探测。
- remove-host 定义为移到同数据中心精确 host folder，使用 Folder.MoveIntoFolder_Task，仅传一个 host；不调用注销或销毁。预览显示随主机迁移的 VM/资源影响；不满足已批准范围则拒绝。具体权限按源集群、主机和目的目录分别核对。
- cluster create 的同步对象回执也必须在提交前保存意图，回执丢失仍禁止按名称盲认/重复创建。delete 要求无主机、无 VM、无子资源池且对象身份未变化。

**Task 2b 细化契约：**
- 新建 `providers/vsphere/clusters.py`、`providers/vsphere/licenses.py`、`application/commands/clusters.py`、`application/registrations/clusters.py` 与领域测试；通过可信 `cluster` Provider 接入 Router，不给 VM Provider 增加集群业务分支。
- `cluster create`：folder_id、name 必填；HA 默认关闭，DRS 自动化默认 manual；新增资源不能隐式启用自动迁移。精确 host folder，绑定 vCenter/folder/父数据中心、同名冲突及创建配置；使用 CreateClusterEx，立即记录新对象 MoRef 的同步回执，核对父目录/名称/配置后成功。
- `cluster configure`：cluster_id 必填，至少提供 ha_enabled、drs_enabled、drs_automation(manual/partiallyAutomated/fullyAutomated)、drs_vmotion_rate(1–5) 之一；不设置用户未选字段，拒绝自相矛盾组合。7/8 对 drs_enabled 明确拒绝弃用语义，并指向 drs_automation；不偷偷将 false 翻译为 manual。开启/改变自动模式展示可能引发的迁移影响。
- `cluster delete`：cluster_id 必填，精确 domain-cN；要求主机集合为空、根资源池无 VM/子资源池；如果关键属性不可读或对象类型不是 ClusterComputeResource 则拒绝。dangerous 摘要与二次确认复用现有 destructive 风险。
- 绑定不仅包含 cluster ID，还包括父目录/资源池身份、主机集合、关键配置与风险影响；版本/disabledMethod/相关权限和提交前实时复查。创建锁定目标目录，配置/删除锁定集群；同目标依赖计划在安全投影实现前拒绝。
- `licenses.py` 从现代 QueryAssignedLicenses 的精确实体记录解析所需 feature 证据，不返回 licenseKey，不把 inUseFeatures 当作完整授权清单。无授权、过期、诊断不满足、无法解释的许可数据均明确拒绝功能启用。检查器接收受控测试数据，可被 Provider 单元测试注入；运行时不能由计划提供“许可通过”布尔值。没有主机的空集群可创建关闭 HA/非自动 DRS 配置；功能启用许可没有证据则不冒充已授权。
- 测试真实 ClusterConfigSpecEx 字段、modify=True、不隐式移除/销毁资源、空集群与所有拒绝分支、同步创建响应丢失、错误任务归属/后置配置不满足、计划摘要变化、没有确认零写入。许可证 parser 的输入样例注明来源，非官方字段仅作明确候选适配，不宣称全版本实测。

许可研究入口：[LicenseAssignmentManager](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.LicenseAssignmentManager.html)、[LicenseInfo](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.LicenseManager.LicenseInfo.html)、[Broadcom 许可 feature 示例](https://knowledge.broadcom.com/external/article/381426)。旧 CheckLicenseFeature/FeatureInfo 已弃用，不应作为现代平台唯一事实来源。

**Task 2c 细化契约：**

**2026-09-26 用户审批覆盖：** 用户选择 A，当前只交付 remove-host；自动 add-host 按严格指纹政策延期，不注册占位命令，不保留可达的凭据转发/加入执行路径，不增加 CA 回退授权开关。以下 add-host 设计内容保留为历史研究，不是当前实施授权。审查回归须验证旧命令/旧计划/直接 Provider 调用均不能触发凭据读取或远端加入。原始 PRD 清单仍记录此延期项，不能借此宣称150叶子全部完成。

- 新建 `providers/vsphere/membership.py`，复用 2b 的集群身份/许可与共享任务适配，扩充集群领域注册及独立处理器；提供两个叶子，不增加注销主机命令。
- add-host 参数为 cluster_id、hostname、username、password_ref、ssl_thumbprint（均必填）、port（默认 443，1–65535）、expected_host_uuid（必填），另有公共写选项。必须使用已知受信任指纹，不自动接受服务端返回的未知证书，不 force 接管其他 vCenter。密码值只在 Provider 调用期间解析，计划/异常/日志均不保存值。
- 预检使用目标数据中心 QueryConnectionInfoViaSpec 的只读连接信息，固定主机硬件 UUID、版本、许可、VM/资源影响及集群成员状态。若已被其他 vCenter 管理、UUID 不符、未知许可/证书或不支持集群则拒绝。新主机有现存 VM 或资源层级需要隐式重排时先明确拒绝，要求用户独立处理，不静默丢弃源资源池。
- 唯一写调用为目标集群 AddHost_Task，asConnected=True、force=False；提交前重取信息，返回的 task 结果必须为固定硬件 UUID 的 HostSystem 且 parent 为目标集群。主机加入后不自动退出维护或执行其他配置。
- remove-host 参数为 cluster_id、host_id、folder_id（均必填），及公共写选项。必须维护模式、同数据中心 host folder，无关联 VM/子资源层级待迁移；双确认后调用目的 Folder.MoveIntoFolder_Task(list=[host])，不调用 Destroy/Disconnect/Unregister。预览/结果明确“保留在 vCenter，转为独立主机”。后置核对同硬件 UUID、独立 ComputeResource 及目的目录。
- 覆盖指纹格式/证书异常、凭据未设置、主机 UUID 改变、已管理、许可失败、含 VM、非维护、跨数据中心、权限缺失、提交前状态变更、响应丢失、错误 task/result UUID 等测试；把 SDK 异常替换为不含秘密的稳定错误，不重发不确定结果。
- 2c 初始支持 env:NAME 受保护引用；4a 替换共享解析器时必须复跑秘密不进入 SQLite/JSON/日志测试。

2c API 来源：[Datacenter](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.Datacenter.html)、[HostConnectSpec](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.ConnectSpec.html)、[HostConnectInfo](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.ConnectInfo.html)。构建目标 SDK 的实际属性与方法也需检查，不能仅按最新文档假定低版本字段存在。

## Task 3: VM 创建、磁盘、模板与 ISO

交付 `vm create`、磁盘 reconfigure、`template list/inspect/convert`、`deploy iso/unmount-iso/linked-clone`。创建规格包含精确 folder/pool/host/datastore/network、CPU/内存/磁盘/Guest ID/硬件版本；用目标能力校验，不硬编码最新上限。创建任务结果绑定新 VM 身份；磁盘扩容不可补偿。模板转换不改名不开机；ISO 限定存储文件与光驱；链接克隆固定快照及父依赖。构造真实 pyVmomi spec，测试提交字段与拒绝分支。

实施分片为 3a 空白 VM 创建、3b 磁盘及 ISO、3c 模板查询/转换与链接克隆。创建有独立的 `creation` Provider，避免强迫不存在的新 VM 通过原 Mutations.vm() 身份检查；已存在 VM 的动作仍复用 vm Provider，以小型 devices/media/placement 辅助模块拆分规范与能力校验，不复制执行引擎。

3a 新建 `providers/vsphere/creation.py`、`providers/vsphere/hardware.py`、`application/commands/creation.py`、`application/registrations/creation.py` 与 `tests/test_vm_creation.py`。必填参数包括 name/folder_id/pool_id/host_id/datastore_id/network_id/guest_id/hardware_version/cpu/memory_gb/disk_gb；所有放置均为精确 ID，不自动分配 IP 或开机。Engine 回执使用任务的结果对象，核对新 VM UUID、配置与放置。

3a 使用目标 EnvironmentBrowser.QueryConfigOption 查询指定虚拟硬件版本与主机，检查 Guest 描述、CPU/内存范围及推荐控制器/NIC 的可用性。SDK 9.1.0.0 实际字段为 `hardwareOptions.numCPU`（允许整数列表），不是臆造的 numCPUs.max；`hardwareOptions.memoryMB` 是 LongOption。Guest 描述为 `supportedMaxCPUs`、`supportedMinMemMB`、`supportedMaxMemMB`、`supportedDiskControllerList`、`supportedEthernetCard`；较新可选字段在 6.5 返回缺失时按已知旧字段判断，不以缺失代表 unlimited。所有上限来自服务端，不硬编码最新产品上限。

3a 测试应包含字面量支持列表 [1,2,4] 拒绝 CPU 3、Guest 上限低于硬件上限、指定硬件版本不匹配、空间/权限/放置冲突、真实 ConfigSpec/VirtualDisk/网卡字段、创建响应丢失不重发、task 结果错误身份，以及不开机/不分配 IP。含既存路径/磁盘的高级导入不混进空白创建命令。

3b 新建 devices.py、media.py 作为现有 VM Provider 的专用规格/预检辅助模块。磁盘调整通过 vm reconfigure 的强类型磁盘列表，逐项固定 device key、原容量和新容量；支持增加新磁盘和扩容，不隐式删除或缩容。关机、快照/加密/RDM 等不满足可支持条件时先拒绝。容量单位与字节/KB 换算显示清楚，目标容量来自实际存储/硬件能力；执行后按具体设备核对。扩容不可补偿必须进入计划与回滚结果，不能因为同一步还有 CPU/内存就显示整步已恢复。修改设备导致后续计划状态无法推演时明确拒绝依赖组合。

3b 的 ISO 命令固定 VM、光驱 device key、datastore ID 和相对文件路径；只编辑已存在光驱，不隐藏新增控制器/启动操作。装载使用经过验证的 ISO 文件和数据存储访问权限，卸载只断开并清除光盘介质，不删除 ISO。预检不触发文件下载，路径规则复用存储浏览的安全边界。测试错误光驱类型、ISO 路径穿越、不可访问存储、输入对象与设备绑定改变、真实编辑规格及后置状态。

3c template list/inspect 是明确的模板查询（不将普通 VM 混入），convert 要求精确模板和目标 pool/host，仅 MarkAsVirtualMachine，不改名不开机。linked-clone 固定父 VM UUID 和 snapshot ID，使用真实 CloneSpec/RelocateSpec 的链接磁盘语义，记录父依赖并校验所有磁盘与放置可支持。无快照、快照非该 VM、不可链接 backing 或加密条件不明时拒绝，不回退完整克隆。输出与计划保留父依赖，后续清理必须识别且拒绝破坏现存子对象依赖。模板和链接克隆各自覆盖成功、权限/身份失败、响应丢失、后置核对测试。

## Task 4: 凭据、历史、预设、策略与缓存

交付 `secret list/set/delete/rotate`、`history list/show`、`preset list/show/save/delete/from-history/from-vm`、`policy inspect/check`、`cache status/refresh/invalidate`。密钥主密钥与密文分离，安全输入无 CLI 明文值，无 get；加密依赖缺失明确拒绝。历史/预设只复用经过校验的参数，不继承授权；缓存标明时间/来源且不用于代替写前实时预检；策略只解释限制，不签发任意授权。配置并发、错误主密钥、secret 泄漏扫描与缓存跨 Profile 隔离纳入测试。

实施分为 4a 密钥与共享引用解析、4b 历史/预设/策略、4c 缓存。4a 统一解析既有 env 引用与新的 secret 引用，供 Profile、host、Guest 和通知复用，不允许各 Provider 自行实现明文存储。

用户方案A修订后，自动主机加入及其凭据解析器已移除；4a 不得为完成“host 接入”而恢复该延期功能，只整合仍然存在的 Profile/Guest/通知调用方。

4a 的输入约束：密钥值仅通过终端隐藏输入或显式 stdin 读取，拒绝明文 `--value`；set 不覆盖已有同名项，rotate 替换精确名称的密钥值并递增修订号（不是轮换主密钥），delete 精确删除。主密钥由独立环境引用提供，禁止自动写到密文目录。列表只返回名称、修订号、时间，不返回密文或明文。错误主密钥、损坏密文、无加密依赖必须明确失败，不能生成一个新库覆盖旧数据。密钥库为本地全局命名空间，拒绝误导性的 Profile 过滤；网络连接仍需显式 Profile。测试使用临时随机密钥，不读取用户真实环境秘密。

4a 接口落点：新增 `infrastructure/secrets.py`（密文持久化）、`infrastructure/credentials.py`（引用校验与解析）、`application/commands/secrets.py` 和领域注册。修改 `infrastructure/config.py` 的 Profile 凭据引用校验、`providers/vsphere/connection.py` 及 2c 成员管理的解析入口，保留 env 引用行为。沿用现有本地独占锁与原子替换边界，不另写无锁配置管理器；秘密值不进入 Store 的 operations/plans/audit。新增密钥库与引用测试，复跑连接、Profile、成员管理的失败与泄漏回归。库格式、主密钥来源和可选依赖在实施前写入任务 brief，不临时自动安装依赖或生成用户主密钥。

## Task 5: Guest 原子操作

交付 `vm guest-exec/guest-exec-output/guest-process-status/guest-output/guest-upload/guest-download/guest-customize`。新 `providers/vsphere/guest.py` 将 Tools、OS、Guest 凭据和 transfer URL 校验与进程启动/查询分开；明示 program/arguments，不自动重写脚本。执行输出是通过明确输出重定向方案采集的文件，不伪造 stdout；输出采集组合进入计划。上传下载有精确路径、大小、覆盖策略、TLS/端点约束，禁止泄漏凭据或把 Guest 输出当指令。覆盖 Linux/Windows spec、退出码、超时、进程丢失、传输中断。

## Task 6: OVA 与 OVF 部署

交付 `deploy ova/ovf`：安全描述文件解析与 OVA 解包，拒绝外部实体、路径穿越、符号链接和异常体积；映射文件/网络/放置与硬件能力。NFC lease 心跳、进度、超时及上传端点证书验证；中断记录本次对象，不默认销毁清理。分文件为归档校验、OVF spec、NFC 传输、应用状态；每层独立失败注入，不因 HTTPS 错误换不验证 TLS。

## Task 7: 资产、事件、配额、IP 与告警重置

交付 `inventory export`、`events list`、`quota check`、`ip check/available/expire`、`alarm reset`。查询批量分页、唯一身份解析和敏感内容转义。IP 探测阴性是 unknown，不等于 available；过期且关联未知部署的租约不自动释放。告警 reset 的底层批量 API 仅 6.7+，范围无法精确到单告警时必须显示真实过滤范围、匹配清单和数量；6.5 或无等价能力明确不支持，不冒充单对象重置。危险范围仍须两次确认。

## Task 8: 扫描、调查报告、通知与调度

交付 PRD 的 scan、attention/summary/investigate、notify、schedule/scheduler 全部叶子。扫描独立持久化，单 Profile 失败可 partial；事件/日志仅证据，不自动修复。HTML 转义不可信内容。通知默认关闭，仅受保护引用端点、已授权摘要/完整内容；outbox 去重、有限退避、未知发送结果不得假报成功。调度需持久化、进程身份/心跳、单实例锁、重叠抑制、错过周期合并和显式时区，无进程不得显示 running。

## Task 9: 类型化编排、批量制备与 TTL

交付跨领域 Plan 引用、`deploy batch-clone/batch`、`vm guest-provision/clean-slate` 与 TTL 全部叶子。允许声明式绑定前序输出，但禁止 shell 插值、任意 Python 方法和旧确认继承。执行每步前固定已解析身份并核对已批准约束；不能凭占位值提交。TTL 默认提醒，删除模式独立持久授权，撤销/身份变化/前提不满足立即停止。cleanup 精确对象并复用 Engine，不通配符授权、不隐式强制关机。失败恢复与补偿保留已完成证据。

## Task 10: MCP 与命令契约一致性

交付可选 `mcp serve`，逐叶子工具、共享应用调用，不 shell 包装。写工具只产生预览；用户确认的 plan apply 必须独立可达且不能自行替用户签授权。stdio 无非协议 stdout，敏感本机管理命令默认隐藏。补齐各命令的输入/输出 schema、权限、版本矩阵、异步/超时/幂等与补偿元数据；新增领域注册表按模块聚合，拒绝重复 command/operation ID。

## Task 11: 数据迁移与中文 Skill 发布

交付 migration inspect/apply/verify：SQLite backup API、源不变、目标幂等；旧配置/预设/租约/历史按明示映射，未知字段报告；旧任务待核对、TTL 提醒、旧确认不导入。真实凭据迁移另需授权，不自动读取本机 .env。迁移及源备份验证后才安排旧目录切换。中文 Skill 与依赖说明同步，ZIP 排除测试/缓存/真实配置/凭据，wheel 必须源码逐文件校验。

## Task 12: 整体验收

对照独立的逐命令清单验证 PRD AC-01–29：缺任何功能不能宣布完整完成。运行完整离线测试、异常注入、分支覆盖、干净构建与隔离安装、Skill 行为测试和全分支代码审查。实际环境矩阵单独记录 6.5/6.7/7.0/8.0 的未验证/阻断条件；无授权不进行真实写入，不推送 GitHub。保留所有剩余缺口与证据，不将暂不支持伪装成功。
