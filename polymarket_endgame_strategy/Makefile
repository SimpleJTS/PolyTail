# Polymarket 尾盘策略 Makefile
# 简化常用命令

.PHONY: help build run stop logs shell test clean dev prod

# 默认目标
help:
	@echo "Polymarket 尾盘交易策略 - 可用命令:"
	@echo ""
	@echo "  make build      - 构建 Docker 镜像"
	@echo "  make dev        - 启动开发环境（dry-run 模式）"
	@echo "  make prod       - 启动生产环境（⚠️ 真实交易）"
	@echo "  make stop       - 停止服务"
	@echo "  make logs       - 查看日志"
	@echo "  make shell      - 进入容器 shell"
	@echo "  make test       - 运行一次扫描测试"
	@echo "  make clean      - 清理容器和镜像"
	@echo ""

# 构建镜像
build:
	docker-compose build

# 开发环境（dry-run）
dev:
	docker-compose up -d
	@echo ""
	@echo "✅ 服务已启动（模拟模式）"
	@echo "   查看日志: make logs"
	@echo "   停止服务: make stop"

# 生产环境（真实交易）
prod:
	@echo "⚠️  警告：即将启动生产环境（真实交易）！"
	@read -p "确认继续？[y/N] " confirm && [ "$$confirm" = "y" ]
	docker-compose -f docker-compose.prod.yml up -d
	@echo ""
	@echo "✅ 生产服务已启动"
	@echo "   查看日志: make logs"

# 停止服务
stop:
	docker-compose down
	docker-compose -f docker-compose.prod.yml down 2>/dev/null || true
	@echo "✅ 服务已停止"

# 查看日志
logs:
	docker-compose logs -f --tail=100

# 进入容器
shell:
	docker-compose exec polymarket-strategy /bin/bash

# 运行测试扫描
test:
	docker-compose run --rm polymarket-strategy --scan-once --debug

# 清理
clean:
	docker-compose down -v --rmi local
	docker-compose -f docker-compose.prod.yml down -v --rmi local 2>/dev/null || true
	@echo "✅ 清理完成"

# 重启服务
restart: stop dev

# 查看状态
status:
	docker-compose ps
