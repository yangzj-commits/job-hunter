"""
求职雷达 · 双轨搜索引擎 (v2.1 - 质量白名单版)
============================================================
v2.1 改进：
  - 自动学习白名单增加质量筛选，符合 B/C/D/E/F 任一条件才加入：
      B. 上市公司（A股/港股/美股等）
      C. 外资独资或中外合资企业
      D. 世界500强或中国500强
      E. 所在行业国内市场份额前5名
      F. 有独立校园招聘体系（官方校招专页或正规offer流程）
  - 不符合任何条件的公司（本地小公司等）一律不加入白名单
"""

import os
import re
import json
import time
import hashlib
import requests

from google import genai
from google.genai import types

# ============================================================
# 初始化
# ============================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-2.5-flash"

_client = None

def _get_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("未设置 GEMINI_API_KEY 环境变量")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# ============================================================
# 公司招聘官网映射（URL fallback用）
# ============================================================
COMPANY_CAREER_URLS = {
    "安永": "https://www.ey.com/zh_cn/careers",
    "ey": "https://www.ey.com/zh_cn/careers",
    "毕马威": "https://home.kpmg/cn/zh/home/careers.html",
    "kpmg": "https://home.kpmg/cn/zh/home/careers.html",
    "普华永道": "https://www.pwccin.com/zh/careers.html",
    "pwc": "https://www.pwccin.com/zh/careers.html",
    "德勤": "https://www2.deloitte.com/cn/zh/careers.html",
    "deloitte": "https://www2.deloitte.com/cn/zh/careers.html",
    "施耐德": "https://www.se.com/cn/zh/about-us/careers/",
    "schneider": "https://www.se.com/cn/zh/about-us/careers/",
    "西门子": "https://www.siemens.com.cn/zh/company/careers.html",
    "siemens": "https://www.siemens.com.cn/zh/company/careers.html",
    "abb": "https://new.abb.com/careers",
    "博世": "https://www.bosch.com.cn/careers/",
    "飞利浦": "https://www.careers.philips.com/cn/zh",
    "强生": "https://jobs.jnj.com/",
    "辉瑞": "https://www.pfizer.com.cn/careers",
    "阿斯利康": "https://careers.astrazeneca.com/china",
    "渣打": "https://www.sc.com/en/careers/",
    "华为": "https://career.huawei.com/reccampportal/portal5/index.html",
    "新华三": "https://www.h3c.com/cn/About_H3C/Careers/",
    "h3c": "https://www.h3c.com/cn/About_H3C/Careers/",
    "富士康": "https://careers.foxconn.com/",
    "宇通": "https://zhaopin.yutong.com/",
    "蜜雪": "https://careers.mixueglobal.com/",
    "中原银行": "https://www.zynbank.com/zhaopin/index.html",
}

JOB_PAGE_KEYWORDS = [
    "/job/", "/jobs/", "/position/", "/vacancy/", "/opening/",
    "/apply/", "jobid=", "positionid=", "job_id=",
    "zhipin.com/job_detail/",
    "liepin.com/job/",
    "maimai.cn/job/",
    "51job.com/applyinfo/",
    "zhaopin.com/jobs/",
    "lagou.com/jobs/",
    "/招聘/", "/岗位/", "/职位/",
]

CAREER_PAGE_KEYWORDS = [
    "/career", "/careers", "/recruit", "/recruitment",
    "/join-us", "/join_us", "/joinus",
    "/talent", "/hr", "/jobs",
    "career.", "careers.", "job.", "jobs.", "recruit.",
    "zhaopin.", "zhipin.", "liepin.", "maimai.",
]


# ============================================================
# URL 工具函数
# ============================================================

def resolve_redirect_url(redirect_url: str, timeout: int = 6) -> str:
    """跟随重定向，获取真实目标URL。"""
    if not redirect_url:
        return ""
    try:
        resp = requests.head(
            redirect_url,
            allow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; JobRadar/2.0)"},
        )
        return resp.url
    except Exception:
        try:
            resp = requests.get(
                redirect_url,
                allow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (compatible; JobRadar/2.0)"},
                stream=True,
            )
            resp.close()
            return resp.url
        except Exception:
            return redirect_url


def classify_url(url: str) -> str:
    """判断URL类型：job_page / career_page / other"""
    if not url:
        return "none"
    url_lower = url.lower()
    for kw in JOB_PAGE_KEYWORDS:
        if kw in url_lower:
            return "job_page"
    for kw in CAREER_PAGE_KEYWORDS:
        if kw in url_lower:
            return "career_page"
    return "other"


