"""
官网监控模块
对公司白名单中的招聘页做内容哈希对比
页面有变化时，尝试提取新岗位信息
这是文档中「反向找公司」方法的技术实现
"""

import hashlib
import json
import os
import time
import re
import requests
from bs4 import BeautifulSoup
from config import COMPANY_WHITELIST_FILE, DATA_DIR

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_HASH_CACHE_FILE = os.path.join(DATA_DIR, "website_hashes.json")


def _load_hashes() -> dict:
    if os.path.exists(_HASH_CACHE_FILE):
        try:
            with open(_HASH_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_hashes(hashes: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_HASH_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(hashes, f, ensure_ascii=False, indent=2)


def _load_company_whitelist() -> list[dict]:
    """读取公司白名单，返回有招聘URL的条目"""
    if not os.path.exists(COMPANY_WHITELIST_FILE):
        return []
    try:
        with open(COMPANY_WHITELIST_FILE, "r", encoding="utf-8") as f:
            companies = json.load(f)
        return [c for c in companies if c.get("careers_url")]
    except Exception as e:
        print(f"[官网监控] 读取白名单失败: {e}")
        return []


def _fetch_page_text(url: str) -> str | None:
    """获取页面文本内容"""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # 去掉脚本和样式，只保留文本
        for tag in soup(["script", "style", "meta", "link"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)
    except Exception as e:
        print(f"[官网监控] 获取失败 {url}: {e}")
        return None


def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _extract_jobs_from_page(text: str, company_name: str, url: str) -> list[dict]:
    """
    从页面文本中用启发式方法提取岗位信息
    招聘页通常含有"招聘"/"职位"/"岗位"等词，以及地点"郑州"
    """
    jobs = []
    # 简单检测：页面是否包含郑州相关岗位信息
    zhengzhou_related = any(kw in text for kw in ["郑州", "Zhengzhou", "河南"])
    if not zhengzhou_related:
        return jobs

    # 尝试从文本中提取岗位名称（使用常见模式）
    patterns = [
        r'(?:招聘|应聘|职位|岗位)[：:]\s*([^\n\r,，]{3,30})',
        r'([^\n\r]{2,20}(?:专员|助理|经理|工程师|分析师|顾问|培训生|实习生|主管))',
    ]
    found_titles = set()
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches[:10]:  # 每种模式最多取10个
            m = m.strip()
            if 3 <= len(m) <= 30:
                found_titles.add(m)

    if found_titles:
        for title in list(found_titles)[:5]:  # 最多取5个岗位
            jobs.append({
                "source": "官网监控",
                "title": title,
                "company": company_name,
                "salary": "详见官网",
                "location": "郑州（待确认）",
                "experience": "",
                "education": "",
                "url": url,
                "publish_date": "",
                "description": ["页面有更新，建议直接访问确认"],
                "search_keyword": "官网监控",
                "_monitor_flag": True,  # 标记为监控发现，需人工确认
            })
    else:
        # 即使提取不到岗位名，也推送一条"页面有变动"提示
        jobs.append({
            "source": "官网监控",
            "title": f"【页面更新】{company_name}招聘页有新内容",
            "company": company_name,
            "salary": "点击查看",
            "location": "郑州（待确认）",
            "experience": "",
            "education": "",
            "url": url,
            "publish_date": "",
            "description": ["官网招聘页内容发生变化，建议前往查看"],
            "search_keyword": "官网监控",
            "_monitor_flag": True,
        })
    return jobs


def monitor_company_websites() -> list[dict]:
    """
    主函数：检查所有白名单公司的官网招聘页
    返回有变化的页面中提取到的岗位列表
    """
    companies = _load_company_whitelist()
    if not companies:
        print("[官网监控] 白名单为空或无招聘URL，跳过")
        return []

    hashes = _load_hashes()
    new_jobs = []
    updated_hashes = dict(hashes)

    print(f"[官网监控] 开始监控 {len(companies)} 家公司官网...")
    for company in companies:
        name = company.get("name", "")
        url = company.get("careers_url", "")
        if not url:
            continue

        text = _fetch_page_text(url)
        if text is None:
            continue

        current_hash = _text_hash(text)
        old_hash = hashes.get(url, "")

        if current_hash != old_hash:
            if old_hash:  # 非首次（首次只建立基准，不推送）
                print(f"[官网监控] {name} 页面有变化！提取岗位...")
                jobs = _extract_jobs_from_page(text, name, url)
                new_jobs.extend(jobs)
            else:
                print(f"[官网监控] {name} 建立基准哈希")
            updated_hashes[url] = current_hash
        else:
            print(f"[官网监控] {name} 无变化")

        time.sleep(2)  # 礼貌延迟

    _save_hashes(updated_hashes)
    print(f"[官网监控] 共发现 {len(new_jobs)} 个新岗位/变动提示")
    return new_jobs
