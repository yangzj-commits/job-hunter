"""
前程无忧（51job）数据抓取模块
使用前端公开的 HMAC-SHA256 签名接口，无需登录，无需 Cookie
城市：郑州（101180100）
"""

import hmac
import time
import requests
from hashlib import sha256
from urllib.parse import quote
from config import SEARCH_KEYWORDS, CITY_CODE_51JOB

# 前程无忧前端静态签名密钥（公开已知）
_SIGN_KEY = "abfc8f9dcf8c3f3d8aa294ac5f2cf2cc7767e5592590f39c3f503271dd68562b"
_BASE = "https://cupid.51job.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://we.51job.com/",
    "Accept": "application/json, text/plain, */*",
}


def _sign(path_and_query: str) -> str:
    return hmac.new(
        _SIGN_KEY.encode(), path_and_query.encode(), digestmod=sha256
    ).hexdigest()


def _build_url(keyword: str, page: int = 1, job_type: str = "") -> tuple[str, str]:
    """构造请求 URL 和对应的签名路径"""
    kw_encoded = quote(keyword)
    path = (
        f"/open/noauth/search-pc?api_key=51job"
        f"&timestamp={int(time.time())}"
        f"&keyword={kw_encoded}"
        f"&searchType=2"
        f"&jobArea={CITY_CODE_51JOB}"
        f"&jobType={job_type}"
        f"&pageNum={page}"
        f"&pageSize=50"
        f"&sortType=0"
        f"&issueDate=1"   # 最近一天发布
        f"&source=1"
        f"&pageCode=sou|sou|soulb"
    )
    return _BASE + path, path


def _fetch_page(keyword: str, page: int = 1) -> list[dict]:
    """抓取一页岗位数据"""
    url, path = _build_url(keyword, page)
    sign = _sign(path)
    headers = {**_HEADERS, "sign": sign}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        jobs_raw = data.get("resultbody", {}).get("job", {}).get("items", [])
        return jobs_raw
    except Exception as e:
        print(f"[51job] 抓取失败 keyword={keyword} page={page}: {e}")
        return []


def _parse_job(raw: dict, keyword: str) -> dict:
    """将原始数据解析为标准格式"""
    salary = raw.get("providesalary_text", "薪资面议")
    return {
        "source": "前程无忧",
        "title": raw.get("job_name", ""),
        "company": raw.get("company_name", ""),
        "salary": salary,
        "location": raw.get("workarea_text", ""),
        "experience": raw.get("workyear_text", ""),
        "education": raw.get("degreefrom_text", ""),
        "job_type": raw.get("jobwelf", ""),
        "url": f"https://jobs.51job.com/{raw.get('number', '')}.html",
        "publish_date": raw.get("issuedate", ""),
        "description": raw.get("job_welf_list", []),
        "search_keyword": keyword,
    }


def fetch_51job_jobs(max_pages: int = 3) -> list[dict]:
    """
    抓取前程无忧郑州岗位
    遍历所有关键词，每个关键词最多抓 max_pages 页
    """
    all_jobs = []
    seen_urls = set()

    for keyword in SEARCH_KEYWORDS:
        print(f"[51job] 搜索关键词: {keyword}")
        for page in range(1, max_pages + 1):
            jobs_raw = _fetch_page(keyword, page)
            if not jobs_raw:
                break
            for raw in jobs_raw:
                job = _parse_job(raw, keyword)
                if job["url"] not in seen_urls and job["title"]:
                    seen_urls.add(job["url"])
                    all_jobs.append(job)
            time.sleep(1.5)  # 礼貌延迟，避免触发频率限制
        time.sleep(2)

    print(f"[51job] 共抓取 {len(all_jobs)} 个岗位（已去重URL）")
    return all_jobs
