"""
求职雷达 · AI评分模块 (v3.4 - 扩充过滤 + 规则兜底)
============================================================
v3.4 改动：
  1. EXCLUDE_KEYWORDS 扩充至 50+ 关键词，覆盖安检/维修/直播/
     开发/设计/人资/财务/游戏测试/行政等不相关方向
  2. 新增垃圾数据过滤：公司名含"某"/"未明确"/空 直接丢弃
  3. 新增规则引擎兜底评分：当AI评分不可用（429等）时，
     用岗位方向关键词匹配 + 白名单加分给出粗略分数，
     避免所有岗位都是统一的50/60分
  4. 推荐门槛调整说明：配合 email_sender 使用
"""

import os
import re
import json
import time

from openai import OpenAI

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
MODEL = "kimi-k2.5"
BASE_URL = "https://api.moonshot.cn/v1"

# thinking 模式：评分场景开启，控制 budget 避免过度消耗
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

# ---------- 直接排除的岗位关键词（v3.4 大幅扩充）----------
EXCLUDE_KEYWORDS = [
    # ── 体力劳动 / 工厂 ──
    "工厂实习", "生产实习", "设备巡检", "车间", "流水线", "装配", "生产工人",
    "品控员", "生产支持",

    # ── 安保 / 安检 ──
    "安检", "安检员", "地铁安检", "保安", "巡检员", "安保",

    # ── 维修 / 保养 ──
    "汽车维修", "汽车保养", "维修保养",

    # ── 中介 / 招聘 ──
    "猎头", "HR外包", "招聘实习", "灵活用工",

    # ── 销售地推 ──
    "地推", "BD实习", "业务拓展实习", "扫楼", "陌生拜访", "商务BD",

    # ── 财务记账 ──
    "出纳实习", "出纳", "会计助理", "记账实习", "做账", "财务实习",

    # ── 法务 ──
    "法务助理", "法律助理实习",

    # ── 设计 ──
    "平面设计", "UI设计", "视觉设计", "美工", "UE设计",

    # ── 基础服务 ──
    "司机", "厨师", "保洁",

    # ── 直播 / 短视频 / 内容创作 ──
    "主播", "直播运营", "直播", "短视频", "剪辑", "拍摄", "拍剪",
    "视频编导", "编导", "短视频后期", "短视频运营", "短视频剪辑",

    # ── 软件开发 / 编程（非目标方向）──
    "Java开发", "C++", "C/C++", "前端开发", "Web前端", "后端开发",
    "算法开发", "AI开发", "人工智能开发", "数据库开发",

    # ── 测试 ──
    "游戏测试", "测试实习",

    # ── 行政 / 党务 ──
    "党工团", "行政后勤", "行政安保", "行政实习",

    # ── 人力资源（纯HR岗）──
    "人资实习", "人力资源实习", "HR实习", "招聘信息发布",

    # ── 教育/招生 ──
    "招生", "培训顾问", "客户服务顾问",

    # ── 工程 / 建筑（非目标方向）──
    "工程造价", "机械工程",

    # ── 电商 ──
    "电商运营",
]

# ---------- 垃圾公司名关键词 ----------
GARBAGE_COMPANY_PATTERNS = [
    "某", "信息未明确", "未知", "匿名", "信息未",
]

# ---------- 车企关键词 ----------
CAR_COMPANY_KEYWORDS = [
    "汽车", "车", "宇通", "比亚迪", "上汽", "一汽", "吉利", "长安",
    "奔驰", "宝马", "奥迪", "丰田", "本田", "大众", "福特", "沃尔沃",
]

