"""
风险管理模块
控制仓位、敞口和止损
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from config.settings import Settings, get_settings
from models.market import Position, OrderSide
from utils.logger import get_logger


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskMetrics:
    """风险指标"""
    total_exposure: float = 0.0
    max_exposure: float = 0.0
    exposure_pct: float = 0.0
    open_positions: int = 0
    max_positions: int = 10
    unrealized_pnl: float = 0.0
    max_drawdown: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    last_update: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RiskAlert:
    """风险警报"""
    level: RiskLevel
    message: str
    metric_name: str
    current_value: float
    threshold: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


class RiskManager:
    """
    风险管理器
    监控和控制交易风险
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        """
        初始化风险管理器
        
        Args:
            settings: 配置
        """
        self.settings = settings or get_settings()
        self.logger = get_logger()
        
        # 风险参数
        self.max_total_exposure = self.settings.max_total_exposure
        self.max_position_size = self.settings.max_position_size
        self.max_positions = 10  # 最大同时持仓数
        self.max_loss_per_trade = 0.05  # 单笔最大亏损比例 5%
        self.max_daily_loss = 0.10  # 日最大亏损比例 10%
        
        # 状态跟踪
        self._current_exposure: float = 0.0
        self._daily_pnl: float = 0.0
        self._daily_start: datetime = datetime.utcnow().replace(hour=0, minute=0, second=0)
        self._peak_equity: float = 0.0
        self._current_drawdown: float = 0.0
        
        # 黑名单（暂时禁止交易的市场）
        self._blacklist: Set[str] = set()
        self._blacklist_expiry: Dict[str, datetime] = {}
        
        # 警报历史
        self._alerts: List[RiskAlert] = []
    
    def can_open_position(
        self,
        position_size: float,
        market_id: str
    ) -> tuple[bool, str]:
        """
        检查是否可以开新仓位
        
        Args:
            position_size: 仓位大小（USDC）
            market_id: 市场 ID
        
        Returns:
            (是否允许, 原因)
        """
        # 检查黑名单
        if self._is_blacklisted(market_id):
            return False, "市场在黑名单中"
        
        # 检查仓位大小
        if position_size > self.max_position_size:
            return False, f"仓位超过限制 ({position_size:.2f} > {self.max_position_size:.2f})"
        
        # 检查总敞口
        new_exposure = self._current_exposure + position_size
        if new_exposure > self.max_total_exposure:
            return False, f"总敞口将超过限制 ({new_exposure:.2f} > {self.max_total_exposure:.2f})"
        
        # 检查日亏损限制
        if self._daily_pnl < -self.max_daily_loss * self.max_total_exposure:
            return False, f"已达日亏损限制"
        
        return True, "OK"
    
    def calculate_position_size(
        self,
        entry_price: float,
        available_balance: float
    ) -> float:
        """
        计算建议的仓位大小
        
        Args:
            entry_price: 进场价格
            available_balance: 可用余额
        
        Returns:
            建议的仓位大小（USDC）
        """
        # 可用敞口
        available_exposure = self.max_total_exposure - self._current_exposure
        
        # 风险调整
        # 价格越接近1，风险越小
        risk_factor = 1.0 - entry_price  # 0.95 -> 0.05
        risk_adjusted_size = self.max_position_size * (1.0 - risk_factor * 2)
        
        # 取最小值
        position_size = min(
            risk_adjusted_size,
            available_exposure,
            available_balance,
            self.max_position_size
        )
        
        return max(position_size, 0)
    
    def update_exposure(self, delta: float):
        """
        更新当前敞口
        
        Args:
            delta: 敞口变化量
        """
        self._current_exposure += delta
        self._current_exposure = max(0, self._current_exposure)
    
    def update_pnl(self, pnl: float):
        """
        更新盈亏
        
        Args:
            pnl: 盈亏金额
        """
        # 检查是否需要重置日统计
        now = datetime.utcnow()
        if now.date() > self._daily_start.date():
            self._daily_pnl = 0.0
            self._daily_start = now.replace(hour=0, minute=0, second=0)
        
        self._daily_pnl += pnl
        
        # 更新最大回撤
        if self._daily_pnl > self._peak_equity:
            self._peak_equity = self._daily_pnl
        else:
            drawdown = self._peak_equity - self._daily_pnl
            self._current_drawdown = max(self._current_drawdown, drawdown)
    
    def add_to_blacklist(self, market_id: str, duration_minutes: int = 60):
        """
        将市场添加到黑名单
        
        Args:
            market_id: 市场 ID
            duration_minutes: 黑名单持续时间（分钟）
        """
        self._blacklist.add(market_id)
        self._blacklist_expiry[market_id] = datetime.utcnow() + timedelta(minutes=duration_minutes)
        self.logger.warning(f"市场已加入黑名单: {market_id[:20]}... ({duration_minutes}分钟)")
    
    def _is_blacklisted(self, market_id: str) -> bool:
        """检查市场是否在黑名单"""
        if market_id not in self._blacklist:
            return False
        
        # 检查是否过期
        expiry = self._blacklist_expiry.get(market_id)
        if expiry and datetime.utcnow() > expiry:
            self._blacklist.discard(market_id)
            del self._blacklist_expiry[market_id]
            return False
        
        return True
    
    def check_stop_loss(self, position: Position) -> bool:
        """
        检查是否需要止损
        
        Args:
            position: 持仓
        
        Returns:
            是否需要止损
        """
        if position.unrealized_pnl_pct < -self.max_loss_per_trade * 100:
            return True
        return False
    
    def get_metrics(self) -> RiskMetrics:
        """获取风险指标"""
        exposure_pct = self._current_exposure / self.max_total_exposure * 100 if self.max_total_exposure > 0 else 0
        
        # 计算风险等级
        if exposure_pct > 90 or self._daily_pnl < -self.max_daily_loss * self.max_total_exposure * 0.8:
            risk_level = RiskLevel.CRITICAL
        elif exposure_pct > 70 or self._daily_pnl < -self.max_daily_loss * self.max_total_exposure * 0.5:
            risk_level = RiskLevel.HIGH
        elif exposure_pct > 50:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW
        
        return RiskMetrics(
            total_exposure=self._current_exposure,
            max_exposure=self.max_total_exposure,
            exposure_pct=exposure_pct,
            max_drawdown=self._current_drawdown,
            risk_level=risk_level
        )
    
    def create_alert(
        self,
        level: RiskLevel,
        message: str,
        metric_name: str,
        current_value: float,
        threshold: float
    ):
        """创建风险警报"""
        alert = RiskAlert(
            level=level,
            message=message,
            metric_name=metric_name,
            current_value=current_value,
            threshold=threshold
        )
        self._alerts.append(alert)
        
        if level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            self.logger.warning(f"⚠️ 风险警报 [{level.value}]: {message}")
        else:
            self.logger.info(f"📊 风险提示 [{level.value}]: {message}")
    
    def get_recent_alerts(self, hours: int = 24) -> List[RiskAlert]:
        """获取最近的警报"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return [a for a in self._alerts if a.timestamp > cutoff]
    
    def reset_daily_stats(self):
        """重置日统计"""
        self._daily_pnl = 0.0
        self._peak_equity = 0.0
        self._current_drawdown = 0.0
        self._daily_start = datetime.utcnow().replace(hour=0, minute=0, second=0)
        self.logger.info("日统计已重置")
