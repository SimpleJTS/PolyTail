"""
尾盘交易策略
整合扫描、监控和执行模块
"""

import asyncio
from datetime import datetime
from typing import Optional

from config.settings import Settings, get_settings
from models.market import TradeSignal
from core.api_client import PolymarketClient
from core.market_scanner import MarketScanner
from core.price_monitor import PriceMonitor
from core.order_executor import OrderExecutor, TradeRecord
from utils.logger import get_logger, TradeLogger


class EndgameStrategy:
    """
    尾盘交易策略
    
    策略逻辑:
    1. 持续扫描即将在 5-15 分钟内结束的市场
    2. 当发现价格 >= 95 cents 的选项时，买入
    3. 立即挂 99 cents 限价卖单
    4. 等待市场结算或限价单成交
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        """
        初始化策略
        
        Args:
            settings: 配置
        """
        self.settings = settings or get_settings()
        self.logger = get_logger()
        self.trade_logger = TradeLogger()
        
        # 初始化组件
        self.client: Optional[PolymarketClient] = None
        self.scanner: Optional[MarketScanner] = None
        self.monitor: Optional[PriceMonitor] = None
        self.executor: Optional[OrderExecutor] = None
        
        # 运行状态
        self._running = False
        self._start_time: Optional[datetime] = None
    
    async def initialize(self):
        """初始化策略组件"""
        self.logger.info("=" * 50)
        self.logger.info("🎰 Polymarket 尾盘交易策略")
        self.logger.info("=" * 50)
        
        # 验证配置
        if not self.settings.validate_credentials():
            self.logger.warning(
                "⚠️ API 凭证未配置完整，将以只读模式运行（无法执行交易）"
            )
        
        # 显示配置
        self.logger.info(f"📊 策略参数:")
        self.logger.info(f"   进场价格: {self.settings.entry_price * 100:.0f} cents")
        self.logger.info(f"   出场价格: {self.settings.exit_price * 100:.0f} cents")
        self.logger.info(f"   时间窗口: {self.settings.min_time_to_end}-{self.settings.max_time_to_end} 分钟")
        self.logger.info(f"   最大单笔: {self.settings.max_position_size} USDC")
        self.logger.info(f"   最大敞口: {self.settings.max_total_exposure} USDC")
        self.logger.info(f"   扫描间隔: {self.settings.scan_interval} 秒")
        self.logger.info("=" * 50)
        
        # 初始化 API 客户端
        self.client = PolymarketClient(self.settings)
        await self.client.connect()
        
        # 初始化扫描器
        self.scanner = MarketScanner(self.client, self.settings)
        
        # 初始化价格监控器
        self.monitor = PriceMonitor(self.client, self.settings)
        
        # 初始化订单执行器
        self.executor = OrderExecutor(self.client, self.settings)
        
        # 设置回调
        self.scanner.add_signal_callback(self._on_scanner_signal)
        self.monitor.add_signal_callback(self._on_monitor_signal)
        
        self.logger.info("✅ 策略组件初始化完成")
    
    async def _on_scanner_signal(self, signal: TradeSignal):
        """
        扫描器信号回调
        
        Args:
            signal: 交易信号
        """
        self.logger.info(f"📡 收到扫描器信号: {signal.market.question[:50]}...")
        
        # 添加到价格监控
        self.monitor.add_market(
            market=signal.market,
            token_id=signal.token_id,
            outcome=signal.outcome
        )
        
        # 如果价格已经满足条件，直接执行
        if signal.entry_price >= self.settings.entry_price:
            await self._execute_trade(signal)
    
    async def _on_monitor_signal(self, signal: TradeSignal):
        """
        价格监控器信号回调
        
        Args:
            signal: 交易信号
        """
        self.logger.info(f"📈 收到价格信号: {signal.market.question[:50]}...")
        await self._execute_trade(signal)
    
    async def _execute_trade(self, signal: TradeSignal):
        """
        执行交易
        
        Args:
            signal: 交易信号
        """
        if not self.settings.validate_credentials():
            self.logger.warning("⚠️ 无法执行交易：API 凭证未配置")
            self.logger.info(f"   信号详情: {signal.outcome} @ {signal.entry_price:.4f}")
            return
        
        record = await self.executor.execute_signal(signal)
        
        if record and record.status in ["entered", "exiting"]:
            self.logger.info("✅ 交易执行成功")
        elif record:
            self.logger.warning(f"⚠️ 交易状态: {record.status}")
    
    async def run(self):
        """运行策略"""
        if self._running:
            self.logger.warning("策略已在运行")
            return
        
        try:
            await self.initialize()
            
            self._running = True
            self._start_time = datetime.utcnow()
            
            self.logger.info("🚀 策略开始运行...")
            self.logger.info("按 Ctrl+C 停止策略")
            
            # 启动扫描器
            await self.scanner.start()
            
            # 启动价格监控
            await self.monitor.start()
            
            # 主循环 - 定期检查持仓和打印统计
            while self._running:
                try:
                    # 检查持仓
                    if self.executor.get_all_positions():
                        await self.executor.check_positions()
                    
                    # 打印统计（每分钟）
                    await self._print_stats()
                    
                    await asyncio.sleep(60)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"主循环错误: {e}")
                    await asyncio.sleep(5)
            
        except KeyboardInterrupt:
            self.logger.info("\n⏹️ 收到停止信号...")
        except Exception as e:
            self.logger.error(f"策略运行错误: {e}")
        finally:
            await self.stop()
    
    async def stop(self):
        """停止策略"""
        self.logger.info("正在停止策略...")
        self._running = False
        
        # 停止组件
        if self.scanner:
            await self.scanner.stop()
        
        if self.monitor:
            await self.monitor.stop()
        
        # 打印最终统计
        if self.executor:
            stats = self.executor.get_stats()
            self.trade_logger.log_stats(
                stats["total_trades"],
                stats["winning_trades"],
                stats["total_realized_pnl"]
            )
        
        # 关闭客户端
        if self.client:
            await self.client.close()
        
        self.logger.info("✅ 策略已停止")
    
    async def _print_stats(self):
        """打印运行统计"""
        if not self.executor:
            return
        
        stats = self.executor.get_stats()
        scanner_stats = self.scanner.get_stats() if self.scanner else {}
        monitor_stats = self.monitor.get_stats() if self.monitor else {}
        
        runtime = datetime.utcnow() - self._start_time if self._start_time else None
        runtime_str = str(runtime).split('.')[0] if runtime else "N/A"
        
        self.logger.info(
            f"\n📊 运行统计 | 运行时间: {runtime_str}\n"
            f"   扫描器: 已处理 {scanner_stats.get('processed_markets', 0)} 个市场\n"
            f"   监控器: 监控 {monitor_stats.get('monitored_count', 0)} 个市场, "
            f"触发 {monitor_stats.get('triggered_count', 0)} 次\n"
            f"   交易: {stats['total_trades']} 笔, "
            f"持仓 {stats['open_positions']} 个\n"
            f"   盈亏: 已实现 {stats['total_realized_pnl']:+.2f} USDC, "
            f"未实现 {stats['unrealized_pnl']:+.2f} USDC\n"
            f"   敞口: {stats['total_exposure']:.2f} / {self.settings.max_total_exposure} USDC"
        )
    
    async def run_once(self):
        """执行一次扫描（用于测试）"""
        await self.initialize()
        
        try:
            result = await self.scanner.scan_once()
            
            self.logger.info(f"\n扫描结果:")
            self.logger.info(f"  总扫描: {result.total_scanned} 个市场")
            self.logger.info(f"  符合条件: {result.qualified_count} 个")
            self.logger.info(f"  交易信号: {len(result.signals)} 个")
            
            for signal in result.signals:
                self.logger.info(
                    f"\n  📌 信号: {signal.market.question[:60]}...\n"
                    f"     选项: {signal.outcome}\n"
                    f"     价格: {signal.entry_price:.4f} → {signal.exit_price:.4f}\n"
                    f"     剩余: {signal.market.minutes_to_end:.1f} 分钟"
                )
            
            return result
            
        finally:
            await self.client.close()


class DryRunStrategy(EndgameStrategy):
    """
    模拟运行策略（不执行真实交易）
    """
    
    async def _execute_trade(self, signal: TradeSignal):
        """模拟交易执行"""
        self.logger.info(
            f"🔔 [模拟] 交易信号:\n"
            f"   市场: {signal.market.question[:50]}...\n"
            f"   选项: {signal.outcome}\n"
            f"   买入价: {signal.entry_price:.4f}\n"
            f"   卖出价: {signal.exit_price:.4f}\n"
            f"   预期收益: {signal.expected_profit_pct:.2f}%"
        )
