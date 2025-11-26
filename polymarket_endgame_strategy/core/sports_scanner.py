"""
体育市场扫描器
扫描 Polymarket 的体育比赛市场
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import httpx

from config.settings import Settings, get_settings
from utils.logger import get_logger


@dataclass
class SportsMarket:
    """体育市场数据"""
    condition_id: str
    slug: str
    question: str
    end_date: datetime
    outcomes: List[str]
    prices: List[float]
    token_ids: List[str]
    liquidity: float
    volume: float
    active: bool
    closed: bool
    
    @property
    def minutes_to_end(self) -> float:
        """距离结束的分钟数"""
        now = datetime.now(timezone.utc)
        delta = self.end_date - now
        return delta.total_seconds() / 60
    
    @property
    def hours_to_end(self) -> float:
        """距离结束的小时数"""
        return self.minutes_to_end / 60
    
    def get_outcome_price(self, outcome_name: str) -> float:
        """获取指定选项的价格"""
        for i, outcome in enumerate(self.outcomes):
            if outcome.lower() == outcome_name.lower():
                return self.prices[i] if i < len(self.prices) else 0.0
        return 0.0
    
    def get_outcome_token(self, outcome_name: str) -> Optional[str]:
        """获取指定选项的 token_id"""
        for i, outcome in enumerate(self.outcomes):
            if outcome.lower() == outcome_name.lower():
                return self.token_ids[i] if i < len(self.token_ids) else None
        return None
    
    @property
    def best_outcome(self) -> tuple:
        """获取价格最高的选项"""
        if not self.prices:
            return None, 0.0
        max_idx = self.prices.index(max(self.prices))
        return self.outcomes[max_idx], self.prices[max_idx]


class SportsScanner:
    """
    体育市场扫描器
    """
    
    # 体育关键词
    SPORTS_KEYWORDS = [
        'nba', 'nfl', 'nhl', 'mlb', 'mls', 'ncaa', 'ncaab', 'ncaaf',
        'soccer', 'football', 'basketball', 'baseball', 'hockey',
        'tennis', 'golf', 'ufc', 'boxing', 'f1', 'mma', 'premier league',
        'champions league', 'world cup', 'super bowl', 'playoffs',
        'championship', 'finals', 'world series', 'stanley cup',
        'vs', 'beat', 'win', 'spread', 'over', 'under', 'points',
        'celtics', 'lakers', 'warriors', 'heat', 'knicks', 'nuggets',
        'bulls', 'nets', 'bucks', 'suns', 'clippers', 'mavericks',
        'chiefs', 'eagles', 'cowboys', 'packers', 'ravens', 'lions',
        '49ers', 'bills', 'dolphins', 'jets', 'patriots', 'raiders',
        'yankees', 'dodgers', 'red sox', 'cubs', 'mets', 'astros'
    ]
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.logger = get_logger()
        self.gamma_api = "https://gamma-api.polymarket.com"
        self.clob_api = "https://clob.polymarket.com"
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        self._http_client = httpx.AsyncClient(timeout=30)
        return self
    
    async def __aexit__(self, *args):
        if self._http_client:
            await self._http_client.aclose()
    
    def _is_sports_market(self, question: str, slug: str) -> bool:
        """判断是否是体育市场"""
        text = (question + " " + slug).lower()
        return any(kw in text for kw in self.SPORTS_KEYWORDS)
    
    def _parse_json_field(self, val: Any) -> List:
        """解析可能是 JSON 字符串的字段"""
        if isinstance(val, str):
            try:
                return json.loads(val)
            except:
                return []
        return val if val else []
    
    async def fetch_sports_markets(self, limit: int = 500) -> List[SportsMarket]:
        """
        获取所有体育市场
        """
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30)
        
        sports_markets = []
        
        try:
            # 从 Gamma API 获取市场
            resp = await self._http_client.get(
                f"{self.gamma_api}/markets",
                params={
                    "limit": limit,
                    "active": "true",
                    "closed": "false"
                }
            )
            
            if resp.status_code != 200:
                return []
            
            markets = resp.json()
            
            for m in markets:
                question = m.get("question", "")
                slug = m.get("slug", "")
                
                # 检查是否是体育市场
                if not self._is_sports_market(question, slug):
                    continue
                
                # 检查是否活跃
                if m.get("closed", True) or not m.get("active", False):
                    continue
                
                # 解析结束时间
                end_str = m.get("endDate", "")
                if not end_str:
                    continue
                
                try:
                    end_str = end_str.replace("Z", "+00:00")
                    end_date = datetime.fromisoformat(end_str)
                except:
                    continue
                
                # 解析其他字段
                outcomes = self._parse_json_field(m.get("outcomes", []))
                prices_raw = self._parse_json_field(m.get("outcomePrices", []))
                token_ids = self._parse_json_field(m.get("clobTokenIds", []))
                
                # 转换价格为浮点数
                prices = []
                for p in prices_raw:
                    try:
                        prices.append(float(p))
                    except:
                        prices.append(0.0)
                
                market = SportsMarket(
                    condition_id=m.get("conditionId", ""),
                    slug=slug,
                    question=question,
                    end_date=end_date,
                    outcomes=outcomes,
                    prices=prices,
                    token_ids=token_ids,
                    liquidity=float(m.get("liquidity", 0) or 0),
                    volume=float(m.get("volume", 0) or 0),
                    active=m.get("active", False),
                    closed=m.get("closed", True)
                )
                
                sports_markets.append(market)
            
        except Exception as e:
            self.logger.error(f"获取体育市场失败: {e}")
        
        return sports_markets
    
    async def scan(
        self,
        min_minutes: int = 5,
        max_minutes: int = 60,
        min_price: float = 0.90
    ) -> List[SportsMarket]:
        """
        扫描符合条件的体育市场
        
        Args:
            min_minutes: 最小剩余时间（分钟）
            max_minutes: 最大剩余时间（分钟）
            min_price: 最小进场价格
        
        Returns:
            符合条件的市场列表
        """
        all_markets = await self.fetch_sports_markets()
        
        self.logger.info(f"扫描 {len(all_markets)} 个体育市场...")
        
        qualified = []
        
        for market in all_markets:
            # 检查时间
            minutes_left = market.minutes_to_end
            if not (min_minutes <= minutes_left <= max_minutes):
                continue
            
            # 检查价格
            best_outcome, best_price = market.best_outcome
            if best_price >= min_price:
                qualified.append(market)
        
        self.logger.info(f"找到 {len(qualified)} 个符合条件的体育市场")
        
        return qualified
    
    async def scan_all_active(self) -> List[SportsMarket]:
        """
        扫描所有活跃的体育市场
        """
        all_markets = await self.fetch_sports_markets()
        
        # 只返回未来的市场
        now = datetime.now(timezone.utc)
        active = [m for m in all_markets if m.end_date > now]
        
        return sorted(active, key=lambda x: x.end_date)


async def main():
    """测试扫描器"""
    from utils.logger import setup_logger
    setup_logger()
    
    async with SportsScanner() as scanner:
        print("=" * 60)
        print("🏀 扫描体育市场")
        print("=" * 60)
        
        # 扫描所有活跃市场
        markets = await scanner.scan_all_active()
        
        print(f"\n找到 {len(markets)} 个活跃体育市场:\n")
        
        for m in markets[:20]:
            best_outcome, best_price = m.best_outcome
            print(f"⏰ [{m.hours_to_end:.1f}h] {m.question[:50]}...")
            print(f"   最佳: {best_outcome} @ {best_price:.0%}")
            print(f"   流动性: ${m.liquidity:,.0f}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
