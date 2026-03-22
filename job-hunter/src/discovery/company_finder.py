"""
公司自动发现模块
实现文档中「反向找公司」的方法论：
  - 抓取「中国杰出雇主」榜单（Top Employers Institute）
  - 抓取欧盟商会招聘板块
每周运行一次（频率由 GitHub Actions workflow 控制）
发现的新公司存入 discovered_companies.json，并推送到邮件供你审核
"""

import json
import os
import time
import re
import requests
from bs4 import BeautifulSoup
from config import COMPANY_WHITELIST_FILE, DISCOVERED_COMPANIES_FILE, DATA_DIR

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _load_existing_companies() -> set:
    """读取已知公司名称集合"""
    known = set()
    # 从白名单读取
    if os.path.exists(COMPANY_WHITELIST_FILE):
        try:
            with open(COMPANY_WHITELIST_FILE, "r", encoding="utf-8") as f:
                wl = json.load(f)
                for c in wl:
                    known.add(c.get("name", "").strip())
        except Exception:
            pass
    # 从已发现记录读取
    if os.path.exists(DISCOVERED_COMPANIES_FILE):
        try:
            with open(DISCOVERED_COMPANIES_FILE, "r", encoding="utf-8") as f:
                dc = json.load(f)
                for c in dc:
                    known.add(c.get("name", "").strip())
        except Exception:
            pass
    return known


def _save_discovered(companies: list[dict]):
    """将新发现的公司追加到 discovered_companies.json"""
    os.makedirs(DATA_DIR, exist_ok=True)
    existing = []
    if os.path.exists(DISCOVERED_COMPANIES_FILE):
        try:
            with open(DISCOVERED_COMPANIES_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    all_entries = existing + companies
    with open(DISCOVERED_COMPANIES_FILE, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)


def discover_from_top_employers() -> list[dict]:
    """
    从 Top Employers Institute 官网抓取中国杰出雇主榜单
    """
    url = "https://www.top-employers.com/cn/top-employers/"
    new_companies = []
    known = _load_existing_companies()
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # 提取公司名称（页面结构：公司名在特定 class 的元素中）
        candidates = []
        for tag in soup.find_all(["h2", "h3", "h4", "p", "span", "a"]):
            text = tag.get_text(strip=True)
            if 2 < len(text) < 50 and not any(c in text for c in ["©", "http", "www", "@"]):
                candidates.append(text)

        for name in candidates:
            if name not in known and len(name) > 2:
                new_companies.append({
                    "name": name,
                    "source": "中国杰出雇主榜单2026",
                    "careers_url": "",  # 待人工补充
                    "added_by": "auto_discovery",
                    "approved": False,
                })
        print(f"[发现模块] 杰出雇主榜单：发现 {len(new_companies)} 家可能的新公司")
    except Exception as e:
        print(f"[发现模块] 杰出雇主榜单抓取失败: {e}")
    return new_companies


def discover_from_eu_chamber() -> list[dict]:
    """
    从欧盟商会招聘板块抓取岗位
    部分岗位直接在页面上，无需二次跳转
    """
    url = "https://www.europeanchamber.com.cn/zh/careers"
    jobs = []
    known = _load_existing_companies()
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        # 检测包含郑州/河南/中部的岗位
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if any(kw in line for kw in ["郑州", "河南", "中部", "Zhengzhou"]):
                # 尝试获取上下文作为岗位信息
                context = lines[max(0, i-2):i+3]
                title = lines[i-1] if i > 0 else line
                company = ""
                # 尝试从上下文找公司名
                for c_line in context:
                    if len(c_line) < 30 and c_line not in known:
                        company = c_line
                        break
                if title:
                    jobs.append({
                        "source": "欧盟商会招聘",
                        "title": title[:50],
                        "company": company or "欧盟商会成员企业",
                        "salary": "详见商会网站",
                        "location": line,
                        "experience": "",
                        "education": "",
                        "url": url,
                        "publish_date": "",
                        "description": ["来源：欧盟商会招聘板块"],
                        "search_keyword": "商会发现",
                    })
        print(f"[发现模块] 欧盟商会：发现 {len(jobs)} 个郑州相关岗位")
    except Exception as e:
        print(f"[发现模块] 欧盟商会抓取失败: {e}")
    return jobs


def run_company_discovery() -> tuple[list[dict], list[dict]]:
    """
    运行公司发现模块
    返回：(新发现的岗位列表, 新发现的公司候选列表)
    """
    print("[发现模块] 开始自动发现新公司...")
    discovered_jobs = []
    new_companies = []

    # 欧盟商会（可能直接有郑州岗位）
    eu_jobs = discover_from_eu_chamber()
    discovered_jobs.extend(eu_jobs)
    time.sleep(3)

    # 杰出雇主榜单（返回公司候选，不直接是岗位）
    top_companies = discover_from_top_employers()
    new_companies.extend(top_companies)

    # 保存新发现的公司候选
    if new_companies:
        _save_discovered(new_companies)
        print(f"[发现模块] 已保存 {len(new_companies)} 家新发现公司候选到 discovered_companies.json")

    return discovered_jobs, new_companies