def get_company_fallback_url(company_name: str) -> str:
    """根据公司名从映射表查招聘官网URL。"""
    name_lower = company_name.lower()
    for key, url in COMPANY_CAREER_URLS.items():
        if key in company_name or key in name_lower:
            return url
    return ""


def pick_best_url(grounding_urls: list, company_name: str) -> tuple:
    """从grounding URL列表中选出最优链接。返回 (url, url_type)"""
    job_page = ""
    career_page = ""

    for u in grounding_urls:
        real_url = u.get("real_url", "")
        url_type = u.get("url_type", "other")
        if url_type == "job_page" and not job_page:
            job_page = real_url
        elif url_type == "career_page" and not career_page:
            career_page = real_url

    if job_page:
        return job_page, "job_page"
    if career_page:
        return career_page, "career_page"

    fallback = get_company_fallback_url(company_name)
    if fallback:
        return fallback, "fallback"

    return "", "none"


# ============================================================
# Gemini 调用：Step 1 - 带搜索的自然语言查询
# ============================================================

def _search_with_grounding(query: str, delay: float = 2.5) -> dict:
    """开启 google_search 工具搜索，返回文本 + 真实URL列表"""
    time.sleep(delay)

    grounding_tool = types.Tool(google_search=types.GoogleSearch())

    prompt = f"""你是专业的招聘信息搜索助手，服务于一名正在找郑州工作的应届硕士生。

请搜索以下招聘信息并汇报结果：
{query}

要求：
1. 只报告你通过搜索实际找到的职位，不要凭记忆推断或编造
2. 对每个职位，请说明：职位名称、公司、地点、薪资（有则报）、经验要求、学历要求、职位类型（实习或全职）
3. 如果没有搜索到郑州相关职位，请直接说"未找到郑州相关职位"
4. 搜索重点：郑州、2026年、应届生/实习"""

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[grounding_tool],
                temperature=1.0,
            ),
        )

        text = response.text or ""
        urls = []
        search_queries = []

        try:
            candidate = response.candidates[0]
            meta = candidate.grounding_metadata
            if meta:
                if meta.web_search_queries:
                    search_queries = list(meta.web_search_queries)
                if meta.grounding_chunks:
                    for chunk in meta.grounding_chunks:
                        if chunk.web and chunk.web.uri:
                            redirect_url = chunk.web.uri
                            domain_title = chunk.web.title or ""
                            real_url = resolve_redirect_url(redirect_url)
                            url_type = classify_url(real_url)
                            urls.append({
                                "redirect_url": redirect_url,
                                "real_url": real_url,
                                "domain_title": domain_title,
                                "url_type": url_type,
                            })
        except Exception as e:
            print(f"    [URL提取] 警告: {e}")

        return {
            "text": text,
            "urls": urls,
            "has_grounding": len(urls) > 0,
            "search_queries": search_queries,
            "original_query": query,
        }

    except Exception as e:
        print(f"    [搜索] 失败: {str(e)[:80]}")
        return {
            "text": "",
            "urls": [],
            "has_grounding": False,
            "search_queries": [],
            "original_query": query,
        }


# ============================================================
# Gemini 调用：Step 2 - 从文本提取结构化JSON（不开搜索）
# ============================================================

