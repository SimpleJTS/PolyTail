"""
实时价格监听器
使用 WebSocket 实时监控价格变化
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Callable, Any
from dataclasses import dataclass
import websockets
import httpx

from config.settings import Settings, get_settings
from utils.logger import get_logger


@dataclass
class PriceUpdate:
    """价格更新"""
    token_id: str
    price: float
    side: str  # BUY or SELL
    size: float
    timestamp: datetime


class RealtimeMonitor:
    """
    实时价格监听器
    使用 Polymarket WebSocket 实时获取价格更新
    """
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.logger = get_logger()
        
        # 订阅的 token_ids
        self._subscribed_tokens: Dict[str, dict] = {}  # token_id -> market_info
        
        # WebSocket 连接
        self._ws: Optional[Any] = None
        self._running = False
        self._reconnect_delay = 1
        
        # 价格回调
        self._price_callbacks: List[Callable[[str, float], Any]] = []
        
        # 当前价格缓存
        self._prices: Dict[str, float] = {}
    
    def add_token(self, token_id: str, market_info: dict = None):
        """添加要监控的 token"""
        self._subscribed_tokens[token_id] = market_info or {}
        self.logger.info(f"添加监控 Token: {token_id[:30]}...")
    
    def remove_token(self, token_id: str):
        """移除监控的 token"""
        if token_id in self._subscribed_tokens:
            del self._subscribed_tokens[token_id]
    
    def add_price_callback(self, callback: Callable[[str, float], Any]):
        """添加价格回调"""
        self._price_callbacks.append(callback)
    
    def get_price(self, token_id: str) -> float:
        """获取缓存的价格"""
        return self._prices.get(token_id, 0.0)
    
    async def start(self):
        """启动监听"""
        if self._running:
            return
        
        self._running = True
        asyncio.create_task(self._run_forever())
        self.logger.info("🔌 实时监听器已启动")
    
    async def stop(self):
        """停止监听"""
        self._running = False
        if self._ws:
            await self._ws.close()
        self.logger.info("🔌 实时监听器已停止")
    
    async def _run_forever(self):
        """持续运行，自动重连"""
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                self.logger.error(f"WebSocket 错误: {e}")
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(self._reconnect_delay * 2, 30)
    
    async def _connect_and_listen(self):
        """连接并监听"""
        self.logger.info(f"连接 WebSocket: {self.WS_URL}")
        
        async with websockets.connect(
            self.WS_URL,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5
        ) as ws:
            self._ws = ws
            self._reconnect_delay = 1  # 重置重连延迟
            self.logger.info("✅ WebSocket 已连接")
            
            # 订阅所有 tokens
            if self._subscribed_tokens:
                await self._subscribe(list(self._subscribed_tokens.keys()))
            
            # 监听消息
            async for message in ws:
                await self._handle_message(message)
    
    async def _subscribe(self, token_ids: List[str]):
        """订阅 tokens"""
        if not self._ws or not token_ids:
            return
        
        sub_msg = {
            "assets_ids": token_ids,
            "type": "market"
        }
        
        await self._ws.send(json.dumps(sub_msg))
        self.logger.info(f"已订阅 {len(token_ids)} 个 tokens")
    
    async def _handle_message(self, message: str):
        """处理收到的消息"""
        try:
            data = json.loads(message)
            
            # 处理不同类型的消息
            if isinstance(data, list):
                # 初始订单簿快照
                for item in data:
                    await self._process_book_snapshot(item)
            elif isinstance(data, dict):
                # 价格更新
                if "price_changes" in data:
                    await self._process_price_changes(data)
                elif "bids" in data or "asks" in data:
                    await self._process_book_snapshot(data)
                    
        except Exception as e:
            self.logger.debug(f"处理消息错误: {e}")
    
    async def _process_book_snapshot(self, data: dict):
        """处理订单簿快照"""
        asset_id = data.get("asset_id", "")
        
        # 获取最佳买卖价
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        
        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 0.0
        
        # 使用中间价
        if best_bid > 0 and best_ask > 0:
            price = (best_bid + best_ask) / 2
        elif best_ask > 0:
            price = best_ask
        elif best_bid > 0:
            price = best_bid
        else:
            return
        
        await self._update_price(asset_id, price)
    
    async def _process_price_changes(self, data: dict):
        """处理价格变化"""
        for change in data.get("price_changes", []):
            asset_id = change.get("asset_id", "")
            price_str = change.get("price", "0")
            
            try:
                price = float(price_str)
                await self._update_price(asset_id, price)
            except:
                pass
    
    async def _update_price(self, token_id: str, price: float):
        """更新价格并触发回调"""
        if not token_id:
            return
        
        old_price = self._prices.get(token_id, 0.0)
        self._prices[token_id] = price
        
        # 价格有变化时触发回调
        if abs(price - old_price) > 0.001:
            for callback in self._price_callbacks:
                try:
                    result = callback(token_id, price)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    self.logger.error(f"价格回调错误: {e}")


class FastScanner:
    """
    快速扫描器
    结合 WebSocket 实时监听和快速轮询
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.logger = get_logger()
        
        self.monitor = RealtimeMonitor(settings)
        self._running = False
        
        # 信号回调
        self._signal_callbacks: List[Callable] = []
        
        # 已触发的信号（避免重复）
        self._triggered: set = set()
    
    def add_signal_callback(self, callback: Callable):
        """添加信号回调"""
        self._signal_callbacks.append(callback)
    
    async def start(self):
        """启动快速扫描"""
        self._running = True
        
        # 设置价格回调
        self.monitor.add_price_callback(self._on_price_update)
        
        # 启动 WebSocket 监听
        await self.monitor.start()
        
        # 启动快速扫描循环（2秒间隔）
        asyncio.create_task(self._fast_scan_loop())
        
        self.logger.info("⚡ 快速扫描器已启动")
    
    async def stop(self):
        """停止"""
        self._running = False
        await self.monitor.stop()
    
    async def _fast_scan_loop(self):
        """快速扫描循环 - 每2秒扫描一次新市场"""
        from core.updown_scanner import UpdownScanner
        
        scanner = UpdownScanner(self.settings)
        
        while self._running:
            try:
                # 快速扫描 Updown 市场
                markets = await scanner.scan(
                    min_minutes=self.settings.min_time_to_end,
                    max_minutes=self.settings.max_time_to_end
                )
                
                # 添加到实时监控
                for market in markets:
                    if market.up_token_id:
                        self.monitor.add_token(market.up_token_id, {
                            "market": market,
                            "outcome": "Up",
                            "entry_price": self.settings.entry_price
                        })
                    if market.down_token_id:
                        self.monitor.add_token(market.down_token_id, {
                            "market": market,
                            "outcome": "Down",
                            "entry_price": self.settings.entry_price
                        })
                
                # 等待2秒
                await asyncio.sleep(2)
                
            except Exception as e:
                self.logger.error(f"快速扫描错误: {e}")
                await asyncio.sleep(5)
    
    async def _on_price_update(self, token_id: str, price: float):
        """价格更新回调"""
        # 检查是否达到进场条件
        if price >= self.settings.entry_price:
            if token_id not in self._triggered:
                self._triggered.add(token_id)
                
                market_info = self.monitor._subscribed_tokens.get(token_id, {})
                
                self.logger.info(
                    f"⚡ 实时信号! Token: {token_id[:20]}... 价格: {price:.2%}"
                )
                
                # 触发回调
                for callback in self._signal_callbacks:
                    try:
                        result = callback(token_id, price, market_info)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        self.logger.error(f"信号回调错误: {e}")


async def main():
    """测试"""
    from utils.logger import setup_logger
    setup_logger()
    
    # 获取一个测试 token
    import time
    ts = int(time.time())
    aligned = (ts // 900) * 900 + 900
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://gamma-api.polymarket.com/events/slug/sol-updown-15m-{aligned}")
        if resp.status_code == 200:
            data = resp.json()
            market = data.get("markets", [{}])[0]
            token_ids = json.loads(market.get("clobTokenIds", "[]"))
            
            if token_ids:
                print(f"监控 Token: {token_ids[0][:40]}...")
                
                # 启动监听
                monitor = RealtimeMonitor()
                monitor.add_token(token_ids[0])
                
                def on_price(token_id, price):
                    print(f"📊 价格更新: {price:.2%}")
                
                monitor.add_price_callback(on_price)
                
                await monitor.start()
                
                # 运行30秒
                await asyncio.sleep(30)
                
                await monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())
