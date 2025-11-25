#!/bin/bash
# Docker 容器入口脚本

set -e

# 显示启动信息
echo "=================================================="
echo "🎰 Polymarket 尾盘交易策略"
echo "=================================================="
echo "启动时间: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Python 版本: $(python3 --version)"
echo ""

# 检查必要的环境变量
check_env() {
    if [ -z "${POLYMARKET_PRIVATE_KEY}" ]; then
        echo "⚠️  警告: POLYMARKET_PRIVATE_KEY 未设置"
        echo "   将以只读模式运行（无法执行交易）"
    else
        echo "✅ API 凭证已配置"
    fi
}

# 显示配置摘要
show_config() {
    echo ""
    echo "📊 策略配置:"
    echo "   进场价格: ${ENTRY_PRICE:-0.95}"
    echo "   出场价格: ${EXIT_PRICE:-0.99}"
    echo "   时间窗口: ${MIN_TIME_TO_END:-5}-${MAX_TIME_TO_END:-15} 分钟"
    echo "   最大仓位: ${MAX_POSITION_SIZE:-100} USDC"
    echo "   最大敞口: ${MAX_TOTAL_EXPOSURE:-500} USDC"
    echo "   扫描间隔: ${SCAN_INTERVAL:-10} 秒"
    echo ""
}

# 创建必要的目录
mkdir -p /app/logs /app/data 2>/dev/null || true

# 运行检查
check_env
show_config

echo "=================================================="
echo "🚀 启动策略..."
echo "=================================================="

# 执行主程序，传递所有参数
exec python3 main.py "$@"
