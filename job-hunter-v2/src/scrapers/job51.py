"""
求职雷达 · 双轨搜索引擎 (v3.5 - 修复搜索轮次不足)
============================================================
v3.5 修复：
  1. range(2) → range(3)：v3.4 的方向限定 Prompt 导致 Kimi 需要更多轮
     $web_search 才能完成搜索，原来2轮上限导致 70% 搜索被丢弃
  2. SYSTEM_PROMPT 精简：方向过滤的主要工作交给 ai_scorer.py 的
     EXCLUDE_KEYWORDS，Prompt 只做轻量引导（"优先返回"而非"排除"），
     减少 Kimi 因过度筛选而多次搜索的情况
  3. 其余 v3.4 优化保留：max_tokens 2000、delay 1s、429快速失败、
     自动学习预过滤+限量
"""

import os
import re
import json
import time
import hashlib

from openai import OpenAI

# ============================================================
# 初始化
# ============================================================
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
# 429 快速失败异常
# ============================================================
class TPDExhaustedError(Exception):
    """TPD 限额耗尽，用于中止后续搜索"""
    pass


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
    "美团": "https://zhaopin.meituan.com/",
    "字节跳动": "https://jobs.bytedance.com/campus",
    "华润": "https://campus.crc.com.cn/",
    "中国银行": "https://campus.boc.cn/",
    "招商银行": "https://career.cmbchina.com/campus",
    "平安": "https://campus.pingan.com/",
    "海尔": "https://career.haier.com/",
    "联想": "https://talent.lenovo.com.cn/",
    "用友": "https://career.yonyou.com/",
    "金蝶": "https://campus.51job.com/kingdee/",
    "牧原": "https://campus.muyuanfoods.com/",
    "宇通客车": "https://zhaopin.yutong.com/",
    "海底捞": "https://job.haidilao.com/",
    "德邦": "https://campus.deppon.com/",
    "好未来": "https://www.talkingdata.com/careers/",
    "腾讯": "https://join.qq.com/",
    "亚信": "https://campus.asiainfo.com/",
    "北森": "https://www.beisen.com/aboutus/join.html",
    "超聚变": "https://www.xfusion.com/cn/about/join-us/",
    "太古可口可乐": "https://www.swirecocacola.com/sc/careers/",
    "复星": "https://www.fosunpharma.com/careers",
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

def classify_url(url: str) -> str:
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
    name_lower = company_name.lower()
    for key, url in COMPANY_CAREER_URLS.items():
        if key in company_name or key in name_lower:
            return url
    return ""


# ============================================================
# Kimi $web_search 一步法搜索
# ============================================================

SEARCH_TOOLS = [
    {
        "type": "builtin_function",
        "function": {"name": "$web_search"},
    }
]

THINKING_DISABLED = {"thinking": {"type": "disabled"}}

# v3.5：精简 Prompt，方向过滤交给后端 EXCLUDE_KEYWORDS
# Prompt 只做轻量引导（"优先"而非"排除"），减少 Kimi 多次搜索的倾向
SYSTEM_PROMPT = """你是专业的招聘信息搜索助手，服务于一名正在找郑州实习工作的2026/2027届应届硕士生。

你的任务：
1. 使用联网搜索工具搜索招聘信息
2. 只报告你通过搜索实际找到的职位，绝对不能凭记忆编造
3. 只保留郑州/河南的岗位，全职岗位用 fulltime 标注
4. 优先返回：数据分析、运营、咨询、信息管理、ERP、项目管理、审计方向的岗位

【返回格式】纯JSON数组，不要任何 markdown 标记或其他文字：
[
  {
    "title": "职位名称",
    "company": "公司全名（必须是具体公司名，不能写'某公司'）",
    "location": "郑州",
    "salary": "薪资或面议",
    "experience": "经验要求",
    "education": "学历要求",
    "apply_type": "internship",
    "source_platform": "Boss直聘",
    "url": "职位链接（有则填完整URL，无则填空字符串）"
  }
]

如果没有找到任何郑州实习职位，返回空数组 []
注意：apply_type 只能是 internship 或 fulltime"""