def _extract_jobs_as_json(search_result: dict) -> list:
    """将Step1的自然语言文本提炼为结构化job列表。"""
    text = search_result.get("text", "")
    urls = search_result.get("urls", [])
    has_grounding = search_result.get("has_grounding", False)

    if not text or not has_grounding:
        return []

    url_ref = ""
    if urls:
        url_ref = "\n\n【搜索来源域名参考】\n"
        for i, u in enumerate(urls):
            url_ref += f"来源{i+1}: {u['domain_title']} ({u['url_type']})\n"

    prompt = f"""请从以下招聘搜索结果中提取结构化信息，返回JSON数组。

【搜索结果原文】
{text[:3000]}
{url_ref}

【提取规则】
1. 只提取文本中明确提到的职位，不要补充或推断
2. 只保留郑州或河南的职位
3. apply_type字段：实习填 "internship"，全职填 "fulltime"
4. source_domain字段：从【搜索来源域名参考】里选最相关的域名填入，没有填空字符串
5. salary没有则填 "面议"

【返回格式】纯JSON数组，不要任何其他文字：
[
  {{
    "title": "职位名称",
    "company": "公司全名",
    "location": "郑州",
    "salary": "8K-15K/月",
    "experience": "应届硕士",
    "education": "硕士及以上",
    "apply_type": "fulltime",
    "source_domain": "liepin.com"
  }}
]

如果没有找到任何郑州职位，返回空数组 []"""

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        raw = (response.text or "[]").strip()
        raw = re.sub(r"^```json?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()

        jobs = json.loads(raw)
        return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []

    except Exception as e:
        print(f"    [结构化提取] 失败: {e}")
        return []


# ============================================================
# 岗位后处理
# ============================================================

def _post_process_jobs(raw_jobs: list, search_result: dict, source_label: str) -> list:
    """合并job和grounding URL，只保留有搜索证据的岗位。"""
    urls = search_result.get("urls", [])
    has_grounding = search_result.get("has_grounding", False)

    if not has_grounding:
        return []

    result = []
    for job in raw_jobs:
        company = job.get("company", "")
        source_domain = job.get("source_domain", "")
        matching_urls = [
            u for u in urls
            if source_domain and source_domain in u.get("domain_title", "")
        ] if source_domain else urls

        best_url, url_type = pick_best_url(matching_urls or urls, company)

        result.append({
            "title": job.get("title", ""),
            "company": company,
            "location": job.get("location", "郑州"),
            "salary": job.get("salary", "面议"),
            "experience": job.get("experience", ""),
            "education": job.get("education", ""),
            "apply_type": job.get("apply_type", "fulltime"),
            "source": source_label,
            "url": best_url,
            "url_type": url_type,
            "grounded": True,
            "has_url": bool(best_url),
        })

    return result


def _job_hash(job: dict) -> str:
    key = f"{job.get('company','').strip()}-{job.get('title','').strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ============================================================
# 公司质量筛选（v2.1 新增）
# ============================================================

def _is_quality_company_batch(company_names: list) -> dict:
    """
    批量判断公司是否符合白名单质量标准，B/C/D/E/F 任一符合即为合格。
    返回 {公司名: True/False}

    标准：
      B. 上市公司（A股/港股/美股/纽交所/纳斯达克等任一交易所上市）
      C. 外资独资或中外合资企业
      D. 世界500强或中国500强成员
      E. 所在行业国内市场份额前5名
      F. 有独立的校园招聘体系（官方校招专页或正规offer流程）
    """
    if not company_names:
        return {}

    names_text = "\n".join(f"- {n}" for n in company_names)

    prompt = f"""你是企业信息核查助手。请判断以下每家公司是否符合至少一条标准：

标准（符合任意一条即为"合格"）：
B. 上市公司（在A股、港股、美股、纽交所、纳斯达克等任一交易所上市）
C. 外资独资或中外合资企业
D. 世界500强或中国500强成员
E. 所在行业国内市场份额前5名
F. 有独立的校园招聘体系（官方校招专页或正规offer流程）

待判断公司列表：
{names_text}

重要原则：
- 只基于你掌握的客观事实判断
- 不确定或无法核实的公司，统一判为不合格（qualified: false）
- 宁缺毋滥，避免将小型本地公司误判为合格

返回纯JSON对象，不要任何其他文字：
{{
  "公司名": {{"qualified": true, "reason": "上市公司(A股上交所)", "matched_criteria": "B"}},
  "公司名2": {{"qualified": false, "reason": "小型本地公司，不符合任何标准", "matched_criteria": ""}}
}}"""

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        raw = (response.text or "{}").strip()
        raw = re.sub(r"^```json?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
        result = json.loads(raw)

        qualified = {}
        for name in company_names:
            info = result.get(name, {})
            is_qualified = info.get("qualified", False)
            qualified[name] = is_qualified
            if is_qualified:
                print(f"    ✓ {name}：{info.get('reason', '')} [{info.get('matched_criteria', '')}]")
            else:
                print(f"    ✗ {name}：{info.get('reason', '不符合任何标准')}")
        return qualified

    except Exception as e:
        print(f"    [公司质量判断] 失败: {e}，默认全部不通过")
        return {name: False for name in company_names}


# ============================================================
# 白名单自动更新（v2.1 带质量筛选）
# ============================================================

def _update_whitelist_with_new_companies(jobs: list, whitelist: list, config: dict) -> list:
    """
    将有搜索证据的新公司，经质量筛选（B/C/D/E/F 任一符合）后加入白名单。
    不符合任何标准的公司（本地小公司等）一律排除。
    """
    if not config.get("AUTO_UPDATE_WHITELIST", True):
        return whitelist

    max_size = config.get("WHITELIST_MAX_SIZE", 50)
    existing_names = {w.get("name", "").strip() for w in whitelist}

    # 收集本次新出现的公司名（去重）
    candidate_names = []
    seen = set()
    for job in jobs:
        company = job.get("company", "").strip()
        if company and company not in existing_names and company not in seen:
            candidate_names.append(company)
            seen.add(company)

    if not candidate_names:
        return whitelist

    print(f"[自动学习] 发现 {len(candidate_names)} 家新公司，开始质量筛选...")

    # 批量质量判断（每批最多20家，防止 prompt 过长）
    batch_size = 20
    qualified_map = {}
    for i in range(0, len(candidate_names), batch_size):
        batch = candidate_names[i: i + batch_size]
        time.sleep(2)
        qualified_map.update(_is_quality_company_batch(batch))

    # 只收录通过质量筛选的公司
    newly_added = []
    for job in jobs:
        company = job.get("company", "").strip()
        if not company or company in existing_names:
            continue
        if not qualified_map.get(company, False):
            continue
        if len(whitelist) + len(newly_added) >= max_size:
            break
        if company not in {c["name"] for c in newly_added}:
            career_url = get_company_fallback_url(company) or job.get("url", "")
            newly_added.append({
                "name": company,
                "careers_url": career_url,
                "auto_added": True,
            })
            existing_names.add(company)

    if newly_added:
        print(f"[自动学习] 通过筛选，新增 {len(newly_added)} 家公司: "
              f"{', '.join(c['name'] for c in newly_added)}")
    else:
        print("[自动学习] 本次无公司通过质量筛选")

    return whitelist + newly_added


# ============================================================
# 主入口：双轨搜索
# ============================================================

def fetch_all_jobs(config: dict, whitelist: list) -> tuple:
    """
    主函数：执行双轨搜索，返回 (jobs, updated_whitelist)
    Track A：扩展关键词 × 招聘平台搜索
    Track B：白名单公司 × 定向岗位搜索
    """
    all_jobs = []
    seen_hashes = set()

    def add_jobs(new_jobs: list):
        for job in new_jobs:
            h = _job_hash(job)
            if h not in seen_hashes:
                seen_hashes.add(h)
                all_jobs.append(job)

    keywords = config.get("SEARCH_KEYWORDS", [])
    site_filter = config.get(
        "SEARCH_SITE_FILTER",
        "site:liepin.com OR site:zhipin.com OR site:maimai.cn"
    )

    # ── Track A：关键词搜索 ──────────────────────────────────
    print("[搜索] 轨道A: 关键词搜索开始")
    for kw in keywords:
        query = f"郑州 {kw} 招聘 2026 ({site_filter})"
        print(f"  ▸ {kw}")
        search_result = _search_with_grounding(query)
        if search_result["has_grounding"]:
            raw_jobs = _extract_jobs_as_json(search_result)
            processed = _post_process_jobs(raw_jobs, search_result, "关键词搜索")
            add_jobs(processed)
            print(f"    ✓ 有证据，提取到 {len(processed)} 个岗位")
        else:
            print(f"    ✗ 无搜索证据，跳过（宁缺毋滥）")

    print(f"  轨道A完成，当前共 {len(all_jobs)} 个岗位\n")

    # ── Track B：白名单公司定向搜索 ──────────────────────────
    print("[搜索] 轨道B: 白名单公司定向搜索开始")
    for company in whitelist:
        name = company.get("name", "") if isinstance(company, dict) else str(company)
        if not name:
            continue
        query = f"{name} 郑州 2026 招聘 应届生 实习 (site:liepin.com OR site:zhipin.com OR site:{name.lower()}.com)"
        print(f"  ▸ {name}")
        search_result = _search_with_grounding(query)
        if search_result["has_grounding"]:
            raw_jobs = _extract_jobs_as_json(search_result)
            processed = _post_process_jobs(raw_jobs, search_result, "定向搜索")
            add_jobs(processed)
            print(f"    ✓ 有证据，提取到 {len(processed)} 个岗位")
        else:
            print(f"    ✗ 无搜索证据，跳过")

    print(f"  轨道B完成，当前共 {len(all_jobs)} 个岗位\n")

    updated_whitelist = _update_whitelist_with_new_companies(all_jobs, whitelist, config)
    print(f"[搜索] 双轨搜索完成，共找到 {len(all_jobs)} 个有搜索证据的岗位")
    return all_jobs, updated_whitelist
