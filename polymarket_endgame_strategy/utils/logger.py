"""
日志模块
提供结构化日志记录和彩色输出
支持按时间轮转日志文件
"""

import logging
import sys
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# 自定义主题
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "red bold",
    "success": "green bold",
    "trade": "magenta bold",
    "price": "blue",
})

console = Console(theme=custom_theme)

# 全局日志实例
_logger: Optional[logging.Logger] = None


def setup_logger(
    name: str = "polymarket_endgame",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_dir: Optional[str] = None,
    rotate_hours: int = 4
) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        name: 日志名称
        level: 日志级别
        log_file: 日志文件路径（可选，单文件模式）
        log_dir: 日志目录（可选，启用时间轮转）
        rotate_hours: 日志轮转间隔（小时），默认4小时
    
    Returns:
        配置好的日志记录器
    """
    global _logger
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 清除现有处理器
    logger.handlers.clear()
    
    # Rich 控制台处理器
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        markup=True,
    )
    rich_handler.setLevel(level)
    rich_format = logging.Formatter("%(message)s")
    rich_handler.setFormatter(rich_format)
    logger.addHandler(rich_handler)
    
    # 时间轮转文件处理器（按4小时分割）
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "strategy.log")
        
        # TimedRotatingFileHandler: 每4小时轮转一次
        rotating_handler = TimedRotatingFileHandler(
            log_path,
            when="H",           # 按小时
            interval=rotate_hours,  # 每4小时
            backupCount=42,     # 保留7天的日志 (7*24/4=42)
            encoding="utf-8"
        )
        rotating_handler.setLevel(level)
        rotating_handler.suffix = "%Y%m%d_%H%M%S.log"  # 文件后缀格式
        
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        rotating_handler.setFormatter(file_format)
        logger.addHandler(rotating_handler)
        
        logger.info(f"📁 日志文件: {log_path} (每{rotate_hours}小时轮转)")
    
    # 单文件处理器（如果指定）
    elif log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """获取日志实例"""
    global _logger
    if _logger is None:
        _logger = setup_logger()
    return _logger


class TradeLogger:
    """交易专用日志记录器"""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or get_logger()
    
    def log_scan_start(self):
        """记录扫描开始"""
        self.logger.info("[cyan]🔍 开始扫描尾盘市场...[/cyan]")
    
    def log_market_found(self, market_question: str, minutes_left: float, price: float):
        """记录发现符合条件的市场"""
        self.logger.info(
            f"[success]📊 发现目标市场[/success]\n"
            f"   问题: {market_question[:50]}...\n"
            f"   剩余时间: {minutes_left:.1f} 分钟\n"
            f"   当前价格: [price]{price:.2f}[/price]"
        )
    
    def log_entry_signal(self, market_question: str, price: float, size: float):
        """记录进场信号"""
        self.logger.info(
            f"[trade]🚀 进场信号触发![/trade]\n"
            f"   市场: {market_question[:50]}...\n"
            f"   价格: [price]{price:.2f}[/price]\n"
            f"   数量: {size:.2f} USDC"
        )
    
    def log_order_placed(self, order_type: str, side: str, price: float, order_id: str):
        """记录订单提交"""
        self.logger.info(
            f"[success]✅ {order_type}订单已提交[/success]\n"
            f"   方向: {side}\n"
            f"   价格: [price]{price:.2f}[/price]\n"
            f"   订单ID: {order_id}"
        )
    
    def log_order_filled(self, side: str, price: float, size: float):
        """记录订单成交"""
        self.logger.info(
            f"[success]💰 订单成交![/success]\n"
            f"   方向: {side}\n"
            f"   价格: [price]{price:.2f}[/price]\n"
            f"   数量: {size:.2f}"
        )
    
    def log_position_update(self, market_id: str, pnl: float, pnl_pct: float):
        """记录持仓更新"""
        pnl_color = "green" if pnl >= 0 else "red"
        self.logger.info(
            f"[info]📈 持仓更新[/info]\n"
            f"   市场: {market_id[:20]}...\n"
            f"   盈亏: [{pnl_color}]{pnl:+.2f} USDC ({pnl_pct:+.2f}%)[/{pnl_color}]"
        )
    
    def log_error(self, message: str, error: Optional[Exception] = None):
        """记录错误"""
        error_msg = f"\n   错误: {str(error)}" if error else ""
        self.logger.error(f"[error]❌ {message}[/error]{error_msg}")
    
    def log_warning(self, message: str):
        """记录警告"""
        self.logger.warning(f"[warning]⚠️ {message}[/warning]")
    
    def log_stats(self, total_trades: int, winning_trades: int, total_pnl: float):
        """记录统计信息"""
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        pnl_color = "green" if total_pnl >= 0 else "red"
        self.logger.info(
            f"[info]📊 交易统计[/info]\n"
            f"   总交易: {total_trades}\n"
            f"   胜率: {win_rate:.1f}%\n"
            f"   总盈亏: [{pnl_color}]{total_pnl:+.2f} USDC[/{pnl_color}]"
        )
