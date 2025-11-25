"""
价格监控模块
实时监控目标市场的价格变化
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional, List, Callable, Awaitable
from dataclasses import dataclass, field

from config.settings import Settings, get_settings
from models.market import Market, TradeSignal, OrderSide
from core.api_client import PolymarketClient
from utils.logger import get_logger
from utils.helpers import format_price


@dataclass
class PriceUpdate:
    """价格更新"""
    token_id: str
    market_id: str
    bid: float
    ask: float
    mid: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def spread(self) -> float:
        """买卖价差"""
        return self.ask - self.bid if self.bid > 0 else 0
    
    @property
    def spread_pct(self) -> float:
        """价差百分比"""
        if self.mid <= 0:
            return 0
        return self.spread / self.mid * 100


@dataclass 
class MonitoredMarket:
    """被监控的市场"""
    market: Market
    token_id: str
    outcome: str
    target_entry_price: float
    target_exit_price: float
    last_price: float = 0.0
    last_update: Optional[datetime] = None
    triggered: bool = False


class PriceMonitor:
    """
    价格监控器
    监控目标市场的价格，触发进场信号
    """
    
    def __init__(
        self,
        client: PolymarketClient,
        settings: Optional[Settings] = None
    ):
        """
        初始化监控器
        
        Args:
            client: API 客户端
            settings: 配置
        """
        self.client = client
        self.settings = settings or get_settings()
        self.logger = get_logger()
        
        # 监控的市场
        self._monitored: Dict[str, MonitoredMarket] = {}
        
        # 运行状态
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # 价格更新回调
        self._price_callbacks: List[Callable[[PriceUpdate], Awaitable[None]]] = []
        
        # 信号触发回调
        self._signal_callbacks: List[Callable[[TradeSignal], Awaitable[None]]] = []
    
    def add_market(
        self,
        market: Market,
        token_id: str,
        outcome: str,
        entry_price: Optional[float] = None,
        exit_price: Optional[float] = None
    ):
        """
        添加监控市场
        
        Args:
            market: 市场信息
            token_id: Token ID
            outcome: 选项 (Yes/No)
            entry_price: 进场价格阈值
            exit_price: 出场价格目标
        """
        entry = entry_price or self.settings.entry_price
        exit_ = exit_price or self.settings.exit_price
        
        monitored = MonitoredMarket(
            market=market,
            token_id=token_id,
            outcome=outcome,
            target_entry_price=entry,
            target_exit_price=exit_
        )
        
        self._monitored[token_id] = monitored
        self.logger.info(
            f"添加监控: {market.question[:50]}... | "
            f"Token: {token_id[:20]}... | "
            f"进场: {format_price(entry)} | 出场: {format_price(exit_)}"
        )
    
    def remove_market(self, token_id: str):
        """
        移除监控市场
        
        Args:
            token_id: Token ID
        """
        if token_id in self._monitored:
            del self._monitored[token_id]
            self.logger.info(f"移除监控: {token_id[:20]}...")
    
    def add_price_callback(
        self,
        callback: Callable[[PriceUpdate], Awaitable[None]]
    ):
        """添加价格更新回调"""
        self._price_callbacks.append(callback)
    
    def add_signal_callback(
        self,
        callback: Callable[[TradeSignal], Awaitable[None]]
    ):
        """添加信号触发回调"""
        self._signal_callbacks.append(callback)
    
    async def check_prices(self) -> List[PriceUpdate]:
        """
        检查所有监控市场的价格
        
        Returns:
            价格更新列表
        """
        updates: List[PriceUpdate] = []
        
        for token_id, monitored in list(self._monitored.items()):
            try:
                # 获取价格
                prices = await self.client.get_market_prices(token_id)
                
                update = PriceUpdate(
                    token_id=token_id,
                    market_id=monitored.market.condition_id,
                    bid=prices.get("bid", 0),
                    ask=prices.get("ask", 0),
                    mid=prices.get("mid", 0)
                )
                
                updates.append(update)
                
                # 更新监控状态
                monitored.last_price = update.ask
                monitored.last_update = update.timestamp
                
                # 调用价格回调
                for callback in self._price_callbacks:
                    try:
                        await callback(update)
                    except Exception as e:
                        self.logger.error(f"价格回调执行失败: {e}")
                
                # 检查是否触发信号
                if not monitored.triggered:
                    await self._check_signal(monitored, update)
                
            except Exception as e:
                self.logger.error(f"获取价格失败 {token_id[:20]}...: {e}")
        
        return updates
    
    async def _check_signal(
        self,
        monitored: MonitoredMarket,
        update: PriceUpdate
    ):
        """
        检查是否触发交易信号
        
        Args:
            monitored: 监控的市场
            update: 价格更新
        """
        # 检查价格是否达到进场条件
        current_price = update.ask
        
        if current_price >= monitored.target_entry_price:
            if current_price < monitored.target_exit_price:
                # 触发信号
                monitored.triggered = True
                
                signal = TradeSignal(
                    market=monitored.market,
                    token_id=monitored.token_id,
                    outcome=monitored.outcome,
                    side=OrderSide.BUY,
                    entry_price=current_price,
                    exit_price=monitored.target_exit_price
                )
                
                self.logger.info(
                    f"🚀 价格信号触发! "
                    f"{monitored.market.question[:30]}... | "
                    f"价格: {format_price(current_price)}"
                )
                
                # 调用信号回调
                for callback in self._signal_callbacks:
                    try:
                        await callback(signal)
                    except Exception as e:
                        self.logger.error(f"信号回调执行失败: {e}")
    
    async def start(self):
        """启动价格监控"""
        if self._running:
            self.logger.warning("价格监控器已在运行")
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self.logger.info("价格监控器已启动")
    
    async def stop(self):
        """停止价格监控"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        self.logger.info("价格监控器已停止")
    
    async def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                if self._monitored:
                    await self.check_prices()
                
                # 价格检查间隔较短（2秒）
                await asyncio.sleep(2)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"监控循环错误: {e}")
                await asyncio.sleep(5)
    
    def get_monitored_count(self) -> int:
        """获取监控市场数量"""
        return len(self._monitored)
    
    def get_all_monitored(self) -> List[MonitoredMarket]:
        """获取所有监控的市场"""
        return list(self._monitored.values())
    
    def clear_triggered(self):
        """清除已触发状态"""
        for monitored in self._monitored.values():
            monitored.triggered = False
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        triggered_count = sum(1 for m in self._monitored.values() if m.triggered)
        return {
            "running": self._running,
            "monitored_count": len(self._monitored),
            "triggered_count": triggered_count
        }
