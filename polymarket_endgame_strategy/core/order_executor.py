"""
订单执行模块
处理买入和卖出订单的执行
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from config.settings import Settings, get_settings
from models.market import (
    TradeSignal, Position, OrderSide, OrderResult
)
from core.api_client import PolymarketClient
from utils.logger import get_logger, TradeLogger
from utils.helpers import format_price, calculate_position_size


@dataclass
class TradeRecord:
    """交易记录"""
    signal: TradeSignal
    entry_order: Optional[OrderResult] = None
    exit_order: Optional[OrderResult] = None
    position: Optional[Position] = None
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    realized_pnl: float = 0.0
    status: str = "pending"  # pending, entered, exiting, closed, cancelled


class OrderExecutor:
    """
    订单执行器
    负责执行交易信号，管理进出场订单
    """
    
    def __init__(
        self,
        client: PolymarketClient,
        settings: Optional[Settings] = None
    ):
        """
        初始化执行器
        
        Args:
            client: API 客户端
            settings: 配置
        """
        self.client = client
        self.settings = settings or get_settings()
        self.logger = get_logger()
        self.trade_logger = TradeLogger()
        
        # 当前持仓
        self._positions: Dict[str, Position] = {}
        
        # 交易记录
        self._trade_records: List[TradeRecord] = []
        
        # 总敞口
        self._total_exposure: float = 0.0
        
        # 执行锁（避免并发问题）
        self._execution_lock = asyncio.Lock()
    
    async def execute_signal(self, signal: TradeSignal) -> Optional[TradeRecord]:
        """
        执行交易信号
        
        Args:
            signal: 交易信号
        
        Returns:
            交易记录或 None
        """
        async with self._execution_lock:
            # 检查是否已有该市场的持仓
            if signal.token_id in self._positions:
                self.logger.warning(f"已有该市场持仓，跳过: {signal.token_id[:20]}...")
                return None
            
            # 检查总敞口限制
            if self._total_exposure >= self.settings.max_total_exposure:
                self.logger.warning(
                    f"总敞口已达上限 ({self._total_exposure:.2f} USDC)，跳过交易"
                )
                return None
            
            # 计算仓位大小
            available_exposure = self.settings.max_total_exposure - self._total_exposure
            position_size = min(
                self.settings.max_position_size,
                available_exposure
            )
            
            if position_size < 1.0:
                self.logger.warning("可用仓位不足，跳过交易")
                return None
            
            # 创建交易记录
            record = TradeRecord(signal=signal)
            
            try:
                # 执行买入
                self.trade_logger.log_entry_signal(
                    signal.market.question,
                    signal.entry_price,
                    position_size
                )
                
                entry_result = await self._execute_entry(
                    signal,
                    position_size
                )
                
                record.entry_order = entry_result
                record.entry_time = datetime.utcnow()
                
                if not entry_result.success:
                    record.status = "cancelled"
                    self.trade_logger.log_error(
                        "买入失败",
                        Exception(entry_result.message)
                    )
                    self._trade_records.append(record)
                    return record
                
                # 创建持仓
                position = Position(
                    market_id=signal.market.condition_id,
                    token_id=signal.token_id,
                    outcome=signal.outcome,
                    side=OrderSide.BUY,
                    size=entry_result.filled_size or (position_size / signal.entry_price),
                    entry_price=entry_result.filled_price or signal.entry_price,
                    current_price=signal.entry_price,
                    entry_order_id=entry_result.order_id,
                    exit_price=signal.exit_price,
                    entry_time=datetime.utcnow()
                )
                
                self._positions[signal.token_id] = position
                self._total_exposure += position_size
                record.position = position
                record.status = "entered"
                
                self.trade_logger.log_order_placed(
                    "买入",
                    "BUY",
                    entry_result.filled_price or signal.entry_price,
                    entry_result.order_id or "N/A"
                )
                
                # 立即挂出限价卖单
                exit_result = await self._execute_exit(signal, position)
                record.exit_order = exit_result
                
                if exit_result.success:
                    position.exit_order_id = exit_result.order_id
                    record.status = "exiting"
                    
                    self.trade_logger.log_order_placed(
                        "限价卖出",
                        "SELL",
                        signal.exit_price,
                        exit_result.order_id or "N/A"
                    )
                else:
                    self.trade_logger.log_warning(
                        f"限价卖单失败: {exit_result.message}"
                    )
                
                self._trade_records.append(record)
                return record
                
            except Exception as e:
                self.logger.error(f"执行交易失败: {e}")
                record.status = "cancelled"
                self._trade_records.append(record)
                return record
    
    async def _execute_entry(
        self,
        signal: TradeSignal,
        position_size: float
    ) -> OrderResult:
        """
        执行进场订单
        
        Args:
            signal: 交易信号
            position_size: 仓位大小（USDC）
        
        Returns:
            订单结果
        """
        return await self.client.place_market_buy(
            token_id=signal.token_id,
            amount=position_size
        )
    
    async def _execute_exit(
        self,
        signal: TradeSignal,
        position: Position
    ) -> OrderResult:
        """
        执行出场订单（限价）
        
        Args:
            signal: 交易信号
            position: 持仓信息
        
        Returns:
            订单结果
        """
        return await self.client.place_limit_sell(
            token_id=signal.token_id,
            price=signal.exit_price,
            size=position.size
        )
    
    async def check_positions(self):
        """检查所有持仓状态"""
        for token_id, position in list(self._positions.items()):
            try:
                # 获取当前价格
                prices = await self.client.get_market_prices(token_id)
                position.current_price = prices.get("mid", position.current_price)
                
                self.trade_logger.log_position_update(
                    position.market_id,
                    position.unrealized_pnl,
                    position.unrealized_pnl_pct
                )
                
            except Exception as e:
                self.logger.error(f"检查持仓失败: {e}")
    
    async def close_position(self, token_id: str) -> Optional[OrderResult]:
        """
        平仓
        
        Args:
            token_id: Token ID
        
        Returns:
            订单结果
        """
        if token_id not in self._positions:
            return None
        
        position = self._positions[token_id]
        
        # 取消现有的限价卖单
        if position.exit_order_id:
            await self.client.cancel_order(position.exit_order_id)
        
        # 市价卖出
        result = await self.client.place_order(
            token_id=token_id,
            side=OrderSide.SELL,
            price=0.01,  # 最低价保证成交
            size=position.size,
            order_type="FOK"
        )
        
        if result.success:
            # 计算盈亏
            realized_pnl = (result.filled_price - position.entry_price) * position.size
            
            # 更新交易记录
            for record in self._trade_records:
                if record.position and record.position.token_id == token_id:
                    record.exit_order = result
                    record.exit_time = datetime.utcnow()
                    record.realized_pnl = realized_pnl
                    record.status = "closed"
                    break
            
            # 移除持仓
            cost = position.entry_price * position.size
            self._total_exposure -= cost
            del self._positions[token_id]
            
            self.trade_logger.log_order_filled(
                "SELL",
                result.filled_price,
                result.filled_size
            )
        
        return result
    
    async def close_all_positions(self):
        """平掉所有持仓"""
        for token_id in list(self._positions.keys()):
            await self.close_position(token_id)
    
    def get_position(self, token_id: str) -> Optional[Position]:
        """获取指定持仓"""
        return self._positions.get(token_id)
    
    def get_all_positions(self) -> List[Position]:
        """获取所有持仓"""
        return list(self._positions.values())
    
    def get_trade_records(self) -> List[TradeRecord]:
        """获取所有交易记录"""
        return self._trade_records
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        total_trades = len(self._trade_records)
        closed_trades = [r for r in self._trade_records if r.status == "closed"]
        winning_trades = [r for r in closed_trades if r.realized_pnl > 0]
        
        total_pnl = sum(r.realized_pnl for r in closed_trades)
        
        # 未实现盈亏
        unrealized_pnl = sum(p.unrealized_pnl for p in self._positions.values())
        
        return {
            "total_trades": total_trades,
            "open_positions": len(self._positions),
            "closed_trades": len(closed_trades),
            "winning_trades": len(winning_trades),
            "win_rate": len(winning_trades) / len(closed_trades) * 100 if closed_trades else 0,
            "total_realized_pnl": total_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_exposure": self._total_exposure
        }
