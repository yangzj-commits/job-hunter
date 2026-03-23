"""
基于 Gemini Google Search 的岗位搜索模块
通过 Gemini API 的搜索能力查找郑州招聘信息
完全绕开中国招聘网站的海外IP封锁问题
"""

import requests
import time
from config import SEARCH_KEYWORDS, GEMINI_API_KEY, GEMINI_MODEL

_SEARCH_QUERIES = [
    "郑州 {kw} 招聘 2026 site:zhipin.com OR site:liepin.com OR site:51job.com",
    "郑州 {kw} 招聘 外企 2026",
    "Zhengzhou {kw} jobs 2026",
]


def _search_jobs_via_gemini(keyword: str) -> list[dict]:
    """用 Gemini + Google Search 搜索岗位"""
    if not GEMINI_API_KEY:
        return []

    prompt = f"""请帮我搜索郑州的"{keyword}"相关招聘岗位信息。

要求：
1. 搜索最新发布的郑州招聘信息
2. 重点关注外资企业、知名国内企业、四大会计师事务所
3. 包含实习和全职岗位
4. 每个岗位返回：职位名称、公司名称、薪资范围、申请链接

请以JSON格式返回，格式如下：
{{
  "jobs": [
    {{
      "title": "职位名称",
      "company": "公司名称",
      "salary": "薪资",
      "location": "郑州",
      "url": "申请链接或招聘页面",
      "description": "简短描述"
    }}
  ]
}}

只返回JSON，不要其他文字。如果没有找到相关岗位，返回 {{"jobs": []}}"""

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
        text = data["candidates"][0]["content"]["parts"][0]["text"]

        import re, json
        text = re.sub(r"```json\s*|\s*```", "", text).strip()
        # 找到JSON部分
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return []
        result = json.loads(match.group())
        jobs_raw = result.get("jobs", [])

        jobs = []
        for raw in jobs_raw:
            if raw.get("title") and raw.get("company"):
                jobs.append({
                    "source": "Gemini搜索",
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

    except Exception as e:
        print(f"[Gemini搜索] keyword={keyword} 失败: {e}")
        return []


def fetch_51job_jobs(max_pages: int = 2) -> list[dict]:
    """主函数，保持接口名称兼容，实际使用Gemini搜索"""
    all_jobs = []
    seen = set()

    # 每次只搜索部分关键词，避免消耗过多API额度
    keywords_to_search = SEARCH_KEYWORDS[:8]

    for keyword in keywords_to_search:
        print(f"[Gemini搜索] 搜索: {keyword}")
        jobs = _search_jobs_via_gemini(keyword)
        for job in jobs:
            key = f"{job['company']}-{job['title']}"
            if key not in seen:
                seen.add(key)
                all_jobs.append(job)
        time.sleep(2)  # 避免超出速率限制

    print(f"[Gemini搜索] 共找到 {len(all_jobs)} 个岗位")
    return all_jobs
