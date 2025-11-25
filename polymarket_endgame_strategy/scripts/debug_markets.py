#!/usr/bin/env python3
"""
调试脚本：查看 Polymarket 实际返回的数据
"""

import asyncio
import httpx
from datetime import datetime, timezone

# Polymarket API 端点
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


async def debug_markets():
    """调试市场数据获取"""
    
    async with httpx.AsyncClient(timeout=30) as client:
        print("=" * 70)
        print("🔍 Polymarket 数据调试")
        print("=" * 70)
        
        # 1. 获取活跃市场（添加正确的筛选参数）
        print("\n📊 1. 从 Gamma API 获取【活跃】市场...")
        resp = await client.get(
            f"{GAMMA_API}/markets",
            params={
                "limit": 100,
                "active": "true",
                "closed": "false",
                "order": "endDate",  # 按结束时间排序
                "ascending": "true"   # 最近结束的在前
            }
        )
        markets = resp.json()
        
        print(f"   获取到 {len(markets)} 个活跃市场")
        
        if markets:
            print("\n   最近结束的5个市场:")
            print("-" * 60)
            for m in markets[:5]:
                question = m.get('question', 'N/A')[:50]
                end_date = m.get('endDate') or m.get('endDateIso') or 'N/A'
                print(f"   • {question}...")
                print(f"     结束时间: {end_date}")
                print()
        
        # 2. 搜索特定市场（使用搜索参数）
        print("=" * 70)
        print("📊 2. 搜索 'Solana' 或 '5 minute' 相关市场...")
        
        # 尝试不同的搜索方式
        for keyword in ['Solana', '5-minute', 'minute', 'Up or Down']:
            resp = await client.get(
                f"{GAMMA_API}/markets",
                params={
                    "limit": 50,
                    "active": "true",
                    "closed": "false",
                    "slug_contains": keyword.lower().replace(' ', '-')
                }
            )
            results = resp.json()
            
            if results:
                print(f"\n   关键词 '{keyword}' 找到 {len(results)} 个市场:")
                for m in results[:3]:
                    print(f"   • {m.get('question', 'N/A')[:60]}")
                    print(f"     结束时间: {m.get('endDate', 'N/A')}")
        
        # 3. 直接搜索带时间周期的市场
        print("\n" + "=" * 70)
        print("📊 3. 搜索周期性市场...")
        
        resp = await client.get(
            f"{GAMMA_API}/markets",
            params={
                "limit": 500,
                "active": "true", 
                "closed": "false"
            }
        )
        all_active = resp.json()
        print(f"   共获取 {len(all_active)} 个活跃市场")
        
        # 查找包含时间相关关键词的市场
        time_keywords = ['minute', 'hour', 'daily', 'Up or Down', '5-Min', '15-Min']
        periodic_markets = []
        
        for m in all_active:
            question = m.get('question', '').lower()
            slug = m.get('slug', '').lower()
            
            for kw in time_keywords:
                if kw.lower() in question or kw.lower() in slug:
                    periodic_markets.append(m)
                    break
        
        print(f"   找到 {len(periodic_markets)} 个周期性市场")
        
        for m in periodic_markets[:10]:
            question = m.get('question', 'N/A')
            end_date = m.get('endDate', 'N/A')
            tokens = m.get('clobTokenIds', [])
            
            print(f"\n   📌 {question[:60]}")
            print(f"      Slug: {m.get('slug', 'N/A')}")
            print(f"      结束时间: {end_date}")
            print(f"      Tokens: {len(tokens)} 个")
            if tokens:
                print(f"      Token ID: {tokens[0][:40]}...")
        
        # 4. 检查结束时间解析
        print("\n" + "=" * 70)
        print("📊 4. 检查即将结束的市场（1小时内）...")
        
        now = datetime.now(timezone.utc)
        ending_soon = []
        
        for m in all_active:
            end_str = m.get('endDate') or m.get('endDateIso')
            if not end_str:
                continue
            
            try:
                if isinstance(end_str, str):
                    # 处理多种日期格式
                    if end_str.endswith('Z'):
                        end_str = end_str[:-1] + '+00:00'
                    end_date = datetime.fromisoformat(end_str)
                    
                    # 确保有时区
                    if end_date.tzinfo is None:
                        end_date = end_date.replace(tzinfo=timezone.utc)
                    
                    minutes_left = (end_date - now).total_seconds() / 60
                    
                    if 0 < minutes_left < 60:
                        ending_soon.append({
                            'question': m.get('question', ''),
                            'slug': m.get('slug', ''),
                            'minutes_left': minutes_left,
                            'end_date': end_str,
                            'tokens': m.get('clobTokenIds', []),
                            'outcomes': m.get('outcomes', []),
                            'outcomePrices': m.get('outcomePrices', [])
                        })
            except Exception as e:
                print(f"   解析错误 {m.get('slug', 'N/A')}: {e}")
        
        print(f"   找到 {len(ending_soon)} 个 1 小时内结束的市场")
        
        for m in sorted(ending_soon, key=lambda x: x['minutes_left'])[:10]:
            print(f"\n   ⏰ [{m['minutes_left']:.1f} 分钟后结束]")
            print(f"      {m['question'][:55]}...")
            print(f"      Prices: {m['outcomePrices']}")
            print(f"      Tokens: {len(m['tokens'])} 个")
        
        # 5. 测试获取价格
        print("\n" + "=" * 70)
        print("📊 5. 测试获取订单簿价格...")
        
        if periodic_markets and periodic_markets[0].get('clobTokenIds'):
            token_id = periodic_markets[0]['clobTokenIds'][0]
            print(f"   测试 Token: {token_id[:40]}...")
            
            try:
                # 获取订单簿
                resp = await client.get(f"{CLOB_API}/book", params={"token_id": token_id})
                book = resp.json()
                print(f"   订单簿响应 Keys: {list(book.keys()) if isinstance(book, dict) else 'N/A'}")
                
                if book.get('bids'):
                    print(f"   最高买价: {book['bids'][0] if book['bids'] else 'N/A'}")
                if book.get('asks'):
                    print(f"   最低卖价: {book['asks'][0] if book['asks'] else 'N/A'}")
                    
            except Exception as e:
                print(f"   订单簿错误: {e}")
        
        print("\n" + "=" * 70)
        print("✅ 调试完成")


if __name__ == "__main__":
    asyncio.run(debug_markets())
