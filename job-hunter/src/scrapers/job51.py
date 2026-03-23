"""
岗位搜索模块
通过 Gemini API 搜索郑州招聘信息
双轨：关键词搜索 + 白名单公司定向搜索
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
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"```json\s*|\s*```", "", text).strip()
        result = json.loads(text)
        return result.get("jobs", [])
    except Exception as e:
        print(f"[搜索] Gemini调用失败: {e}")
        return []


def _parse_jobs(raw_list: list, keyword: str, source: str) -> list[dict]:
    jobs = []
    for raw in raw_list:
        if raw.get("title") and raw.get("company"):
            jobs.append({
                "source": source,
                "title": raw.get("title", ""),
                "company": raw.get("company", ""),
                "salary": raw.get("salary", "薪资面议"),
                "location": raw.get("location", "郑州"),
                "experience": raw.get("experience", ""),
                "education": raw.get("education", ""),
                "url": raw.get("url", ""),
                "publish_date": "",
                "description": [raw.get("description", "")],
                "search_keyword": keyword,
            })
    return jobs


def _load_whitelist_companies() -> list[str]:
    try:
        with open(COMPANY_WHITELIST_FILE, "r", encoding="utf-8") as f:
            companies = json.load(f)
        return [c["name"] for c in companies if c.get("name")]
    except Exception:
        return []


def _build_keyword_prompt(keywords: list[str]) -> str:
    kw_str = "、".join(keywords)
    return f"""你是一个招聘信息助手。请根据你的知识，列出郑州市2025-2026年春招/社招中，
与以下岗位类型相关的招聘信息：{kw_str}

重点关注：
- 外资企业（如施耐德、西门子、ABB、四大会计师事务所等）
- 知名国内企业（如华为、新华三、宇通、蜜雪冰城等）
- 互联网大厂郑州分支（如字节跳动、京东、阿里等）
- 适合信息管理/数据分析专业应届硕士或实习生的岗位

请以JSON格式返回，包含尽可能多的真实岗位（目标20个以上）：
{{
  "jobs": [
    {{
      "title": "职位名称",
      "company": "公司名称",
      "salary": "薪资范围",
      "location": "郑州",
      "experience": "经验要求",
      "education": "学历要求",
      "url": "招聘官网或平台链接",
      "description": "岗位简要描述"
    }}
  ]
}}"""


def _build_company_prompt(companies: list[str]) -> str:
    company_str = "、".join(companies)
    return f"""你是一个招聘信息助手。请列出以下公司在郑州的招聘岗位（实习或全职均可）：
{company_str}

这些公司在郑州有分支机构或办事处。请根据你的知识列出这些公司近期可能开放的郑州岗位，
特别是适合信息管理/数据分析背景应届硕士的非技术类岗位（如运营、分析、咨询、管培生等）。

以JSON格式返回：
{{
  "jobs": [
    {{
      "title": "职位名称",
      "company": "公司名称",
      "salary": "薪资范围",
      "location": "郑州",
      "experience": "经验要求",
      "education": "学历要求",
      "url": "该公司招聘官网链接",
      "description": "岗位描述"
    }}
  ]
}}"""


def fetch_51job_jobs(max_pages: int = 2) -> list[dict]:
    """双轨搜索主函数"""
    all_jobs = []
    seen = set()

    # ── 轨道A：关键词搜索 ─────────────────────────────────────
    print("[搜索] 轨道A：关键词搜索")
    keywords = SEARCH_KEYWORDS[:8]
    prompt_a = _build_keyword_prompt(keywords)
    raw_a = _call_gemini(prompt_a)
    jobs_a = _parse_jobs(raw_a, "关键词搜索", "Gemini推荐")
    for job in jobs_a:
        key = f"{job['company']}-{job['title']}"
        if key not in seen:
            seen.add(key)
            all_jobs.append(job)
    print(f"  找到 {len(jobs_a)} 个岗位")
    time.sleep(3)

    # ── 轨道B：白名单公司定向搜索 ─────────────────────────────
    print("[搜索] 轨道B：白名单公司定向搜索")
    companies = _load_whitelist_companies()
    if companies:
        # 第一批（前10家）
        prompt_b1 = _build_company_prompt(companies[:10])
        raw_b1 = _call_gemini(prompt_b1)
        jobs_b1 = _parse_jobs(raw_b1, "白名单定向", "定向搜索")
        for job in jobs_b1:
            key = f"{job['company']}-{job['title']}"
            if key not in seen:
                seen.add(key)
                all_jobs.append(job)
        print(f"  第一批找到 {len(jobs_b1)} 个岗位")
        time.sleep(3)

        # 第二批（后10家）
        if len(companies) > 10:
            prompt_b2 = _build_company_prompt(companies[10:20])
            raw_b2 = _call_gemini(prompt_b2)
            jobs_b2 = _parse_jobs(raw_b2, "白名单定向", "定向搜索")
            for job in jobs_b2:
                key = f"{job['company']}-{job['title']}"
                if key not in seen:
                    seen.add(key)
                    all_jobs.append(job)
            print(f"  第二批找到 {len(jobs_b2)} 个岗位")

    print(f"\n[搜索] 双轨搜索完成，共 {len(all_jobs)} 个岗位")
    return all_jobs
