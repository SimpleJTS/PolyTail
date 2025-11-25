"""
辅助函数模块
提供通用的辅助函数
"""

from datetime import datetime, timedelta
from typing import Optional, Union
import re


def format_price(price: float, decimals: int = 2) -> str:
    """
    格式化价格显示
    
    Args:
        price: 价格（0-1之间）
        decimals: 小数位数
    
    Returns:
        格式化后的价格字符串
    """
    cents = price * 100
    return f"{cents:.{decimals}f}¢"


def format_time_remaining(end_time: Optional[datetime]) -> str:
    """
    格式化剩余时间
    
    Args:
        end_time: 结束时间
    
    Returns:
        格式化后的剩余时间字符串
    """
    if end_time is None:
        return "未知"
    
    now = datetime.utcnow()
    delta = end_time - now
    
    if delta.total_seconds() <= 0:
        return "已结束"
    
    total_minutes = delta.total_seconds() / 60
    
    if total_minutes < 1:
        return f"{delta.seconds} 秒"
    elif total_minutes < 60:
        return f"{total_minutes:.1f} 分钟"
    elif total_minutes < 1440:  # 24 hours
        hours = total_minutes / 60
        return f"{hours:.1f} 小时"
    else:
        days = total_minutes / 1440
        return f"{days:.1f} 天"


def safe_float(value: Union[str, float, int, None], default: float = 0.0) -> float:
    """
    安全转换为浮点数
    
    Args:
        value: 要转换的值
        default: 默认值
    
    Returns:
        转换后的浮点数
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Union[str, float, int, None], default: int = 0) -> int:
    """
    安全转换为整数
    
    Args:
        value: 要转换的值
        default: 默认值
    
    Returns:
        转换后的整数
    """
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def truncate_string(s: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    截断字符串
    
    Args:
        s: 原始字符串
        max_length: 最大长度
        suffix: 截断后缀
    
    Returns:
        截断后的字符串
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def parse_token_id(token_id: str) -> Optional[str]:
    """
    解析并验证Token ID格式
    
    Args:
        token_id: Token ID字符串
    
    Returns:
        验证后的Token ID或None
    """
    if not token_id:
        return None
    # Token ID 通常是很长的数字字符串
    if re.match(r'^\d+$', token_id):
        return token_id
    return None


def calculate_position_size(
    available_balance: float,
    price: float,
    max_position: float,
    risk_pct: float = 0.1
) -> float:
    """
    计算仓位大小
    
    Args:
        available_balance: 可用余额
        price: 当前价格
        max_position: 最大仓位
        risk_pct: 风险百分比
    
    Returns:
        建议的仓位大小（USDC）
    """
    # 基于可用余额的风险比例
    risk_based = available_balance * risk_pct
    
    # 不超过最大仓位
    position = min(risk_based, max_position)
    
    # 确保有足够的流动性
    if position < 1.0:  # 最小1 USDC
        return 0.0
    
    return position


def is_valid_price_for_entry(price: float, threshold: float) -> bool:
    """
    检查价格是否适合进场
    
    Args:
        price: 当前价格
        threshold: 进场价格阈值
    
    Returns:
        是否适合进场
    """
    return price >= threshold


def estimate_slippage(order_size: float, liquidity: float) -> float:
    """
    估算滑点
    
    Args:
        order_size: 订单大小
        liquidity: 流动性
    
    Returns:
        估算的滑点百分比
    """
    if liquidity <= 0:
        return 1.0  # 100% 滑点（无法交易）
    
    # 简单的滑点估算模型
    impact_ratio = order_size / liquidity
    
    if impact_ratio < 0.01:
        return 0.001  # 0.1%
    elif impact_ratio < 0.05:
        return 0.005  # 0.5%
    elif impact_ratio < 0.1:
        return 0.01   # 1%
    else:
        return 0.02   # 2%+


def format_order_summary(
    side: str,
    price: float,
    size: float,
    market_question: str
) -> str:
    """
    格式化订单摘要
    
    Args:
        side: 买/卖方向
        price: 价格
        size: 数量
        market_question: 市场问题
    
    Returns:
        格式化的订单摘要
    """
    return (
        f"{'买入' if side.upper() == 'BUY' else '卖出'} | "
        f"价格: {format_price(price)} | "
        f"数量: {size:.2f} USDC | "
        f"市场: {truncate_string(market_question, 40)}"
    )
