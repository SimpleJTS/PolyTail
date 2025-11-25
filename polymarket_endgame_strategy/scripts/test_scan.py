#!/usr/bin/env python3
"""
测试扫描脚本
用于测试市场扫描功能，不需要 API 凭证
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from config.settings import Settings
from core.api_client import PolymarketClient
from core.market_scanner import MarketScanner
from utils.logger import setup_logger, get_logger
from utils.helpers import format_price, format_time_remaining


async def main():
    """测试市场扫描"""
    setup_logger()
    logger = get_logger()
    
    logger.info("=" * 60)
    logger.info("🔍 Polymarket 市场扫描测试")
    logger.info("=" * 60)
    
    # 创建配置（使用更宽松的参数以便测试）
    settings = Settings(
        entry_price=0.90,  # 降低阈值以便找到更多市场
        exit_price=0.99,
        min_time_to_end=1,  # 更短的时间窗口
        max_time_to_end=60,  # 更长的时间窗口
    )
    
    logger.info(f"测试参数:")
    logger.info(f"  进场阈值: {settings.entry_price * 100:.0f} cents")
    logger.info(f"  时间窗口: {settings.min_time_to_end}-{settings.max_time_to_end} 分钟")
    
    async with PolymarketClient(settings) as client:
        # 获取市场列表
        logger.info("\n获取活跃市场...")
        markets = await client.get_markets(active=True, closed=False, limit=100)
        logger.info(f"获取到 {len(markets)} 个市场")
        
        # 显示一些市场示例
        logger.info("\n市场示例:")
        for i, market in enumerate(markets[:5]):
            time_left = format_time_remaining(market.end_date)
            yes_token = market.get_yes_token()
            no_token = market.get_no_token()
            
            yes_price = f"{yes_token.price:.2f}" if yes_token else "N/A"
            no_price = f"{no_token.price:.2f}" if no_token else "N/A"
            
            logger.info(
                f"\n  {i+1}. {market.question[:60]}...\n"
                f"     结束时间: {time_left}\n"
                f"     Yes: {yes_price} | No: {no_price}\n"
                f"     状态: {'活跃' if market.active else '不活跃'} | "
                f"{'已关闭' if market.closed else '未关闭'}"
            )
        
        # 使用扫描器
        logger.info("\n" + "=" * 60)
        logger.info("使用扫描器扫描符合条件的市场...")
        
        scanner = MarketScanner(client, settings)
        result = await scanner.scan_once()
        
        logger.info(f"\n扫描结果:")
        logger.info(f"  总扫描: {result.total_scanned} 个市场")
        logger.info(f"  符合时间条件: {result.qualified_count} 个")
        logger.info(f"  交易信号: {len(result.signals)} 个")
        
        if result.signals:
            logger.info("\n🎯 发现的交易信号:")
            for signal in result.signals:
                logger.info(
                    f"\n  市场: {signal.market.question[:50]}...\n"
                    f"  选项: {signal.outcome}\n"
                    f"  价格: {signal.entry_price:.4f} → {signal.exit_price:.4f}\n"
                    f"  预期收益: {signal.expected_profit_pct:.2f}%\n"
                    f"  剩余时间: {signal.market.minutes_to_end:.1f} 分钟"
                )
        
        if result.markets:
            logger.info("\n📊 符合时间条件的市场:")
            for market in result.markets[:10]:
                yes_token = market.get_yes_token()
                no_token = market.get_no_token()
                
                logger.info(
                    f"\n  {market.question[:50]}...\n"
                    f"  剩余: {market.minutes_to_end:.1f} 分钟\n"
                    f"  Yes: {yes_token.price:.4f if yes_token else 'N/A'} | "
                    f"No: {no_token.price:.4f if no_token else 'N/A'}"
                )
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ 扫描测试完成")


if __name__ == "__main__":
    asyncio.run(main())
