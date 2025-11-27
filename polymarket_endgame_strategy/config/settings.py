"""
配置管理模块
管理所有交易参数
"""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """策略配置参数"""
    
    # ============================================
    # Polymarket 凭证（只需要私钥）
    # ============================================
    polymarket_private_key: str = Field(
        default="",
        description="Polygon 钱包私钥（用于签名交易）"
    )
    
    # ============================================
    # 交易参数
    # ============================================
    entry_price: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="进场价格阈值（0.95 = 95 cents）"
    )
    max_entry_price: float = Field(
        default=0.96,
        ge=0.0,
        le=1.0,
        description="最高进场价格（超过此价格不下单，利润空间太小）"
    )
    exit_price: float = Field(
        default=0.99,
        ge=0.0,
        le=1.0,
        description="限价出场价格（0.99 = 99 cents）"
    )
    min_time_to_end: int = Field(
        default=5,
        ge=1,
        description="最小剩余时间（分钟）"
    )
    max_time_to_end: int = Field(
        default=15,
        ge=1,
        description="最大剩余时间（分钟）"
    )
    max_position_size: float = Field(
        default=100.0,
        ge=0.0,
        description="单笔最大仓位（USDC）"
    )
    max_total_exposure: float = Field(
        default=500.0,
        ge=0.0,
        description="最大总敞口（USDC）"
    )
    
    # ============================================
    # 网络设置
    # ============================================
    polygon_rpc_url: str = Field(
        default="https://polygon-rpc.com",
        description="Polygon RPC URL"
    )
    use_testnet: bool = Field(
        default=False,
        description="是否使用测试网"
    )
    
    # ============================================
    # 监控设置
    # ============================================
    scan_interval: int = Field(
        default=10,
        ge=1,
        description="扫描间隔（秒）"
    )
    debug_mode: bool = Field(
        default=False,
        description="是否启用调试模式"
    )
    
    # ============================================
    # CLOB API 端点
    # ============================================
    clob_api_url: str = Field(
        default="https://clob.polymarket.com",
        description="CLOB API URL (mainnet)"
    )
    clob_api_url_testnet: str = Field(
        default="https://clob.polymarket.com",
        description="CLOB API URL (testnet)"
    )
    gamma_api_url: str = Field(
        default="https://gamma-api.polymarket.com",
        description="Gamma API URL (市场数据)"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        # 支持从环境变量读取，前缀为空
        env_prefix = ""
    
    @property
    def active_clob_url(self) -> str:
        """获取当前使用的 CLOB API URL"""
        return self.clob_api_url_testnet if self.use_testnet else self.clob_api_url
    
    @property
    def entry_price_cents(self) -> int:
        """进场价格（cents）"""
        return int(self.entry_price * 100)
    
    @property
    def exit_price_cents(self) -> int:
        """出场价格（cents）"""
        return int(self.exit_price * 100)
    
    def validate_credentials(self) -> bool:
        """验证私钥是否已配置"""
        return bool(self.polymarket_private_key)


@lru_cache()
def get_settings() -> Settings:
    """获取配置实例（单例模式）"""
    return Settings()
