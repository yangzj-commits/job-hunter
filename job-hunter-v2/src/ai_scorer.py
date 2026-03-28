"""
求职雷达 · AI评分模块 (v3.2 - 修复性能问题)
修复：
  1. client 加入 timeout=60，防止评分请求无限挂起
  2. budget_tokens 从 2000 降至 500，减少thinking耗时
  3. max_tokens 从 6000 降至 3000
  4. batch_size 从 20 降至 10，每批响应更快
"""

import os
import re
import json
import time

from openai import OpenAI

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
MODEL = "kimi-k2.5"
BASE_URL = "https://api.moonshot.cn/v1"

# thinking 模式：评分场景开启，但控制 budget 避免过度消耗
THINKING_ENABLED = {"thinking": {"type": "enabled", "budget_tokens": 500}}

# ---------- 白名单公司（定向加分）----------
PRIORITY_COMPANIES = [
    "安永", "EY", "毕马威", "KPMG", "普华永道", "PwC", "德勤", "Deloitte",
    "施耐德", "Schneider", "西门子", "Siemens", "ABB", "博世", "Bosch",
    "飞利浦", "Philips", "强生", "辉瑞", "Pfizer", "阿斯利康", "AstraZeneca",
    "渣打", "华为", "新华三", "H3C", "富士康", "宇通", "蜜雪", "中原银行",
    "美团", "字节跳动", "阿里", "腾讯", "京东", "百度", "中国银行", "工商银行",
    "建设银行", "农业银行", "招商银行", "平安", "中国移动", "中国联通", "中国电信",
    "海尔", "联想", "用友", "金蝶", "华润", "中粮", "牧原", "宇通客车",
]

# ---------- 直接排除的岗位关键词 ----------
EXCLUDE_KEYWORDS = [
    "工厂实习", "生产实习", "设备巡检", "车间", "流水线", "装配", "生产工人",
    "猎头", "HR外包", "招聘实习", "灵活用工",
    "地推", "BD实习", "业务拓展实习", "扫楼", "陌生拜访",
    "出纳实习", "会计助理", "记账实习", "做账",
    "法务助理", "法律助理实习",
    "平面设计", "UI设计实习", "视觉设计实习", "美工实习",
    "司机", "保安", "厨师", "保洁",
]

# ---------- 车企关键词 ----------
CAR_COMPANY_KEYWORDS = [
    "汽车", "车", "宇通", "比亚迪", "上汽", "一汽", "吉利", "长安",
    "奔驰", "宝马", "奥迪", "丰田", "本田", "大众", "福特", "沃尔沃",
]

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=KIMI_API_KEY,
            base_url=BASE_URL,
            timeout=60,     # 修复：加入超时，防止评分请求无限挂起
        )
    return _client


def _is_priority_company(company: str) -> bool:
    company_lower = company.lower()
    for p in PRIORITY_COMPANIES:
        if p.lower() in company_lower:
            return True
    return False


def _is_car_company(company: str) -> bool:
    for kw in CAR_COMPANY_KEYWORDS:
        if kw in company:
            return True
    return False


def _pre_filter(jobs: list) -> list:
    result = []
    for job in jobs:
        title = job.get("title", "")
        company = job.get("company", "")
        combined = title + company
        if any(kw in combined for kw in EXCLUDE_KEYWORDS):
            print(f"  [过滤] 排除: {title} @ {company}")
            continue
        result.append(job)
    return result


def _pre_score_adjust(job: dict, base_score: int) -> tuple:
    title = job.get("title", "")
    company = job.get("company", "")
    apply_type = job.get("apply_type", "")
    note = ""

    if apply_type == "fulltime":
        return min(base_score, 18), "全职岗位，当前仅寻找实习"

    if "销售" in title and not _is_car_company(company):
        base_score = max(0, base_score - 20)
        note = "非车企销售岗，降分处理"

    if any(kw in title for kw in ["管培生", "管理培训生"]):
        base_score = max(0, base_score - 10)
        note = "管培生岗位，需核实是否含数据分析轮岗"

    if "审计" in title and any(kw in company for kw in ["普通合伙", "特殊普通合伙"]):
        base_score = max(0, base_score - 15)
        note = "小型会计事务所审计，含金量相对较低"

    return base_score, note


