#!/usr/bin/env python3
"""
Polymarket 尾盘交易策略
主程序入口

使用方法:
    python main.py              # 运行策略（需要配置 API 凭证）
    python main.py --dry-run    # 模拟运行（不执行交易）
    python main.py --scan-once  # 只扫描一次
    python main.py --help       # 显示帮助
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

from config.settings import Settings, get_settings
from core.strategy import EndgameStrategy, DryRunStrategy
from utils.logger import setup_logger, get_logger
import logging


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Polymarket 尾盘交易策略",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python main.py                     # 正常运行
    python main.py --dry-run           # 模拟运行
    python main.py --scan-once         # 只扫描一次
    python main.py --entry 0.94        # 设置进场价格为 94 cents
    python main.py --exit 0.98         # 设置出场价格为 98 cents

环境变量:
    POLYMARKET_PRIVATE_KEY    钱包私钥（必填，0x开头）
        """
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟运行，不执行真实交易"
    )
    
    parser.add_argument(
        "--scan-once",
        action="store_true",
        help="只执行一次扫描，然后退出"
    )
    
    parser.add_argument(
        "--entry",
        type=float,
        default=None,
        help="进场价格阈值 (0-1)，例如 0.95 表示 95 cents"
    )
    
    parser.add_argument(
        "--exit",
        type=float,
        default=None,
        help="出场价格 (0-1)，例如 0.99 表示 99 cents"
    )
    
    parser.add_argument(
        "--min-time",
        type=int,
        default=None,
        help="最小剩余时间（分钟）"
    )
    
    parser.add_argument(
        "--max-time",
        type=int,
        default=None,
        help="最大剩余时间（分钟）"
    )
    
    parser.add_argument(
        "--max-position",
        type=float,
        default=None,
        help="单笔最大仓位（USDC）"
    )
    
    parser.add_argument(
        "--max-exposure",
        type=float,
        default=None,
        help="最大总敞口（USDC）"
    )
    
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="扫描间隔（秒）"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试模式"
    )
    
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="日志文件路径（单文件模式）"
    )
    
    parser.add_argument(
        "--log-dir",
        type=str,
        default=None,
        help="日志目录（启用4小时轮转）"
    )
    
    return parser.parse_args()


def create_settings(args) -> Settings:
    """根据命令行参数创建配置"""
    # 从环境变量和默认值创建基础配置
    settings = Settings()
    
    # 覆盖命令行参数
    if args.entry is not None:
        settings.entry_price = args.entry
    
    if args.exit is not None:
        settings.exit_price = args.exit
    
    if args.min_time is not None:
        settings.min_time_to_end = args.min_time
    
    if args.max_time is not None:
        settings.max_time_to_end = args.max_time
    
    if args.max_position is not None:
        settings.max_position_size = args.max_position
    
    if args.max_exposure is not None:
        settings.max_total_exposure = args.max_exposure
    
    if args.interval is not None:
        settings.scan_interval = args.interval
    
    if args.debug:
        settings.debug_mode = True
    
    return settings


async def main():
    """主函数"""
    args = parse_args()
    
    # 设置日志
    log_level = logging.DEBUG if args.debug else logging.INFO
    
    # 优先使用命令行参数，其次使用环境变量
    log_dir = args.log_dir or os.environ.get("LOG_DIR")
    log_file = args.log_file or os.environ.get("LOG_FILE")
    
    # 默认启用日志目录（如果都没设置）
    if not log_dir and not log_file:
        log_dir = "/app/logs" if os.path.exists("/app") else "./logs"
    
    setup_logger(level=log_level, log_file=log_file, log_dir=log_dir)
    logger = get_logger()
    
    # 创建配置
    settings = create_settings(args)
    
    # 选择策略类型
    if args.dry_run:
        logger.info("🔧 模拟运行模式")
        strategy = DryRunStrategy(settings)
    else:
        strategy = EndgameStrategy(settings)
    
    try:
        if args.scan_once:
            # 只扫描一次
            await strategy.run_once()
        else:
            # 持续运行
            await strategy.run()
            
    except KeyboardInterrupt:
        logger.info("\n⏹️ 用户中断")
    except Exception as e:
        logger.error(f"运行错误: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def run():
    """入口点"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已退出")


if __name__ == "__main__":
    run()
