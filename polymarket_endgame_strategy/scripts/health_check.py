#!/usr/bin/env python3
"""
健康检查脚本
用于 Docker 容器健康检查和监控
"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def check_health():
    """执行健康检查"""
    checks = []
    
    # 检查 1: 配置加载
    try:
        from config.settings import get_settings
        settings = get_settings()
        checks.append(("配置加载", True, "OK"))
    except Exception as e:
        checks.append(("配置加载", False, str(e)))
    
    # 检查 2: 模块导入
    try:
        from core.api_client import PolymarketClient
        from core.strategy import EndgameStrategy
        checks.append(("模块导入", True, "OK"))
    except Exception as e:
        checks.append(("模块导入", False, str(e)))
    
    # 检查 3: API 连接（可选）
    try:
        from core.api_client import PolymarketClient
        from config.settings import Settings
        
        settings = Settings()
        client = PolymarketClient(settings)
        await client.connect()
        
        # 尝试获取市场列表
        markets = await client.get_markets(limit=1)
        await client.close()
        
        if markets:
            checks.append(("API 连接", True, f"获取到 {len(markets)} 个市场"))
        else:
            checks.append(("API 连接", True, "连接正常，无数据"))
    except Exception as e:
        checks.append(("API 连接", False, str(e)))
    
    return checks


def main():
    """主函数"""
    print("=" * 50)
    print("🏥 Polymarket 策略健康检查")
    print("=" * 50)
    
    checks = asyncio.run(check_health())
    
    all_passed = True
    for name, passed, message in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {name}: {message}")
        if not passed:
            all_passed = False
    
    print("=" * 50)
    
    if all_passed:
        print("✅ 所有检查通过")
        sys.exit(0)
    else:
        print("❌ 部分检查失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