def _search_and_extract_jobs(query: str, delay: float = 1.0) -> dict:
    """
    Kimi 一步法：联网搜索 + 直接返回结构化岗位JSON。
    v3.5：后续轮次上限从 range(2) 恢复为 range(3)，
    给 Kimi 足够的轮次完成多次 $web_search 后返回结果。
    """
    time.sleep(delay)
    client = _get_client()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]

    try:
        # ── 第一轮：期望触发 $web_search ────────────────────
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=SEARCH_TOOLS,
            max_tokens=2000,
            extra_body=THINKING_DISABLED,
        )
        choice = response.choices[0]

        if choice.finish_reason != "tool_calls":
            print("    ✗ Kimi未触发联网搜索，丢弃结果（宁缺毋滥）")
            return {"jobs": [], "has_search": False}

        tool_calls = choice.message.tool_calls or []
        has_web_search = any(tc.function.name == "$web_search" for tc in tool_calls)
        if not has_web_search:
            print("    ✗ 未检测到 $web_search 调用，丢弃")
            return {"jobs": [], "has_search": False}

        # ── 提交工具参数，让 Kimi 执行搜索 ──────────────────
        messages.append(choice.message)
        for tc in tool_calls:
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tc.function.arguments,
            })

        # ── 后续轮次等待 finish_reason=stop（最多3轮）────────
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
                text = choice2.message.content or ""
                jobs = _parse_jobs_from_text(text)
                return {"jobs": jobs, "has_search": True}

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

        print("    ✗ 超过最大轮次，丢弃结果")
        return {"jobs": [], "has_search": False}

    except Exception as e:
        err_str = str(e)
        if "429" in err_str and "TPD" in err_str:
            raise TPDExhaustedError(f"TPD限额耗尽: {err_str[:120]}")
        if "timeout" in err_str.lower() or "timed out" in err_str.lower():
            print(f"    ✗ 请求超时（>60秒），跳过此次搜索")
        else:
            print(f"    [搜索] 失败: {err_str[:120]}")
        return {"jobs": [], "has_search": False}


