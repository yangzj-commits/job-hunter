"""
岗位搜索模块
双轨搜索：
  1. 关键词搜索（通用岗位）
  2. 白名单公司定向搜索（针对每家目标公司单独搜索郑州岗位）
全部通过 Gemini API + Google Search 实现，绕开海外IP封锁
"""

import json
import re
import time
import requests
from config import SEARCH_KEYWORDS, GEMINI_API_KEY, GEMINI_MODEL, COMPANY_WHITELIST_FILE


def _call_gemini(prompt: str) -> list[dict]:
    """调用 Gemini API，返回解析后的岗位列表"""
    if not GEMINI_API_KEY:
        return []

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = ""
        for part in data["candidates"][0]["content"]["parts"]:
            if "text" in part:
                text += part["text"]

        text = re.sub(r"```json\s*|\s*```", "", text).strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return []
        result = json.loads(match.group())
        return result.get("jobs", [])

    except Exception as e:
        print(f"[搜索] Gemini调用失败: {e}")
        return []


def _build_prompt(query_desc: str) -> str:
    return f"""请通过Google搜索，找出{query_desc}。

返回JSON格式，只返回JSON不要其他文字：
{{
  "jobs": [
    {{
      "title": "职位名称",
      "company": "公司名称",
      "salary": "薪资（如不知道填'薪资面议'）",
      "location": "郑州",
      "url": "招聘页面链接",
      "description": "岗位简要描述"
    }}
  ]
}}

没有找到时返回：{{"jobs": []}}"""


def _parse_jobs(raw_list: list, keyword: str, source: str = "Gemini搜索") -> list[dict]:
    jobs = []
    for raw in raw_list:
        if raw.get("title") and raw.get("company"):
            jobs.append({
                "source": source,
                "title": raw.get("title", ""),
                "company": raw.get("company", ""),
                "salary": raw.get("salary", "薪资面议"),
                "location": raw.get("location", "郑州"),
                "experience": "",
                "education": "",
                "url": raw.get("url", ""),
                "publish_date": "",
                "description": [raw.get("description", "")],
                "search_keyword": keyword,
            })
    return jobs


def _load_whitelist_companies() -> list[str]:
    """读取白名单公司名称列表"""
    try:
        with open(COMPANY_WHITELIST_FILE, "r", encoding="utf-8") as f:
            companies = json.load(f)
        return [c["name"] for c in companies if c.get("name")]
    except Exception:
        return []


def fetch_51job_jobs(max_pages: int = 2) -> list[dict]:
    """
    双轨搜索主函数
    轨道A：通用关键词搜索
    轨道B：白名单公司定向搜索
    """
    all_jobs = []
    seen = set()

    # ── 轨道A：关键词搜索（取前6个关键词）──────────────────────
    print("[搜索] 轨道A：关键词搜索")
    keywords_to_use = SEARCH_KEYWORDS[:6]
    for keyword in keywords_to_use:
        print(f"[搜索] 关键词: {keyword}")
        query = f"郑州最新招聘'{keyword}'岗位，2025年或2026年发布，包含外资企业和知名企业"
        raw_list = _call_gemini(_build_prompt(query))
        jobs = _parse_jobs(raw_list, keyword, "关键词搜索")
        for job in jobs:
            key = f"{job['company']}-{job['title']}"
            if key not in seen:
                seen.add(key)
                all_jobs.append(job)
        print(f"  找到 {len(jobs)} 个岗位")
        time.sleep(3)

    # ── 轨道B：白名单公司定向搜索（每次取前8家）──────────────
    print("\n[搜索] 轨道B：白名单公司定向搜索")
    companies = _load_whitelist_companies()[:8]
    if companies:
        # 把多家公司合并成一次查询，节省API额度
        company_list = "、".join(companies)
        query = (f"以下公司在郑州的最新招聘信息（实习或全职）：{company_list}。"
                 f"搜索这些公司官网或招聘平台上的郑州岗位")
        print(f"[搜索] 定向搜索 {len(companies)} 家公司...")
        raw_list = _call_gemini(_build_prompt(query))
        jobs = _parse_jobs(raw_list, "白名单公司", "定向搜索")
        for job in jobs:
            key = f"{job['company']}-{job['title']}"
            if key not in seen:
                seen.add(key)
                all_jobs.append(job)
        print(f"  找到 {len(jobs)} 个岗位")
        time.sleep(3)

        # 剩余公司再搜一批
        companies_rest = _load_whitelist_companies()[8:16]
        if companies_rest:
            company_list2 = "、".join(companies_rest)
            query2 = (f"以下公司在郑州的最新招聘信息：{company_list2}。"
                      f"搜索这些公司的郑州岗位")
            raw_list2 = _call_gemini(_build_prompt(query2))
            jobs2 = _parse_jobs(raw_list2, "白名单公司", "定向搜索")
            for job in jobs2:
                key = f"{job['company']}-{job['title']}"
                if key not in seen:
                    seen.add(key)
                    all_jobs.append(job)
            print(f"  第二批找到 {len(jobs2)} 个岗位")

    print(f"\n[搜索] 双轨搜索完成，共 {len(all_jobs)} 个岗位")
    return all_jobs
