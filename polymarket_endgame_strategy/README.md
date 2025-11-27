# Polymarket 尾盘交易策略

自动扫描即将结束的 Polymarket 预测市场，在价格达到 95 cents 时买入，挂 99 cents 限价卖出。

## 策略逻辑

1. **扫描市场**：持续扫描 5-15 分钟内结束的市场
2. **进场条件**：当 Yes/No 选项价格 ≥ 95 cents 时买入
3. **出场策略**：立即挂 99 cents 限价卖单
4. **风险控制**：单笔最大 100 USDC，总敞口最大 500 USDC

## 快速开始

### 1. 获取私钥

从 MetaMask 导出私钥：
- MetaMask → 账户详情 → 显示私钥 → 复制（0x 开头）

### 2. Docker 部署

**构建镜像：**
```bash
docker build -t polymarket-strategy .
```

**测试扫描（不交易）：**
```bash
docker run --rm polymarket-strategy --scan-once
```

**模拟运行（不交易）：**
```bash
docker run -d --name poly-strategy \
  -e POLYMARKET_PRIVATE_KEY="0x你的私钥" \
  polymarket-strategy --dry-run
```

**正式运行（真实交易）：**
```bash
docker run -d --name poly-strategy \
  -e POLYMARKET_PRIVATE_KEY="0x你的私钥" \
  -e ENTRY_PRICE=0.95 \
  -e EXIT_PRICE=0.99 \
  -e MIN_TIME_TO_END=5 \
  -e MAX_TIME_TO_END=15 \
  -e MAX_POSITION_SIZE=100 \
  -e MAX_TOTAL_EXPOSURE=500 \
  -v $(pwd)/logs:/app/logs \
  --restart unless-stopped \
  polymarket-strategy
```

> 💡 日志会自动按4小时分割保存到 `logs/` 目录

### 3. 常用命令

```bash
# 查看实时日志
docker logs -f poly-strategy

# 查看日志文件
ls -la logs/                           # 列出所有日志文件
cat logs/strategy.log                  # 查看当前日志
tail -f logs/strategy.log              # 实时跟踪当前日志

# 停止并删除容器再重新运行
docker stop poly-strategy 2>/dev/null; docker rm poly-strategy 2>/dev/null

# 重启
docker restart poly-strategy
```

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export POLYMARKET_PRIVATE_KEY="0x你的私钥"

# 运行
python3 main.py              # 正式运行
python3 main.py --dry-run    # 模拟运行
python3 main.py --scan-once  # 只扫描一次
```

## 参数说明

| 参数 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `--entry` | `ENTRY_PRICE` | 0.95 | 进场价格阈值 |
| `--exit` | `EXIT_PRICE` | 0.99 | 出场限价 |
| `--min-time` | `MIN_TIME_TO_END` | 5 | 最小剩余时间（分钟）|
| `--max-time` | `MAX_TIME_TO_END` | 15 | 最大剩余时间（分钟）|
| `--max-position` | `MAX_POSITION_SIZE` | 100 | 单笔最大仓位（USDC）|
| `--max-exposure` | `MAX_TOTAL_EXPOSURE` | 500 | 最大总敞口（USDC）|
| `--interval` | `SCAN_INTERVAL` | 10 | 扫描间隔（秒）|
| `--log-dir` | `LOG_DIR` | `./logs` | 日志目录（4小时轮转）|

## 日志文件

日志会按 **4小时** 自动轮转，保留最近 7 天的记录：

```
logs/
├── strategy.log                    # 当前日志
├── strategy.log.20251125_040000.log  # 历史日志（按时间戳命名）
├── strategy.log.20251125_080000.log
└── ...
```

**日志格式：**
```
2025-11-25 12:34:56 | INFO     | 扫描 60 个 Updown 市场...
2025-11-25 12:34:57 | INFO     | 找到 3 个符合条件的市场
```

## 注意事项

⚠️ **交易前准备：**
1. 钱包需要有 MATIC（用于 Gas 费）
2. 钱包需要有 USDC（用于交易）
3. 首次使用需在 [Polymarket](https://polymarket.com) 网站授权 USDC

⚠️ **风险提示：**
- 市场结果可能是 No，导致亏损
- 限价单可能无法成交
- 建议先用小额资金测试

## 项目结构

```
polymarket_endgame_strategy/
├── main.py                 # 主程序入口
├── Dockerfile              # Docker 构建文件
├── requirements.txt        # 依赖
├── config/
│   └── settings.py         # 配置管理
├── core/
│   ├── api_client.py       # Polymarket API
│   ├── market_scanner.py   # 市场扫描
│   ├── price_monitor.py    # 价格监控
│   ├── order_executor.py   # 订单执行
│   └── strategy.py         # 策略引擎
├── models/
│   └── market.py           # 数据模型
└── utils/
    ├── logger.py           # 日志
    └── helpers.py          # 辅助函数
```

## License

MIT
