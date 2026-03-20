# VMWare vCenter 术语

本文档定义了 VMWare vCenter 使用专业术语解释说明。

---

## 常用术语解释

| 术语                      | 英文                             | 说明                                                  |
| ----------------------- | ------------------------------ | --------------------------------------------------- |
| vCenter                 | vCenter Server                 | VMware 虚拟化管理平台，集中管理 Datacenter、Cluster、Host、VM 等资源。 |
| Datacenter              | Datacenter                     | vCenter 下的资源容器，用于组织 Cluster、Host、VM 等对象。            |
| Cluster                 | Cluster                        | 由多个 Host 组成的资源池，支持 DRS（动态资源调度）、HA（高可用性）等功能。         |
| Host                    | Host                           | 运行 ESXi 的物理服务器，是虚拟机的承载平台。                           |
| VM                      | Virtual Machine                | 虚拟机，运行在 Host 上的逻辑计算资源，拥有独立操作系统。                     |
| Folder                  | Folder                         | 清单对象容器，用于对 VM、Host 等对象进行分组和管理。                      |
| Resource Pool           | Resource Pool                  | Cluster 内的资源子集，用于分配和隔离 CPU、内存等资源。                   |
| Template                | Template                       | 虚拟机模板，用于快速部署新的 VM。                                  |
| Datastore               | Datastore                      | 数据存储逻辑容器，用于保存 VM 文件、ISO 镜像等。                        |
| Datastore Cluster       | Datastore Cluster              | 多个 Datastore 的集合，支持存储资源的统一管理和策略分配。                  |
| vSwitch                 | Standard vSwitch               | ESXi 标准虚拟交换机，提供 VM 与物理网络连接，支持 VLAN。                 |
| Port Group              | Port Group                     | vSwitch 上的端口组，定义虚拟机的网络属性（VLAN、网络策略等）。               |
| vDS                     | Distributed vSwitch            | 分布式虚拟交换机，实现跨多个 Host 的统一网络管理。                        |
| vmnic                   | Physical NIC                   | 物理网卡，Host 通过它连接到物理网络。                               |
| DRS                     | Distributed Resource Scheduler | 动态资源调度器，根据负载自动平衡 VM 到不同 Host。                       |
| HA                      | High Availability              | 高可用性机制，当 Host 故障时自动重启 VM 到其他 Host。                  |
| vMotion                 | vMotion                        | 虚拟机迁移技术，可在不同 Host 之间迁移 VM 而不中断服务。                   |
| Management Network      | Management Network             | 管理网络，用于 Host 与 vCenter 之间通信。                        |
| VMkernel                | VMkernel Adapter               | 虚拟机管理内核适配器，支持 vMotion、存储访问、管理流量等。                   |
| Snapshot                | Snapshot                       | 虚拟机状态备份，可保存 VM 的磁盘、内存和设置状态。                         |
| Template Library        | Content Library                | 存储 VM 模板、ISO 镜像、脚本等资源的集中库。                          |
| NSX                     | NSX                            | VMware 网络虚拟化平台，实现微分段、防火墙和逻辑网络。                      |
| vSAN                    | vSAN                           | VMware 超融合存储，整合本地磁盘形成分布式存储池。                        |
| vCenter HA              | vCenter High Availability      | vCenter 自身的高可用部署机制。                                 |
| vSphere Replication     | vSphere Replication            | VM 数据异地或本地复制技术，用于灾备。                                |
| FT                      | Fault Tolerance                | VMware 高可用技术，可实现 VM 零停机容错。                          |
| vApp                    | vApp                           | 包含多个 VM 的逻辑应用容器，可整体管理资源和启动顺序。                       |
| Content Library         | Content Library                | 存储和管理 VM 模板、ISO 和其他文件的库。                            |
| Host Profile            | Host Profile                   | 标准化 Host 配置模板，用于快速部署和一致性管理。                         |
| Resource Reservation    | Resource Reservation           | 为 VM 或 Resource Pool 保留 CPU / 内存资源。                 |
| Resource Limit          | Resource Limit                 | 限制 VM 或 Resource Pool 可使用的最大 CPU / 内存资源。            |
| Resource Share          | Resource Share                 | 定义 VM / Resource Pool 在资源竞争下的优先级。                   |
| vSphere Client          | vSphere Client                 | Web 或 HTML5 客户端，用于管理 vSphere 环境。                    |
| vSphere Web Client      | vSphere Web Client             | 基于 Web 的管理界面，用于访问 vCenter 功能。                       |
| Host Profile            | Host Profile                   | 标准化 Host 配置，用于批量部署或检查一致性。                           |
| vMotion Network         | vMotion Network                | 专用网络，用于虚拟机迁移流量。                                     |
| Fault Tolerance Logging | FT Logging                     | 记录 Fault Tolerance 虚拟机的操作和同步状态。                     |
