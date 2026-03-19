"""
Module: scripts.client
Description: vCenter API 连接客户端封装，支持上下文管理与会话状态检查。
Author: xiaofei
Date: 2026-03-19
"""

import ssl
import logging
from typing import Optional, Any
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl

# 设置模块级日志，方便外部配置
logger = logging.getLogger(__name__)

class VCenterClient:
    """
    vCenter 连接客户端封装类。
    
    使用示例:
        with VCenterClient(host, user, pwd) as si:
            content = si.RetrieveContent()
            # 执行业务逻辑
    """

    def __init__(self, host: str, user: str, pwd: str, port: int = 443, timeout: int = 60):
        """
        初始化连接参数。
        
        :param host: vCenter 主机地址 (IP 或域名)
        :param user: 登录用户名 (如: administrator@vsphere.local)
        :param pwd: 登录密码
        :param port: 端口，默认为 HTTPS 443
        :param timeout: 连接超时时间（秒）
        """
        self.host = host
        self.user = user
        self.pwd = pwd
        self.port = port
        self.timeout = timeout
        
        # 受管对象实例 (ServiceInstance)
        self.si: Optional[vim.ServiceInstance] = None
        
        # 默认忽略 SSL 证书验证。
        # 注意：在极高安全要求的环境中，应通过 ssl.create_default_context(cafile=...) 加载私有 CA
        self._ssl_context = ssl._create_unverified_context()

    def is_connected(self) -> bool:
        """
        检查当前会话是否依然有效。
        通过尝试访问简单的 API 属性来验证 Session 是否超时。
        """
        if not self.si:
            return False
        try:
            # 尝试获取服务器时间，这是一个轻量级操作
            self.si.CurrentTime()
            return True
        except (vmodl.RuntimeFault, Exception):
            return False

    def connect(self) -> vim.ServiceInstance:
        """
        建立 vCenter 连接。如果已存在有效连接则直接返回。
        
        :return: pyVmomi ServiceInstance 对象
        :raises ConnectionError: 认证失败或网络无法到达时抛出
        """
        if self.is_connected():
            logger.debug(f"vCenter [{self.host}] 会话已存在且有效，跳过重复连接。")
            return self.si

        try:
            logger.info(f"正在尝试连接 vCenter: {self.host} (User: {self.user})...")
            
            # SmartConnect 是连接入口
            self.si = SmartConnect(
                host=self.host,
                user=self.user,
                pwd=self.pwd,
                port=self.port,
                sslContext=self._ssl_context,
                connectionPoolTimeout=self.timeout
            )
            
            logger.info(f"vCenter [{self.host}] 连接建立成功。")
            return self.si

        except vim.fault.InvalidLogin:
            logger.error(f"vCenter 连接失败: 用户名或密码错误 (Host: {self.host})")
            raise ConnectionError("vSphere 认证失败：请检查凭据")
        except Exception as e:
            logger.error(f"vCenter 系统错误: {str(e)}")
            # 将原始异常包装，方便上层业务处理
            raise ConnectionError(f"无法建立 vCenter 通信: {e}")

    def disconnect(self) -> None:
        """
        安全断开当前会话。
        """
        if self.si:
            try:
                logger.info(f"正在关闭 vCenter [{self.host}] 的会话连接...")
                Disconnect(self.si)
                logger.info("会话已安全释放。")
            except Exception as e:
                logger.warning(f"断开连接时发生非预期异常: {e}")
            finally:
                self.si = None

    def __enter__(self) -> vim.ServiceInstance:
        """上下文管理：进入 with 块时自动连接"""
        return self.connect()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """上下文管理：离开 with 块时自动断开"""
        self.disconnect()

    def __repr__(self) -> str:
        """优雅的对象表示，方便调试"""
        return f"<VCenterClient(host='{self.host}', user='{self.user}', connected={self.is_connected()})>"