"""
数据模型定义
定义市场、订单、交易信号等数据结构
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    GTC = "GTC"  # Good Till Cancelled
    FOK = "FOK"  # Fill or Kill
    GTD = "GTD"  # Good Till Date


class MarketOutcome(BaseModel):
    """市场选项结果"""
    token_id: str = Field(..., description="Token ID")
    outcome: str = Field(..., description="选项名称 (Yes/No)")
    price: float = Field(default=0.0, ge=0.0, le=1.0, description="当前价格")
    
    class Config:
        frozen = True


class Market(BaseModel):
    """市场数据模型"""
    condition_id: str = Field(..., description="市场条件ID")
    question_id: str = Field(default="", description="问题ID")
    question: str = Field(default="", description="市场问题")
    description: str = Field(default="", description="市场描述")
    
    # 时间信息
    end_date: Optional[datetime] = Field(default=None, description="结束时间")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    
    # 市场状态
    active: bool = Field(default=True, description="是否活跃")
    closed: bool = Field(default=False, description="是否已关闭")
    resolved: bool = Field(default=False, description="是否已结算")
    
    # Token信息
    tokens: List[MarketOutcome] = Field(default_factory=list, description="市场选项")
    
    # 流动性信息
    volume: float = Field(default=0.0, description="交易量")
    liquidity: float = Field(default=0.0, description="流动性")
    
    @property
    def minutes_to_end(self) -> Optional[float]:
        """距离结束的分钟数"""
        if self.end_date is None:
            return None
        
        # 获取当前 UTC 时间
        now = datetime.utcnow()
        end = self.end_date
        
        # 处理时区问题：如果 end_date 有时区信息，去掉它
        if end.tzinfo is not None:
            end = end.replace(tzinfo=None)
        
        delta = end - now
        return delta.total_seconds() / 60
    
    @property
    def is_ending_soon(self) -> bool:
        """是否即将结束（5-15分钟内）"""
        minutes = self.minutes_to_end
        if minutes is None:
            return False
        return 5 <= minutes <= 15
    
    def get_yes_token(self) -> Optional[MarketOutcome]:
        """获取 Yes 选项"""
        for token in self.tokens:
            if token.outcome.upper() == "YES":
                return token
        return None
    
    def get_no_token(self) -> Optional[MarketOutcome]:
        """获取 No 选项"""
        for token in self.tokens:
            if token.outcome.upper() == "NO":
                return token
        return None


class TradeSignal(BaseModel):
    """交易信号"""
    market: Market = Field(..., description="市场信息")
    token_id: str = Field(..., description="交易的Token ID")
    outcome: str = Field(..., description="选项 (Yes/No)")
    side: OrderSide = Field(..., description="交易方向")
    entry_price: float = Field(..., description="进场价格")
    exit_price: float = Field(..., description="目标出场价格")
    signal_time: datetime = Field(default_factory=datetime.utcnow, description="信号时间")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="信号置信度")
    
    @property
    def expected_profit_pct(self) -> float:
        """预期收益率"""
        if self.entry_price <= 0:
            return 0.0
        return (self.exit_price - self.entry_price) / self.entry_price * 100


class Position(BaseModel):
    """持仓信息"""
    market_id: str = Field(..., description="市场ID")
    token_id: str = Field(..., description="Token ID")
    outcome: str = Field(..., description="选项")
    side: OrderSide = Field(..., description="方向")
    
    # 持仓数据
    size: float = Field(default=0.0, description="持仓数量")
    entry_price: float = Field(default=0.0, description="入场均价")
    current_price: float = Field(default=0.0, description="当前价格")
    
    # 订单状态
    entry_order_id: Optional[str] = Field(default=None, description="入场订单ID")
    exit_order_id: Optional[str] = Field(default=None, description="出场订单ID")
    exit_price: float = Field(default=0.0, description="挂单出场价格")
    
    # 时间
    entry_time: Optional[datetime] = Field(default=None, description="入场时间")
    
    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏"""
        if self.side == OrderSide.BUY:
            return (self.current_price - self.entry_price) * self.size
        else:
            return (self.entry_price - self.current_price) * self.size
    
    @property
    def unrealized_pnl_pct(self) -> float:
        """未实现盈亏百分比"""
        if self.entry_price <= 0 or self.size <= 0:
            return 0.0
        cost = self.entry_price * self.size
        return self.unrealized_pnl / cost * 100


class OrderResult(BaseModel):
    """订单执行结果"""
    success: bool = Field(..., description="是否成功")
    order_id: Optional[str] = Field(default=None, description="订单ID")
    filled_size: float = Field(default=0.0, description="成交数量")
    filled_price: float = Field(default=0.0, description="成交价格")
    message: str = Field(default="", description="消息")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="时间戳")