# ---------- 规则引擎评分：方向关键词及对应加分 ----------
DIRECTION_SCORE_MAP = {
    "数据分析": 30,
    "商业分析": 30,
    "BI": 25,
    "信息管理": 25,
    "信息化": 20,
    "ERP": 25,
    "实施顾问": 20,
    "管理咨询": 25,
    "风险咨询": 25,
    "咨询": 20,
    "审计": 20,
    "产品运营": 20,
    "供应链运营": 20,
    "供应链": 15,
    "运营": 10,
    "产品经理": 20,
    "项目管理": 20,
    "项目助理": 15,
    "数字化": 20,
    "IT支持": 15,
    "系统支持": 15,
    "软件交付": 15,
}

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=KIMI_API_KEY,
            base_url=BASE_URL,
            timeout=60,
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
    """预过滤：排除关键词命中 + 垃圾公司名"""
    result = []
    for job in jobs:
        title = job.get("title", "")
        company = job.get("company", "").strip()

        # 垃圾公司名过滤
        if not company or len(company) < 2:
            print(f"  [过滤] 垃圾数据（公司名无效）: {title} @ {company or '(空)'}")
            continue
        if any(p in company for p in GARBAGE_COMPANY_PATTERNS):
            print(f"  [过滤] 垃圾数据（公司名模糊）: {title} @ {company}")
            continue

        # 关键词排除
        combined = title + company
        excluded = False
        for kw in EXCLUDE_KEYWORDS:
            if kw in combined:
                print(f"  [过滤] 排除({kw}): {title} @ {company}")
                excluded = True
                break
        if excluded:
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


def _rule_based_score(job: dict) -> tuple:
    """
    规则引擎兜底评分：当AI评分不可用时使用。
    基于岗位标题中的方向关键词匹配 + 白名单公司加分，
    给出 0-100 的粗略分数，保留基本区分能力。
    """
    title = job.get("title", "")
    company = job.get("company", "")
    score = 35  # 基础分

    # 方向关键词加分（只取最高匹配的一个）
    best_direction_bonus = 0
    matched_direction = ""
    for kw, bonus in DIRECTION_SCORE_MAP.items():
        if kw in title and bonus > best_direction_bonus:
            best_direction_bonus = bonus
            matched_direction = kw
    score += best_direction_bonus

    # 白名单公司加分
    if _is_priority_company(company):
        score += 10

    # 全职压分
    if job.get("apply_type") == "fulltime":
        score = min(score, 18)

    # 非车企销售降分
    if "销售" in title and not _is_car_company(company):
        score = max(0, score - 20)

    score = min(100, max(0, score))

    reason_parts = []
    if matched_direction:
        reason_parts.append(f"方向匹配:{matched_direction}")
    if _is_priority_company(company):
        reason_parts.append("重点目标公司")
    reason_parts.append("规则引擎评分(AI不可用)")

    return score, " | ".join(reason_parts)


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
    """函数名保持不变（被main.py调用），内部已切换为 Kimi + thinking 模式。"""
    if not jobs:
        return []

    if not KIMI_API_KEY:
        print("[AI评分] 未配置 KIMI_API_KEY，使用规则引擎评分")
        for job in jobs:
            score, reason = _rule_based_score(job)
            job["score"] = score
            job["score_reason"] = reason
        return jobs

    jobs = _pre_filter(jobs)
    print(f"[AI评分] 预过滤后剩余 {len(jobs)} 个岗位")

    batch_size = 10
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
                max_tokens=3000,
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
            err_str = str(e)
            is_429 = "429" in err_str
            if is_429:
                print(f"[AI评分] 批次{batch_num} 限流(429)，使用规则引擎兜底")
            else:
                print(f"[AI评分] 评分失败: {err_str[:100]}，使用规则引擎兜底")

            # v3.4：改用规则引擎兜底，不再统一给50/60分
            for job in batch:
                score, reason = _rule_based_score(job)
                # 规则引擎的结果也走 _pre_score_adjust
                adjusted, rule_note = _pre_score_adjust(job, score)
                if rule_note:
                    reason = f"{reason} | [{rule_note}]"
                job["score"] = adjusted
                job["score_reason"] = reason
                all_scored.append(job)

        if batch_start + batch_size < len(jobs):
            time.sleep(3)

    all_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = all_scored[0].get("score", 0) if all_scored else 0
    print(f"[AI评分] ✓ 完成，最高分: {top}")
    return all_scored
