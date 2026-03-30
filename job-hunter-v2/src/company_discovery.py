"""
求职雷达 · 公司发现引擎 (v3.6 - 具体化搜索策略)
============================================================
v3.6 修复：
  v3.5 的搜索查询过于抽象（"搜索杰出雇主榜单"），Kimi 无法返回有效结果。
  改为具体、可搜索的查询：直接搜公司名单，而不是搜榜单概念。

策略设计原则：
  - 每个查询都包含具体的搜索词（如"郑州 上市公司 名单"）
  - 限定郑州/河南地域
  - 要求返回公司名，不要返回岗位
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
# 发现策略：具体化、可搜索的查询
# ============================================================

DISCOVERY_QUERIES = [
    # ── 策略1：郑州本地上市公司 ──
    {
        "name": "郑州A股上市公司",
        "query": (
            "搜索 郑州 A股上市公司 名单 2025，"
            "列出注册地或总部在郑州的A股上市公司名称。"
            "返回公司名称的JSON数组。"
        ),
    },

    # ── 策略2：河南500强/大企业 ──
    {
        "name": "河南百强企业",
        "query": (
            "搜索 2024年或2025年 河南省民营企业100强 名单，"
            "或 河南企业100强 名单，列出排名靠前的企业名称。"
            "返回公司名称的JSON数组。"
        ),
    },

    # ── 策略3：郑州外资企业 ──
    {
        "name": "郑州知名外企",
        "query": (
            "搜索在郑州设有工厂或办公室的知名外资企业，"
            "比如富士康郑州、日产郑州、格力郑州、海尔郑州等，"
            "以及世界500强在郑州的分公司或子公司。"
            "返回公司名称的JSON数组。"
        ),
    },

    # ── 策略4：杰出雇主（中国区）在郑州有业务的 ──
    {
        "name": "杰出雇主郑州",
        "query": (
            "搜索 2025年 Top Employers 中国杰出雇主 认证企业名单，"
            "或 中国最佳雇主 榜单企业，找出其中在河南郑州有办公室或分支机构的公司。"
            "返回公司名称的JSON数组。"
        ),
    },

    # ── 策略5：郑州高新区/经开区重点企业 ──
    {
        "name": "郑州产业园区重点企业",
        "query": (
            "搜索 郑州高新技术开发区 或 郑州经济技术开发区 的重点企业名单，"
            "包括入驻的知名科技公司、信息技术企业、上市公司。"
            "返回公司名称的JSON数组。"
        ),
    },

    # ── 策略6：郑州央企/国企 ──
    {
        "name": "郑州央企国企",
        "query": (
            "搜索在郑州的央企和大型国企分支机构，"
            "比如中铁、中建、国家电网、中国移动、中国银行等在郑州的分公司，"
            "以及河南省属大型国企如河南能源化工集团、中原银行等。"
            "返回公司名称的JSON数组。"
        ),
    },
]

SEARCH_TOOLS = [
    {
        "type": "builtin_function",
        "function": {"name": "$web_search"},
    }
]

THINKING_DISABLED = {"thinking": {"type": "disabled"}}

EXTRACT_SYSTEM_PROMPT = """你是企业信息研究助手。任务是通过联网搜索找到符合条件的企业名称。

要求：
1. 使用搜索工具查找信息
2. 只返回你确实通过搜索找到的企业名，不要编造
3. 尽可能多地列出找到的公司（10-30家）
4. 返回纯JSON数组格式

【返回格式】纯JSON数组：
["公司A全称", "公司B全称", "公司C全称"]

没找到就返回 []"""


def _search_companies(query: str, delay: float = 1.0) -> list:
    """用 Kimi 联网搜索发现公司名称。"""
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

        messages.append(choice.message)
        for tc in (choice.message.tool_calls or []):
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tc.function.arguments,
            })

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
            return [n.strip() for n in names if isinstance(n, str) and n.strip() and len(n.strip()) >= 3]
        return []
    except Exception:
        # fallback: 按行提取
        lines = text.strip().split("\n")
        names = []
        for line in lines:
            line = re.sub(r"^[\d\.\-\*•·\s]+", "", line).strip()
            if line and 3 <= len(line) <= 30:
                names.append(line)
        return names


# ============================================================
# 主入口
# ============================================================

def discover_companies(existing_names: set) -> list:
    """
    运行公司发现引擎，返回去重后的新公司名列表。
    """
    print("[公司发现] 启动公司发现引擎（6策略：上市/百强/外企/雇主/园区/央企）")

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
