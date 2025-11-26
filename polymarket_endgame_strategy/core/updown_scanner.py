"""
Updown 市场扫描器
专门扫描 Polymarket 的周期性 Up/Down 市场（5分钟/15分钟）
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import httpx

from config.settings import Settings, get_settings
from utils.logger import get_logger


@dataclass
class UpdownMarket:
    """Updown 市场数据"""
    slug: str
    title: str
    token: str  # sol, btc, eth
    period: str  # 5m, 15m
    timestamp: int
    end_date: datetime
    outcomes: List[str]  # ["Up", "Down"]
    prices: List[float]  # [0.5, 0.5]
    token_ids: List[str]
    liquidity: float
    active: bool
    
    @property
    def minutes_to_end(self) -> float:
        """距离结束的分钟数"""
        now = datetime.now(timezone.utc)
        delta = self.end_date - now
        return delta.total_seconds() / 60
    
    @property
    def up_price(self) -> float:
        """Up 选项价格"""
        try:
            idx = self.outcomes.index("Up")
            return self.prices[idx]
        except (ValueError, IndexError):
            return 0.0
    
    @property
    def down_price(self) -> float:
        """Down 选项价格"""
        try:
            idx = self.outcomes.index("Down")
            return self.prices[idx]
        except (ValueError, IndexError):
            return 0.0
    
    @property
    def up_token_id(self) -> Optional[str]:
        """Up 选项的 token_id"""
        try:
            idx = self.outcomes.index("Up")
            return self.token_ids[idx]
        except (ValueError, IndexError):
            return None
    
    @property
    def down_token_id(self) -> Optional[str]:
        """Down 选项的 token_id"""
        try:
            idx = self.outcomes.index("Down")
            return self.token_ids[idx]
        except (ValueError, IndexError):
            return None


class UpdownScanner:
    """
    Updown 市场扫描器
    扫描 Polymarket 的周期性 Up/Down 市场
    """
    
    # 支持的代币和周期
    TOKENS = ["sol", "btc", "eth"]
    PERIODS = {
        "5m": 300,   # 5 分钟 = 300 秒
        "15m": 900,  # 15 分钟 = 900 秒
    }
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.logger = get_logger()
        self.api_url = "https://gamma-api.polymarket.com"
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        self._http_client = httpx.AsyncClient(timeout=30)
        return self
    
    async def __aexit__(self, *args):
        if self._http_client:
            await self._http_client.aclose()
    
    def _align_timestamp(self, ts: int, period_seconds: int) -> int:
        """将时间戳对齐到周期"""
        return (ts // period_seconds) * period_seconds
    
    def _generate_slugs(
        self,
        tokens: Optional[List[str]] = None,
        periods: Optional[List[str]] = None,
        count: int = 5
    ) -> List[str]:
        """
        生成要查询的 slug 列表
        
        Args:
            tokens: 要查询的代币列表
            periods: 要查询的周期列表
            count: 每个组合查询多少个时间段
        
        Returns:
            slug 列表
        """
        tokens = tokens or self.TOKENS
        periods = periods or list(self.PERIODS.keys())
        
        current_ts = int(time.time())
        slugs = []
        
        for token in tokens:
            for period in periods:
                period_seconds = self.PERIODS.get(period, 900)
                
                # 生成当前和未来几个周期的 slug
                for i in range(count):
                    aligned_ts = self._align_timestamp(current_ts, period_seconds)
                    target_ts = aligned_ts + (i * period_seconds)
                    slug = f"{token}-updown-{period}-{target_ts}"
                    slugs.append(slug)
        
        return slugs
    
    async def fetch_market(self, slug: str) -> Optional[UpdownMarket]:
        """
        获取单个市场数据
        
        Args:
            slug: 市场 slug
        
        Returns:
            市场数据或 None
        """
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30)
        
        try:
            resp = await self._http_client.get(f"{self.api_url}/events/slug/{slug}")
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            
            # 解析市场数据
            markets = data.get("markets", [])
            if not markets:
                return None
            
            market = markets[0]
            
            # 解析结束时间
            end_str = market.get("endDate", "")
            end_date = datetime.now(timezone.utc)
            if end_str:
                try:
                    end_str = end_str.replace("Z", "+00:00")
                    end_date = datetime.fromisoformat(end_str)
                except:
                    pass
            
            # 解析 JSON 字符串字段
            def parse_json_str(val):
                if isinstance(val, str):
                    try:
                        return json.loads(val)
                    except:
                        return []
                return val if val else []
            
            # 解析 token_ids
            token_ids = parse_json_str(market.get("clobTokenIds", "[]"))
            
            # 解析价格
            prices_raw = parse_json_str(market.get("outcomePrices", "[]"))
            prices = []
            for p in prices_raw:
                try:
                    prices.append(float(p))
                except:
                    prices.append(0.0)
            
            # 解析 outcomes
            outcomes = parse_json_str(market.get("outcomes", "[]"))
            
            # 解析 slug 获取 token 和 period
            parts = slug.split("-")
            token = parts[0] if parts else "unknown"
            period = parts[2] if len(parts) > 2 else "15m"
            timestamp = int(parts[3]) if len(parts) > 3 else 0
            
            return UpdownMarket(
                slug=slug,
                title=data.get("title", ""),
                token=token,
                period=period,
                timestamp=timestamp,
                end_date=end_date,
                outcomes=outcomes,
                prices=prices,
                token_ids=token_ids,
                liquidity=float(market.get("liquidity", 0) or 0),
                active=market.get("active", False),
            )
            
        except Exception as e:
            self.logger.debug(f"获取市场失败 {slug}: {e}")
            return None
    
    async def scan(
        self,
        tokens: Optional[List[str]] = None,
        periods: Optional[List[str]] = None,
        min_minutes: int = 5,
        max_minutes: int = 15
    ) -> List[UpdownMarket]:
        """
        扫描符合条件的 Updown 市场
        
        Args:
            tokens: 要扫描的代币
            periods: 要扫描的周期
            min_minutes: 最小剩余时间
            max_minutes: 最大剩余时间
        
        Returns:
            符合条件的市场列表
        """
        slugs = self._generate_slugs(tokens, periods, count=10)
        
        self.logger.info(f"扫描 {len(slugs)} 个 Updown 市场...")
        
        # 并发获取所有市场
        tasks = [self.fetch_market(slug) for slug in slugs]
        results = await asyncio.gather(*tasks)
        
        # 过滤有效市场
        markets = []
        for market in results:
            if market is None:
                continue
            if not market.active:
                continue
            
            minutes_left = market.minutes_to_end
            if min_minutes <= minutes_left <= max_minutes:
                markets.append(market)
        
        self.logger.info(f"找到 {len(markets)} 个符合条件的市场")
        
        return markets
    
    async def scan_all_active(
        self,
        tokens: Optional[List[str]] = None,
        periods: Optional[List[str]] = None
    ) -> List[UpdownMarket]:
        """
        扫描所有活跃的 Updown 市场（不限时间）
        """
        slugs = self._generate_slugs(tokens, periods, count=20)
        
        tasks = [self.fetch_market(slug) for slug in slugs]
        results = await asyncio.gather(*tasks)
        
        markets = [m for m in results if m and m.active]
        return markets


async def main():
    """测试扫描器"""
    from utils.logger import setup_logger
    setup_logger()
    
    async with UpdownScanner() as scanner:
        print("=" * 60)
        print("🔍 扫描 Updown 市场")
        print("=" * 60)
        
        # 扫描所有活跃市场
        markets = await scanner.scan_all_active()
        
        print(f"\n找到 {len(markets)} 个活跃市场:\n")
        
        for m in sorted(markets, key=lambda x: x.minutes_to_end):
            print(f"⏰ [{m.minutes_to_end:.1f} 分钟] {m.title}")
            print(f"   Up: {m.up_price:.2%} | Down: {m.down_price:.2%}")
            print(f"   流动性: ${m.liquidity:,.0f}")
            print()
        
        # 扫描 5-15 分钟内的市场
        print("=" * 60)
        print("🎯 扫描 5-15 分钟内结束的市场")
        print("=" * 60)
        
        target_markets = await scanner.scan(min_minutes=5, max_minutes=15)
        
        for m in target_markets:
            print(f"\n📊 {m.title}")
            print(f"   剩余: {m.minutes_to_end:.1f} 分钟")
            print(f"   Up: {m.up_price:.2%} | Down: {m.down_price:.2%}")
            print(f"   Up Token: {m.up_token_id[:30] if m.up_token_id else 'N/A'}...")


if __name__ == "__main__":
    asyncio.run(main())
