# scripts/client.py
"""
vCenter 连接客户端
"""

from pyVim.connect import SmartConnect, Disconnect
import ssl
import logging

class VCenterClient:
    """封装 vCenter 连接逻辑，支持上下文管理 (with 语句)"""
    def __init__(self, host, user, pwd, port=443):
        self.host = host
        self.user = user
        self.pwd = pwd
        self.port = port
        self.si = None
        # 忽略 SSL 证书验证（在 O&M 环境中常用）
        self.context = ssl._create_unverified_context()

    def connect(self):
        try:
            self.si = SmartConnect(
                host=self.host,
                user=self.user,
                pwd=self.pwd,
                port=self.port,
                sslContext=self.context
            )
            return self.si
        except Exception as e:
            logging.error(f"无法连接到 vCenter {self.host}: {str(e)}")
            raise

    def disconnect(self):
        if self.si:
            Disconnect(self.si)

    def __enter__(self):
        self.connect()
        return self.si

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()