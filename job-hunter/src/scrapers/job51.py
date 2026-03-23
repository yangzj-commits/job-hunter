"""
前程无忧（51job）数据抓取模块
使用 we.51job.com 搜索接口，无需登录
"""

import time
import requests
from config import SEARCH_KEYWORDS, CITY_CODE_51JOB

_BASE = "https://we.51job.com/api/job/search-pc"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://we.51job.com/",
    "Accept": "application/json, text/plain, */*",
}


def _fetch_page(keyword: str, page: int = 1) -> list[dict]:
    params = {
        "api_key": "51job",
        "keyword": keyword,
        "searchType": "2",
        "jobArea": CITY_CODE_51JOB,
        "pageNum": page,
        "pageSize": 50,
        "sortType": "0",
        "issueDate": "1",
        "source": "1",
        "pageCode": "sou|sou|soulb",
    }
    try:
        resp = requests.get(_BASE, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("resultbody", {}).get("job", {}).get("items", [])
    except Exception as e:
        print(f"[51job] 抓取失败 keyword={keyword} page={page}: {e}")
        return []


def _parse_job(raw: dict, keyword: str) -> dict:
    return {
        "source": "前程无忧",
        "title": raw.get("job_name", ""),
        "company": raw.get("company_name", ""),
        "salary": raw.get("providesalary_text", "薪资面议"),
        "location": raw.get("workarea_text", ""),
        "experience": raw.get("workyear_text", ""),
        "education": raw.get("degreefrom_text", ""),
        "url": f"https://jobs.51job.com/{raw.get('number','')}.html",
        "publish_date": raw.get("issuedate", ""),
        "description": raw.get("job_welf_list", []),
        "search_keyword": keyword,
    }


def fetch_51job_jobs(max_pages: int = 2) -> list[dict]:
    all_jobs = []
    seen_urls = set()
    for keyword in SEARCH_KEYWORDS:
        print(f"[51job] 搜索: {keyword}")
        for page in range(1, max_pages + 1):
            items = _fetch_page(keyword, page)
            if not items:
                break
            for raw in items:
                job = _parse_job(raw, keyword)
                if job["url"] not in seen_urls and job["title"]:
                    seen_urls.add(job["url"])
                    all_jobs.append(job)
            time.sleep(1.5)
        time.sleep(2)
    print(f"[51job] 共抓取 {len(all_jobs)} 个岗位")
    return all_jobs
