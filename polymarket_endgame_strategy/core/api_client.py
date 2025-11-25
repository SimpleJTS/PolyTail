"""
Polymarket API 客户端
基于官方文档: https://docs.polymarket.com
"""

import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
import httpx

from config.settings import Settings, get_settings
from models.market import Market, MarketOutcome, OrderSide, OrderResult
from utils.logger import get_logger
from utils.helpers import safe_float

# 尝试导入 py-clob-client
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType, BalanceAllowanceParams, AssetType
    from py_clob_client.constants import POLYGON
    HAS_CLOB_CLIENT = True
except ImportError:
    HAS_CLOB_CLIENT = False
    ClobClient = None


class PolymarketClient:
    """
    Polymarket API 客户端
    基于官方 py-clob-client 库
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        """
        初始化客户端
        
        Args:
            settings: 配置实例
        """
        self.settings = settings or get_settings()
        self.logger = get_logger()
        
        # HTTP 客户端（用于市场数据）
        self._http_client: Optional[httpx.AsyncClient] = None
        
        # CLOB 客户端（用于交易）
        self._clob_client: Optional[Any] = None
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
    
    async def connect(self):
        """建立连接"""
        # 创建 HTTP 客户端
        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Content-Type": "application/json"}
        )
        
        # 初始化 CLOB 客户端（只需要私钥）
        if HAS_CLOB_CLIENT and self.settings.polymarket_private_key:
            try:
                host = "https://clob.polymarket.com"
                self._clob_client = ClobClient(
                    host=host,
                    key=self.settings.polymarket_private_key,
                    chain_id=POLYGON,
                )
                # 根据官方文档，需要设置 API creds（从私钥派生）
                self._clob_client.set_api_creds(self._clob_client.create_or_derive_api_creds())
                self.logger.info("CLOB 客户端已连接")
            except Exception as e:
                self.logger.warning(f"CLOB 客户端初始化失败: {e}")
                self._clob_client = None
        
        self.logger.info("API 客户端已连接")
    
    async def close(self):
        """关闭连接"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self.logger.info("API 客户端已断开")
    
    # ============================================
    # 市场数据 API (Gamma API)
    # ============================================
    
    async def get_markets(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> List[Market]:
        """
        获取市场列表
        
        Args:
            active: 是否只获取活跃市场
            closed: 是否包含已关闭市场
            limit: 返回数量限制
            offset: 偏移量
        
        Returns:
            市场列表
        """
        if not self._http_client:
            await self.connect()
        
        params = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
        }
        
        try:
            response = await self._http_client.get(
                f"{self.settings.gamma_api_url}/markets",
                params=params
            )
            response.raise_for_status()
            data = response.json()
            
            markets = []
            for item in data:
                market = self._parse_market(item)
                if market:
                    markets.append(market)
            
            return markets
            
        except Exception as e:
            self.logger.error(f"获取市场列表失败: {e}")
            return []
    
    async def get_market_by_id(self, condition_id: str) -> Optional[Market]:
        """
        根据 ID 获取市场详情
        
        Args:
            condition_id: 市场条件 ID
        
        Returns:
            市场详情或 None
        """
        if not self._http_client:
            await self.connect()
        
        try:
            response = await self._http_client.get(
                f"{self.settings.gamma_api_url}/markets/{condition_id}"
            )
            response.raise_for_status()
            data = response.json()
            return self._parse_market(data)
            
        except Exception as e:
            self.logger.error(f"获取市场详情失败: {e}")
            return None
    
    async def get_market_prices(self, token_id: str) -> Dict[str, float]:
        """
        获取市场价格（从订单簿）
        
        Args:
            token_id: Token ID
        
        Returns:
            包含 bid/ask 价格的字典
        """
        if not self._http_client:
            await self.connect()
        
        try:
            # 从 CLOB API 获取价格
            response = await self._http_client.get(
                f"{self.settings.active_clob_url}/price",
                params={"token_id": token_id, "side": "buy"}
            )
            buy_data = response.json() if response.status_code == 200 else {}
            
            response = await self._http_client.get(
                f"{self.settings.active_clob_url}/price",
                params={"token_id": token_id, "side": "sell"}
            )
            sell_data = response.json() if response.status_code == 200 else {}
            
            return {
                "bid": safe_float(buy_data.get("price"), 0.0),
                "ask": safe_float(sell_data.get("price"), 0.0),
                "mid": (safe_float(buy_data.get("price"), 0.0) + 
                       safe_float(sell_data.get("price"), 0.0)) / 2
            }
            
        except Exception as e:
            self.logger.error(f"获取价格失败: {e}")
            return {"bid": 0.0, "ask": 0.0, "mid": 0.0}
    
    async def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """
        获取订单簿
        
        Args:
            token_id: Token ID
        
        Returns:
            订单簿数据
        """
        if not self._http_client:
            await self.connect()
        
        try:
            response = await self._http_client.get(
                f"{self.settings.active_clob_url}/book",
                params={"token_id": token_id}
            )
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            self.logger.error(f"获取订单簿失败: {e}")
            return {"bids": [], "asks": []}
    
    # ============================================
    # 交易 API (CLOB API)
    # ============================================
    
    async def place_order(
        self,
        token_id: str,
        side: OrderSide,
        price: float,
        size: float,
        order_type: str = "GTC"
    ) -> OrderResult:
        """
        下单 - 基于官方文档
        
        Args:
            token_id: Token ID
            side: 买/卖方向 (BUY/SELL)
            price: 价格 (0-1)
            size: 数量
            order_type: 订单类型 (GTC/FOK/GTD)
        
        Returns:
            订单结果
        """
        if not self._clob_client:
            return OrderResult(
                success=False,
                message="CLOB 客户端未初始化，请检查私钥配置"
            )
        
        try:
            # 根据官方文档构建订单
            # BUY = 买入, SELL = 卖出
            order_args = OrderArgs(
                price=price,
                size=size,
                side=side.value,  # "BUY" or "SELL"
                token_id=token_id,
            )
            
            # 创建并签名订单
            signed_order = self._clob_client.create_order(order_args)
            
            # 提交订单
            response = self._clob_client.post_order(signed_order, order_type)
            
            order_id = ""
            if isinstance(response, dict):
                order_id = response.get("orderID", "") or response.get("id", "")
            
            return OrderResult(
                success=True,
                order_id=order_id,
                message="订单已提交"
            )
            
        except Exception as e:
            self.logger.error(f"下单失败: {e}")
            return OrderResult(
                success=False,
                message=f"下单失败: {str(e)}"
            )
    
    async def place_market_buy(
        self,
        token_id: str,
        amount: float
    ) -> OrderResult:
        """
        市价买入
        
        Args:
            token_id: Token ID
            amount: 购买金额（USDC）
        
        Returns:
            订单结果
        """
        # 获取当前卖单价格
        prices = await self.get_market_prices(token_id)
        ask_price = prices.get("ask", 0)
        
        if ask_price <= 0:
            return OrderResult(
                success=False,
                message="无法获取卖单价格"
            )
        
        # 计算购买数量
        size = amount / ask_price
        
        # 使用略高于 ask 的价格确保成交
        price = min(ask_price * 1.005, 0.99)  # 最高 0.99
        
        return await self.place_order(
            token_id=token_id,
            side=OrderSide.BUY,
            price=price,
            size=size,
            order_type="FOK"  # Fill or Kill
        )
    
    async def place_limit_sell(
        self,
        token_id: str,
        price: float,
        size: float
    ) -> OrderResult:
        """
        限价卖出
        
        Args:
            token_id: Token ID
            price: 卖出价格
            size: 卖出数量
        
        Returns:
            订单结果
        """
        return await self.place_order(
            token_id=token_id,
            side=OrderSide.SELL,
            price=price,
            size=size,
            order_type="GTC"  # Good Till Cancelled
        )
    
    async def cancel_order(self, order_id: str) -> bool:
        """
        取消订单
        
        Args:
            order_id: 订单 ID
        
        Returns:
            是否成功
        """
        if not self._clob_client:
            self.logger.error("CLOB 客户端未初始化")
            return False
        
        try:
            self._clob_client.cancel(order_id)
            return True
        except Exception as e:
            self.logger.error(f"取消订单失败: {e}")
            return False
    
    async def get_open_orders(self) -> List[Dict[str, Any]]:
        """
        获取所有未成交订单
        
        Returns:
            订单列表
        """
        if not self._clob_client:
            return []
        
        try:
            orders = self._clob_client.get_orders()
            return orders if isinstance(orders, list) else []
        except Exception as e:
            self.logger.error(f"获取订单失败: {e}")
            return []
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        获取当前持仓
        
        Returns:
            持仓列表
        """
        if not self._http_client:
            await self.connect()
        
        if not self._account:
            return []
        
        try:
            # 从 Gamma API 获取持仓
            response = await self._http_client.get(
                f"{self.settings.gamma_api_url}/positions",
                params={"user": self._account.address}
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            self.logger.error(f"获取持仓失败: {e}")
            return []
    
    async def get_balance(self) -> float:
        """
        获取 USDC 余额
        
        Returns:
            余额
        """
        # 这里需要通过 Web3 查询，简化处理
        # 实际应用中需要调用 Polygon 网络查询 USDC 余额
        return 0.0
    
    # ============================================
    # 辅助方法
    # ============================================
    
    def _parse_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """解析市场数据"""
        try:
            # 解析结束时间
            end_date = None
            end_date_str = data.get("endDate") or data.get("end_date_iso")
            if end_date_str:
                try:
                    # 处理不同的日期格式
                    if isinstance(end_date_str, str):
                        if end_date_str.endswith("Z"):
                            end_date_str = end_date_str[:-1] + "+00:00"
                        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                except Exception:
                    pass
            
            # 解析 tokens
            tokens = []
            tokens_data = data.get("tokens", []) or data.get("outcomes", [])
            for token_data in tokens_data:
                if isinstance(token_data, dict):
                    token = MarketOutcome(
                        token_id=str(token_data.get("token_id", "")),
                        outcome=token_data.get("outcome", ""),
                        price=safe_float(token_data.get("price"), 0.0)
                    )
                    tokens.append(token)
            
            return Market(
                condition_id=data.get("condition_id", "") or data.get("conditionId", ""),
                question_id=data.get("question_id", "") or data.get("questionId", ""),
                question=data.get("question", "") or data.get("title", ""),
                description=data.get("description", ""),
                end_date=end_date,
                active=data.get("active", True),
                closed=data.get("closed", False),
                resolved=data.get("resolved", False),
                tokens=tokens,
                volume=safe_float(data.get("volume"), 0.0),
                liquidity=safe_float(data.get("liquidity"), 0.0),
            )
            
        except Exception as e:
            self.logger.error(f"解析市场数据失败: {e}")
            return None
