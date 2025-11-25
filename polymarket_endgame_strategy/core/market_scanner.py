"""
市场扫描模块
扫描即将结束的市场
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Callable, Awaitable
from dataclasses import dataclass

from config.settings import Settings, get_settings
from models.market import Market, TradeSignal, OrderSide
from core.api_client import PolymarketClient
from utils.logger import get_logger, TradeLogger
from utils.helpers import format_time_remaining


@dataclass
class ScanResult:
    """扫描结果"""
    markets: List[Market]
    signals: List[TradeSignal]
    scan_time: datetime
    total_scanned: int
    qualified_count: int


class MarketScanner:
    """
    市场扫描器
    定期扫描即将结束的市场，寻找交易机会
    """
    
    def __init__(
        self,
        client: PolymarketClient,
        settings: Optional[Settings] = None
    ):
        """
        初始化扫描器
        
        Args:
            client: API 客户端
            settings: 配置
        """
        self.client = client
        self.settings = settings or get_settings()
        self.logger = get_logger()
        self.trade_logger = TradeLogger()
        
        # 扫描状态
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        
        # 已处理的市场（避免重复信号）
        self._processed_markets: set = set()
        
        # 信号回调
        self._signal_callbacks: List[Callable[[TradeSignal], Awaitable[None]]] = []
    
    def add_signal_callback(
        self,
        callback: Callable[[TradeSignal], Awaitable[None]]
    ):
        """
        添加信号回调
        
        Args:
            callback: 当发现交易信号时调用的回调函数
        """
        self._signal_callbacks.append(callback)
    
    async def scan_once(self) -> ScanResult:
        """
        执行一次扫描
        
        Returns:
            扫描结果
        """
        self.trade_logger.log_scan_start()
        
        scan_time = datetime.utcnow()
        signals: List[TradeSignal] = []
        qualified_markets: List[Market] = []
        
        try:
            # 获取活跃市场
            markets = await self.client.get_markets(active=True, closed=False, limit=500)
            total_scanned = len(markets)
            
            self.logger.debug(f"获取到 {total_scanned} 个活跃市场")
            
            # 筛选即将结束的市场
            for market in markets:
                if self._is_qualified_market(market):
                    qualified_markets.append(market)
                    
                    # 检查价格信号
                    signal = await self._check_price_signal(market)
                    if signal:
                        signals.append(signal)
                        
                        # 调用回调
                        for callback in self._signal_callbacks:
                            try:
                                await callback(signal)
                            except Exception as e:
                                self.logger.error(f"信号回调执行失败: {e}")
            
            self.logger.info(
                f"扫描完成: {total_scanned} 个市场, "
                f"{len(qualified_markets)} 个符合条件, "
                f"{len(signals)} 个交易信号"
            )
            
            return ScanResult(
                markets=qualified_markets,
                signals=signals,
                scan_time=scan_time,
                total_scanned=total_scanned,
                qualified_count=len(qualified_markets)
            )
            
        except Exception as e:
            self.logger.error(f"扫描失败: {e}")
            return ScanResult(
                markets=[],
                signals=[],
                scan_time=scan_time,
                total_scanned=0,
                qualified_count=0
            )
    
    def _is_qualified_market(self, market: Market) -> bool:
        """
        检查市场是否符合条件
        
        Args:
            market: 市场信息
        
        Returns:
            是否符合条件
        """
        # 检查是否已关闭或已结算
        if market.closed or market.resolved:
            return False
        
        # 检查是否有结束时间
        if market.end_date is None:
            return False
        
        # 检查剩余时间是否在目标范围内
        minutes_to_end = market.minutes_to_end
        if minutes_to_end is None:
            return False
        
        min_time = self.settings.min_time_to_end
        max_time = self.settings.max_time_to_end
        
        if not (min_time <= minutes_to_end <= max_time):
            return False
        
        # 检查是否有 tokens
        if not market.tokens:
            return False
        
        return True
    
    async def _check_price_signal(self, market: Market) -> Optional[TradeSignal]:
        """
        检查市场是否有价格信号
        
        Args:
            market: 市场信息
        
        Returns:
            交易信号或 None
        """
        # 避免重复处理
        if market.condition_id in self._processed_markets:
            return None
        
        entry_threshold = self.settings.entry_price
        exit_price = self.settings.exit_price
        
        # 检查 Yes 选项
        yes_token = market.get_yes_token()
        if yes_token and yes_token.price >= entry_threshold:
            # 获取最新价格确认
            prices = await self.client.get_market_prices(yes_token.token_id)
            current_price = prices.get("ask", yes_token.price)
            
            if current_price >= entry_threshold and current_price < exit_price:
                self._processed_markets.add(market.condition_id)
                
                self.trade_logger.log_market_found(
                    market.question,
                    market.minutes_to_end or 0,
                    current_price
                )
                
                return TradeSignal(
                    market=market,
                    token_id=yes_token.token_id,
                    outcome="YES",
                    side=OrderSide.BUY,
                    entry_price=current_price,
                    exit_price=exit_price
                )
        
        # 检查 No 选项（同样逻辑）
        no_token = market.get_no_token()
        if no_token and no_token.price >= entry_threshold:
            prices = await self.client.get_market_prices(no_token.token_id)
            current_price = prices.get("ask", no_token.price)
            
            if current_price >= entry_threshold and current_price < exit_price:
                self._processed_markets.add(market.condition_id)
                
                self.trade_logger.log_market_found(
                    market.question,
                    market.minutes_to_end or 0,
                    current_price
                )
                
                return TradeSignal(
                    market=market,
                    token_id=no_token.token_id,
                    outcome="NO",
                    side=OrderSide.BUY,
                    entry_price=current_price,
                    exit_price=exit_price
                )
        
        return None
    
    async def start(self):
        """启动持续扫描"""
        if self._running:
            self.logger.warning("扫描器已在运行")
            return
        
        self._running = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        self.logger.info("市场扫描器已启动")
    
    async def stop(self):
        """停止扫描"""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None
        self.logger.info("市场扫描器已停止")
    
    async def _scan_loop(self):
        """扫描循环"""
        while self._running:
            try:
                await self.scan_once()
                await asyncio.sleep(self.settings.scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"扫描循环错误: {e}")
                await asyncio.sleep(5)  # 错误后等待5秒
    
    def clear_processed(self):
        """清除已处理记录"""
        self._processed_markets.clear()
        self.logger.info("已清除处理记录")
    
    def get_stats(self) -> dict:
        """获取扫描统计"""
        return {
            "running": self._running,
            "processed_markets": len(self._processed_markets),
            "callbacks_registered": len(self._signal_callbacks)
        }