def _parse_jobs_from_text(text: str) -> list:
    """从 Kimi 返回的文本中解析 JSON 岗位列表。"""
    if not text:
        return []
    try:
        text = text.strip()
        text = re.sub(r"^```json?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            text = match.group(0)

        jobs = json.loads(text)
        if isinstance(jobs, list):
            return [j for j in jobs if isinstance(j, dict)]
        return []
    except json.JSONDecodeError as e:
        try:
            decoder = json.JSONDecoder()
            result, _ = decoder.raw_decode(text)
            if isinstance(result, list):
                return [j for j in result if isinstance(j, dict)]
        except Exception:
            pass
        print(f"    [JSON解析] 失败: {e}")
        return []


# ============================================================
# 岗位后处理
# ============================================================

def _post_process_job(job: dict, source_label: str) -> dict:
    company = job.get("company", "").strip()
    url = job.get("url", "").strip()
    url_type = classify_url(url)

    if not url:
        fallback = get_company_fallback_url(company)
        if fallback:
            url = fallback
            url_type = "career_page"

    return {
        "title": job.get("title", "").strip(),
        "company": company,
        "location": job.get("location", "郑州").strip(),
        "salary": job.get("salary", "面议").strip() or "面议",
        "experience": job.get("experience", "").strip(),
        "education": job.get("education", "").strip(),
        "apply_type": job.get("apply_type", "internship"),
        "source": source_label,
        "source_platform": job.get("source_platform", "").strip(),
        "url": url,
        "url_type": url_type,
        "grounded": True,
        "has_url": bool(url),
    }


def _job_hash(job: dict) -> str:
    key = f"{job.get('company','').strip()}-{job.get('title','').strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ============================================================
# 公司质量筛选（四方案并行，禁用thinking加速）
# ============================================================

def _is_quality_company_batch(company_names: list) -> dict:
    if not company_names:
        return {}

    names_text = "\n".join(f"- {n}" for n in company_names)

    prompt = f"""判断以下每家公司是否符合至少一个条件（符合任意一条即为"合格"）：
B. 上市公司：在A股、港股、美股等任一正规交易所上市
C. 外资或合资：外商独资或中外合资企业
D. 500强：世界500强或中国500强
E. 行业前5：国内主营业务市场份额前5名

公司列表：
{names_text}

原则：不确定的一律判为不合格，宁缺毋滥。

返回纯JSON对象：
{{
  "公司名": {{"qualified": true, "matched_criteria": "B", "reason": "A股上市"}},
  "公司名2": {{"qualified": false, "matched_criteria": "", "reason": "无法确认"}}
}}"""

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "只返回JSON，不要其他文字。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
            extra_body=THINKING_DISABLED,
        )

        raw = (response.choices[0].message.content or "{}").strip()
        raw = re.sub(r"^```json?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
        result = json.loads(raw)

        scheme_map = {
            "B": "方案1/2(上市)",
            "C": "方案1/3/4(外资)",
            "D": "方案3/4(500强)",
            "E": "方案3(行业前5)",
        }

        qualified = {}
        for name in company_names:
            info = result.get(name, {})
            is_qualified = info.get("qualified", False)
            criteria = info.get("matched_criteria", "")
            reason = info.get("reason", "")
            qualified[name] = is_qualified
            scheme_label = scheme_map.get(criteria, f"条件{criteria}")
            if is_qualified:
                print(f"    ✓ {name}：{reason} → 通过{scheme_label}")
            else:
                print(f"    ✗ {name}：{reason}")

        return qualified

    except Exception as e:
        err_str = str(e)
        if "429" in err_str and "TPD" in err_str:
            print(f"    [公司质量判断] TPD耗尽，默认全部不通过")
        else:
            print(f"    [公司质量判断] 失败: {err_str[:120]}，默认全部不通过")
        return {name: False for name in company_names}


# ============================================================
# 自动学习：规则预过滤
# ============================================================

GARBAGE_COMPANY_KEYWORDS = [
    "某", "未明确", "未知", "匿名", "信息未",
]

SMALL_COMPANY_SUFFIXES = [
    "工作室", "个体", "经营部", "服务部", "小店",
]


def _pre_filter_candidates(candidate_names: list) -> list:
    filtered = []
    for name in candidate_names:
        if not name or len(name) < 3:
            print(f"    [预过滤] 跳过（名称无效）: {name}")
            continue
        if any(kw in name for kw in GARBAGE_COMPANY_KEYWORDS):
            print(f"    [预过滤] 跳过（名称模糊）: {name}")
            continue
        if any(name.endswith(s) for s in SMALL_COMPANY_SUFFIXES):
            print(f"    [预过滤] 跳过（小微企业）: {name}")
            continue
        filtered.append(name)

    skipped = len(candidate_names) - len(filtered)
    if skipped > 0:
        print(f"    [预过滤] 规则过滤掉 {skipped} 家，剩余 {len(filtered)} 家待AI判断")
    return filtered


# ============================================================
# 白名单自动更新
# ============================================================

def _update_whitelist_with_new_companies(jobs: list, whitelist: list, config: dict) -> list:
    if not config.get("AUTO_UPDATE_WHITELIST", True):
        return whitelist

    max_size = config.get("WHITELIST_MAX_SIZE", 30)
    max_candidates = config.get("AUTO_LEARN_MAX_CANDIDATES", 10)
    existing_names = {w.get("name", "").strip() for w in whitelist}

    candidate_names = []
    seen = set()
    for job in jobs:
        company = job.get("company", "").strip()
        if company and company not in existing_names and company not in seen:
            candidate_names.append(company)
            seen.add(company)

    if not candidate_names:
        return whitelist

    print(f"[自动学习] 发现 {len(candidate_names)} 家新公司")

    candidate_names = _pre_filter_candidates(candidate_names)

    if not candidate_names:
        print("[自动学习] 预过滤后无候选公司")
        return whitelist

    if len(candidate_names) > max_candidates:
        print(f"[自动学习] 候选公司 {len(candidate_names)} 家超过限额 {max_candidates}，截取前 {max_candidates} 家")
        candidate_names = candidate_names[:max_candidates]

    print(f"[自动学习] 开始四方案并行质量筛选（{len(candidate_names)} 家）...")

    batch_size = 20
    qualified_map = {}
    for i in range(0, len(candidate_names), batch_size):
        batch = candidate_names[i: i + batch_size]
        time.sleep(1)
        qualified_map.update(_is_quality_company_batch(batch))

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
    all_jobs = []
    seen_hashes = set()
    tpd_exhausted = False

    def add_jobs(new_jobs: list):
        for job in new_jobs:
            h = _job_hash(job)
            if h not in seen_hashes:
                seen_hashes.add(h)
                all_jobs.append(job)

    keywords = config.get("SEARCH_KEYWORDS", [])

    # ── Track A：关键词搜索 ──────────────────────────────────
    print("[搜索] 轨道A: 实习关键词搜索开始（Kimi联网）")
    for kw in keywords:
        if tpd_exhausted:
            print(f"  ▸ {kw}\n    ⚠️ TPD已耗尽，跳过")
            continue

        query = (
            f"搜索郑州 {kw} 招聘信息，"
            f"重点查找Boss直聘、猎聘、前程无忧、智联招聘等平台上的郑州实习岗位，"
            f"只返回有明确招聘信息的职位。"
        )
        print(f"  ▸ {kw}")

        try:
            result = _search_and_extract_jobs(query)
        except TPDExhaustedError as e:
            print(f"    ⚠️ {e}")
            tpd_exhausted = True
            continue

        if result["has_search"] and result["jobs"]:
            processed = [_post_process_job(j, "关键词搜索") for j in result["jobs"]]
            add_jobs(processed)
            print(f"    ✓ 搜索成功，提取到 {len(processed)} 个岗位")
        elif result["has_search"]:
            print(f"    ✓ 搜索成功，未找到郑州相关实习岗位")

    print(f"  轨道A完成，当前共 {len(all_jobs)} 个岗位\n")

    # ── Track B：白名单公司定向搜索 ──────────────────────────
    print("[搜索] 轨道B: 白名单公司定向实习搜索开始")
    for company in whitelist:
        if tpd_exhausted:
            name = company.get("name", "") if isinstance(company, dict) else str(company)
            print(f"  ▸ {name}\n    ⚠️ TPD已耗尽，跳过")
            continue

        name = company.get("name", "") if isinstance(company, dict) else str(company)
        if not name:
            continue

        query = (
            f"搜索{name}在郑州的2026年实习生招聘信息，"
            f"查找Boss直聘、猎聘、前程无忧或{name}官网上的郑州实习岗位，"
            f"面向2026届/2027届应届生。"
        )
        print(f"  ▸ {name}")

        try:
            result = _search_and_extract_jobs(query)
        except TPDExhaustedError as e:
            print(f"    ⚠️ {e}")
            tpd_exhausted = True
            continue

        if result["has_search"] and result["jobs"]:
            processed = [_post_process_job(j, "定向搜索") for j in result["jobs"]]
            add_jobs(processed)
            print(f"    ✓ 搜索成功，提取到 {len(processed)} 个岗位")
        elif result["has_search"]:
            print(f"    ✓ 搜索成功，未找到{name}郑州实习岗位")

    print(f"  轨道B完成，当前共 {len(all_jobs)} 个岗位\n")

    if tpd_exhausted:
        print("[搜索] ⚠️ 本次运行遇到 TPD 限流，部分搜索被跳过")

    updated_whitelist = _update_whitelist_with_new_companies(all_jobs, whitelist, config)
    print(f"[搜索] 双轨搜索完成，共找到 {len(all_jobs)} 个有搜索证据的岗位")
    return all_jobs, updated_whitelist
