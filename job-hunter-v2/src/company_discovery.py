"""
求职雷达 · 公司发现引擎 (v3.5)
============================================================
基于"反向找公司"方法论，通过以下策略自动发现优质公司：

策略1 - 榜单发现法：
  搜索"杰出雇主"、"最佳职场"等权威榜单，提取在郑州/河南有业务的公司

策略2 - 行业龙头法：
  搜索目标行业（信息化/数据/咨询/制造）的头部企业，筛选郑州有岗位的

策略3 - 地域挖掘法：
  搜索郑州本地上市公司、外企、500强子公司，发现平台上不容易刷到的机会

运行频率：
  白名单 < DISCOVERY_THRESHOLD 时自动触发，或手动触发
  避免每次运行都消耗 token

输出：
  返回一批候选公司名称，由调用方送入质量筛选管线
"""

import os
import re
import json
import time

from openai import OpenAI

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
MODEL = "kimi-k2.5"
BASE_URL = "https://api.moonshot.cn/v1"

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not KIMI_API_KEY:
            raise RuntimeError("未设置 KIMI_API_KEY 环境变量")
        _client = OpenAI(
            api_key=KIMI_API_KEY,
            base_url=BASE_URL,
            timeout=60,
        )
    return _client


# ============================================================
# 发现策略查询模板
# ============================================================

DISCOVERY_QUERIES = [
    # ── 策略1：榜单发现法 ──
    {
        "name": "杰出雇主榜单",
        "query": (
            "搜索2025年或2026年中国杰出雇主榜单、中国最佳雇主榜单，"
            "找出其中在郑州或河南有分公司、办事处或业务的企业名称。"
            "只返回公司名称列表。"
        ),
    },
    {
        "name": "外企最佳职场",
        "query": (
            "搜索2025年或2026年中国最佳外资企业雇主、外企最佳职场榜单，"
            "找出在郑州或河南设有办公室或工厂的外资企业。"
            "只返回公司名称列表。"
        ),
    },

    # ── 策略2：行业龙头法 ──
    {
        "name": "信息化/数据行业龙头",
        "query": (
            "搜索河南郑州的信息化、数字化、数据服务、ERP软件行业的龙头企业和上市公司，"
            "包括在郑州设有研发中心或分公司的全国性IT/咨询企业。"
            "只返回公司名称列表。"
        ),
    },

    # ── 策略3：地域挖掘法 ──
    {
        "name": "郑州上市公司与500强",
        "query": (
            "搜索郑州本地的上市公司名单，以及世界500强、中国500强在郑州设有分支机构的企业。"
            "重点关注有数据分析、运营管理、信息化等白领岗位的公司。"
            "只返回公司名称列表。"
        ),
    },
    {
        "name": "郑州外企与合资企业",
        "query": (
            "搜索在郑州或河南的外商独资企业和中外合资企业名单，"
            "包括欧美日韩企业在郑州的分公司、代表处或工厂。"
            "只返回公司名称列表。"
        ),
    },
]

# Kimi 搜索工具声明
SEARCH_TOOLS = [
    {
        "type": "builtin_function",
        "function": {"name": "$web_search"},
    }
]

THINKING_DISABLED = {"thinking": {"type": "disabled"}}

EXTRACT_SYSTEM_PROMPT = """你是企业信息研究助手。你的任务是通过联网搜索找到符合条件的企业名称。

要求：
1. 使用搜索工具查找信息
2. 只返回你确实通过搜索找到的企业名，不要编造
3. 返回纯JSON数组格式，每个元素是一个公司名字符串

【返回格式】纯JSON数组：
["公司A全称", "公司B全称", "公司C全称"]

如果没找到符合条件的企业，返回空数组 []"""


def _search_companies(query: str, delay: float = 1.0) -> list:
    """
    用 Kimi 联网搜索发现公司名称。
    返回公司名列表。
    """
    time.sleep(delay)
    client = _get_client()

    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=SEARCH_TOOLS,
            max_tokens=2000,
            extra_body=THINKING_DISABLED,
        )
        choice = response.choices[0]

        if choice.finish_reason != "tool_calls":
            return []

        # 提交搜索参数
        messages.append(choice.message)
        for tc in (choice.message.tool_calls or []):
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tc.function.arguments,
            })

        # 等待结果（最多3轮）
        for turn in range(3):
            response2 = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=SEARCH_TOOLS,
                max_tokens=2000,
                extra_body=THINKING_DISABLED,
            )
            choice2 = response2.choices[0]

            if choice2.finish_reason == "stop":
                return _parse_company_names(choice2.message.content or "")

            if choice2.finish_reason == "tool_calls":
                messages.append(choice2.message)
                for tc in (choice2.message.tool_calls or []):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tc.function.arguments,
                    })
            else:
                break

        return []

    except Exception as e:
        err_str = str(e)
        if "429" in err_str:
            print(f"    ✗ 限流，跳过此策略")
        else:
            print(f"    ✗ 搜索失败: {err_str[:100]}")
        return []


def _parse_company_names(text: str) -> list:
    """从 Kimi 返回的文本中解析公司名列表。"""
    if not text:
        return []
    try:
        text = text.strip()
        text = re.sub(r"^```json?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            text = match.group(0)

        names = json.loads(text)
        if isinstance(names, list):
            return [n.strip() for n in names if isinstance(n, str) and n.strip()]
        return []
    except Exception as e:
        # 如果不是 JSON，尝试按行提取
        lines = text.strip().split("\n")
        names = []
        for line in lines:
            line = re.sub(r"^[\d\.\-\*•·]+\s*", "", line).strip()
            if line and len(line) >= 3 and len(line) <= 30:
                names.append(line)
        return names


# ============================================================
# 主入口
# ============================================================

def discover_companies(existing_names: set) -> list:
    """
    运行公司发现引擎，返回去重后的新公司名列表。

    参数：
        existing_names: 白名单中已有的公司名集合，用于去重

    返回：
        新发现的公司名列表（已去重，未经质量筛选）
    """
    print("[公司发现] 启动公司发现引擎（榜单+行业+地域三策略）")

    all_discovered = []
    seen = set()

    for strategy in DISCOVERY_QUERIES:
        name = strategy["name"]
        query = strategy["query"]
        print(f"  ▸ 策略: {name}")

        companies = _search_companies(query)

        new_count = 0
        for company in companies:
            if company not in existing_names and company not in seen:
                seen.add(company)
                all_discovered.append(company)
                new_count += 1

        if companies:
            print(f"    ✓ 发现 {len(companies)} 家公司，其中 {new_count} 家为新公司")
        else:
            print(f"    ✗ 未发现公司")

    print(f"[公司发现] 完成，共发现 {len(all_discovered)} 家新候选公司")
    return all_discovered
