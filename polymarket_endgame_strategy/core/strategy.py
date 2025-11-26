"""
尾盘交易策略
整合扫描、监控和执行模块
支持普通市场和 Updown 周期性市场
"""

import asyncio
from datetime import datetime
from typing import Optional, List

from config.settings import Settings, get_settings
from models.market import TradeSignal, Market, MarketOutcome, OrderSide
from core.api_client import PolymarketClient
from core.order_executor import OrderExecutor, TradeRecord
from core.updown_scanner import UpdownScanner, UpdownMarket
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
        self.updown_scanner: Optional[UpdownScanner] = None  # Updown 市场扫描器
        self.executor: Optional[OrderExecutor] = None
        
        # 运行状态
        self._running = False
        self._start_time: Optional[datetime] = None
        
        # Updown 扫描统计
        self._updown_scanned = 0
        self._updown_signals = 0
    
    async def initialize(self):
        """初始化策略组件"""
        self.logger.info("=" * 50)
        self.logger.info("🎰 Polymarket 尾盘交易策略")
        self.logger.info("=" * 50)
        
        # 验证配置
        if not self.settings.validate_credentials():
            self.logger.warning(
                "⚠️ 私钥未配置，将以只读模式运行（无法执行交易）"
            )
        else:
            self.logger.info("✅ 私钥已配置，可以执行交易")
        
        # 检查 py-clob-client 是否安装
        try:
            from py_clob_client.client import ClobClient
            self.logger.info("✅ py-clob-client 已安装")
        except ImportError:
            self.logger.error("❌ py-clob-client 未安装，无法下单！请运行: pip install py-clob-client")
        
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
        
        # 初始化 Updown 扫描器（专门扫描 5m/15m 周期性市场）
        self.updown_scanner = UpdownScanner(self.settings)
        
        # 初始化订单执行器
        self.executor = OrderExecutor(self.client, self.settings)
        
        self.logger.info("✅ 策略组件初始化完成")
    
    async def _scan_updown_markets(self):
        """扫描 Updown 周期性市场"""
        try:
            markets = await self.updown_scanner.scan(
                min_minutes=self.settings.min_time_to_end,
                max_minutes=self.settings.max_time_to_end
            )
            
            self._updown_scanned += len(markets)
            
            for market in markets:
                # 检查 Up 选项
                if market.up_price >= self.settings.entry_price:
                    self._updown_signals += 1
                    self.logger.info(
                        f"🎯 Updown 信号: {market.title}\n"
                        f"   Up: {market.up_price:.2%} | Down: {market.down_price:.2%}\n"
                        f"   剩余: {market.minutes_to_end:.1f} 分钟"
                    )
                    
                    # 创建交易信号
                    signal = self._create_signal_from_updown(market, "Up")
                    if signal:
                        await self._execute_trade(signal)
                
                # 检查 Down 选项
                elif market.down_price >= self.settings.entry_price:
                    self._updown_signals += 1
                    self.logger.info(
                        f"🎯 Updown 信号: {market.title}\n"
                        f"   Up: {market.up_price:.2%} | Down: {market.down_price:.2%}\n"
                        f"   剩余: {market.minutes_to_end:.1f} 分钟"
                    )
                    
                    signal = self._create_signal_from_updown(market, "Down")
                    if signal:
                        await self._execute_trade(signal)
                else:
                    # 没有达到进场价格，只记录
                    self.logger.debug(
                        f"📊 Updown: {market.title[:40]}... | "
                        f"Up: {market.up_price:.0%} Down: {market.down_price:.0%} | "
                        f"{market.minutes_to_end:.1f}min"
                    )
                        
        except Exception as e:
            self.logger.error(f"Updown 扫描错误: {e}")
    
    def _create_signal_from_updown(self, market: UpdownMarket, outcome: str) -> Optional[TradeSignal]:
        """从 Updown 市场创建交易信号"""
        try:
            token_id = market.up_token_id if outcome == "Up" else market.down_token_id
            price = market.up_price if outcome == "Up" else market.down_price
            
            if not token_id:
                return None
            
            # 创建 Market 对象
            market_obj = Market(
                condition_id=market.slug,
                question=market.title,
                end_date=market.end_date,
                active=market.active,
                tokens=[
                    MarketOutcome(token_id=market.up_token_id or "", outcome="Up", price=market.up_price),
                    MarketOutcome(token_id=market.down_token_id or "", outcome="Down", price=market.down_price),
                ]
            )
            
            return TradeSignal(
                market=market_obj,
                token_id=token_id,
                outcome=outcome,
                side=OrderSide.BUY,
                entry_price=price,
                exit_price=self.settings.exit_price
            )
        except Exception as e:
            self.logger.error(f"创建信号失败: {e}")
            return None
    
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
            
            # 主循环 - 定期扫描 Updown 市场
            while self._running:
                try:
                    # 扫描 Updown 市场
                    await self._scan_updown_markets()
                    
                    # 检查持仓
                    if self.executor.get_all_positions():
                        await self.executor.check_positions()
                    
                    # 打印统计
                    await self._print_stats()
                    
                    # 等待扫描间隔
                    await asyncio.sleep(self.settings.scan_interval)
                    
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
        
        runtime = datetime.utcnow() - self._start_time if self._start_time else None
        runtime_str = str(runtime).split('.')[0] if runtime else "N/A"
        
        self.logger.info(
            f"\n📊 运行统计 | 运行时间: {runtime_str}\n"
            f"   Updown: 扫描 {self._updown_scanned} 次, 信号 {self._updown_signals} 个\n"
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
            # 扫描 Updown 市场
            markets = await self.updown_scanner.scan(
                min_minutes=self.settings.min_time_to_end,
                max_minutes=self.settings.max_time_to_end
            )
            
            self.logger.info(f"\n扫描结果:")
            self.logger.info(f"  Updown 市场: {len(markets)} 个")
            
            for market in markets:
                self.logger.info(
                    f"\n  📌 {market.title}\n"
                    f"     Up: {market.up_price:.0%} | Down: {market.down_price:.0%}\n"
                    f"     剩余: {market.minutes_to_end:.1f} 分钟"
                )
            
            return markets
            
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