def _build_scoring_prompt(jobs: list) -> str:
    jobs_text = ""
    for i, job in enumerate(jobs):
        jobs_text += (
            f"\n岗位{i+1}: {job.get('title','')} | "
            f"{job.get('company','')} | "
            f"{job.get('salary','')} | "
            f"经验:{job.get('experience','')} | "
            f"学历:{job.get('education','')} | "
            f"类型:{job.get('apply_type','')}\n"
        )

    return f"""职业规划顾问为以下实习岗位打分（0-100分）。

候选人：信息管理硕士（谢菲尔德，2026届），技能Python/Tableau/Excel/数据分析/SQL，目标郑州实习。

评分标准：
- 85-100：强推（数据分析/信息管理/咨询/运营方向，知名公司）
- 70-84：推荐
- 55-69：一般
- <55：不推荐或全职

岗位列表（共{len(jobs)}个）：
{jobs_text}

仅返回JSON：
{{"results": [{{"index": 1, "score": 85, "reason": "中文理由"}}]}}"""


def score_jobs_with_gemini(jobs: list) -> list:
    """函数名保持不变，内部已切换为 Kimi + thinking 模式。"""
    if not jobs:
        return []

    if not KIMI_API_KEY:
        print("[AI评分] 未配置 KIMI_API_KEY，所有岗位默认50分")
        for job in jobs:
            job["score"] = 50
            job["score_reason"] = "未配置AI评分"
        return jobs

    jobs = _pre_filter(jobs)
    print(f"[AI评分] 预过滤后剩余 {len(jobs)} 个岗位")

    batch_size = 10   # 修复：从20降至10，配合thinking模式响应更快
    all_scored = []

    for batch_start in range(0, len(jobs), batch_size):
        batch = jobs[batch_start: batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(jobs) + batch_size - 1) // batch_size
        print(f"[AI评分] 批次 {batch_num}/{total_batches}，{len(batch)} 个岗位")

        prompt = _build_scoring_prompt(batch)

        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "职业规划顾问，只返回JSON。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=3000,            # 修复：从6000降至3000
                extra_body=THINKING_ENABLED,
            )

            raw = (response.choices[0].message.content or "{}").strip()
            raw = re.sub(r"^```json?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw).strip()

            result = json.loads(raw)
            scores = {r["index"]: r for r in result.get("results", [])}
            print(f"[AI评分] 解析到 {len(scores)} 条评分")

            for i, job in enumerate(batch):
                score_data = scores.get(i + 1, {})
                base_score = score_data.get("score", 50)
                ai_reason = score_data.get("reason", "")

                adjusted_score, rule_note = _pre_score_adjust(job, base_score)

                bonus = 0
                if job.get("apply_type") != "fulltime" and _is_priority_company(job.get("company", "")):
                    bonus = 10

                final_score = min(100, adjusted_score + bonus)

                reason_parts = []
                if ai_reason:
                    reason_parts.append(ai_reason)
                if rule_note:
                    reason_parts.append(f"[{rule_note}]")
                if bonus:
                    reason_parts.append("[重点目标公司+10分]")

                job["score"] = final_score
                job["score_reason"] = " ".join(reason_parts)
                all_scored.append(job)

        except Exception as e:
            print(f"[AI评分] 评分失败: {e}")
            for job in batch:
                bonus = 10 if _is_priority_company(job.get("company", "")) else 0
                adjusted, rule_note = _pre_score_adjust(job, 50)
                job["score"] = min(100, adjusted + bonus)
                job["score_reason"] = f"评分出错: {str(e)[:60]}"
                all_scored.append(job)

        if batch_start + batch_size < len(jobs):
            time.sleep(3)

    all_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = all_scored[0].get("score", 0) if all_scored else 0
    print(f"[AI评分] ✓ 完成，最高分: {top}")
    return all_scored
