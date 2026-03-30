"""
求职雷达 · 主程序 (v3.5)
新增：
  - 轨道C：公司发现引擎（榜单/行业/地域三策略自动发现优质公司）
  - 白名单保护：不会用更少条目覆盖已有白名单（防误删）
  - 白名单低于阈值时自动触发发现引擎补充

流程：
  1. 加载白名单和历史记录
  2. 【新】白名单不足时，运行公司发现引擎（轨道C）补充
  3. 双轨搜索（轨道A关键词 + 轨道B定向）
  4. AI评分
  5. 去重过滤
  6. 发送邮件
  7. 保存历史 + 更新白名单
"""

import os
import sys
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    GEMINI_MODEL, SEARCH_KEYWORDS, SEARCH_SITE_FILTER,
    TOP_JOBS_DISPLAY, AUTO_UPDATE_WHITELIST, WHITELIST_MAX_SIZE,
    AUTO_LEARN_MAX_CANDIDATES, DISCOVERY_ENABLED, DISCOVERY_MAX_ADD
)
from src.scrapers.job51 import fetch_all_jobs, _is_quality_company_batch
from src.company_discovery import discover_companies
from src.ai_scorer import score_jobs_with_gemini
from src.state_manager import load_history, filter_new_jobs, save_history
from src.email_sender import send_email

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
WHITELIST_PATH = os.path.join(DATA_DIR, "company_whitelist.json")
HISTORY_PATH = os.path.join(DATA_DIR, "sent_jobs.json")


def load_whitelist() -> list:
    try:
        with open(WHITELIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and len(data) > 0:
            return data
        print("[配置] 白名单文件为空")
        return []
    except FileNotFoundError:
        print("[配置] 白名单文件不存在，使用空列表")
        return []
    except Exception as e:
        print(f"[配置] 白名单加载异常: {e}，使用空列表")
        return []


def save_whitelist(new_whitelist: list, old_whitelist: list):
    """
    安全保存白名单：只在新白名单 ≥ 旧白名单数量时才保存。
    防止因程序异常导致白名单被清空。
    """
    if len(new_whitelist) < len(old_whitelist):
        print(f"[配置] ⚠️ 白名单保护：新列表({len(new_whitelist)}) < 旧列表({len(old_whitelist)})，跳过保存")
        return

    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(WHITELIST_PATH, "w", encoding="utf-8") as f:
            json.dump(new_whitelist, f, ensure_ascii=False, indent=2)
        print(f"[配置] 白名单已保存（共 {len(new_whitelist)} 家公司）")
    except Exception as e:
        print(f"[配置] 白名单保存失败: {e}")


def run_discovery(whitelist: list) -> list:
    """
    运行公司发现引擎（轨道C），发现新公司并通过质量筛选后加入白名单。
    """
    existing_names = {w.get("name", "").strip() for w in whitelist}

    # 第1步：发现候选公司
    candidates = discover_companies(existing_names)

    if not candidates:
        print("[公司发现] 未发现新候选公司")
        return whitelist

    # 第2步：限量
    if len(candidates) > DISCOVERY_MAX_ADD * 2:
        print(f"[公司发现] 候选 {len(candidates)} 家，截取前 {DISCOVERY_MAX_ADD * 2} 家送质量筛选")
        candidates = candidates[:DISCOVERY_MAX_ADD * 2]

    # 第3步：质量筛选（复用 job51 的四方案并行筛选）
    print(f"[公司发现] 对 {len(candidates)} 家候选公司进行质量筛选...")
    time.sleep(1)
    qualified_map = _is_quality_company_batch(candidates)

    # 第4步：合格公司加入白名单
    newly_added = []
    for name in candidates:
        if not qualified_map.get(name, False):
            continue
        if len(whitelist) + len(newly_added) >= WHITELIST_MAX_SIZE:
            break
        if name not in existing_names:
            newly_added.append({
                "name": name,
                "careers_url": "",
                "auto_added": True,
                "source": "公司发现引擎",
            })
            existing_names.add(name)

        if len(newly_added) >= DISCOVERY_MAX_ADD:
            break

    if newly_added:
        print(f"[公司发现] ✓ 通过质量筛选，新增 {len(newly_added)} 家: "
              f"{', '.join(c['name'] for c in newly_added)}")
    else:
        print("[公司发现] 本次无公司通过质量筛选")

    return whitelist + newly_added


def main():
    start_time = time.time()
    run_date = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    print("=" * 60)
    print("求职雷达启动 (v3.5)")
    print("=" * 60)

    # ── 步骤1：加载配置 ──
    print("\n【步骤1】加载配置")
    whitelist = load_whitelist()
    original_whitelist = list(whitelist)  # 保存原始副本，用于保护检查
    history = load_history(HISTORY_PATH)
    print(f"  白名单: {len(whitelist)} 家公司")
    print(f"  历史记录: {len(history)} 条")

    # ── 步骤2：公司发现引擎（轨道C）──
    print("\n【步骤2】公司发现引擎（轨道C）")
    if not DISCOVERY_ENABLED:
        print("  公司发现引擎已关闭")
    elif len(whitelist) >= WHITELIST_MAX_SIZE:
        print(f"  白名单已满（{len(whitelist)}/{WHITELIST_MAX_SIZE}），跳过发现引擎")
    else:
        remaining = WHITELIST_MAX_SIZE - len(whitelist)
        print(f"  白名单 {len(whitelist)}/{WHITELIST_MAX_SIZE}，还可补充 {remaining} 家，启动发现引擎")
        whitelist = run_discovery(whitelist)
        print(f"  ✓ 发现引擎完成，白名单更新至 {len(whitelist)} 家")

    # ── 步骤3：双轨搜索 ──
    print("\n【步骤3】双轨岗位搜索")
    config = {
        "SEARCH_KEYWORDS": SEARCH_KEYWORDS,
        "SEARCH_SITE_FILTER": SEARCH_SITE_FILTER,
        "AUTO_UPDATE_WHITELIST": AUTO_UPDATE_WHITELIST,
        "WHITELIST_MAX_SIZE": WHITELIST_MAX_SIZE,
        "AUTO_LEARN_MAX_CANDIDATES": AUTO_LEARN_MAX_CANDIDATES,
        "TOP_JOBS_DISPLAY": TOP_JOBS_DISPLAY,
    }

    all_jobs, updated_whitelist = fetch_all_jobs(config, whitelist)
    total_scraped = len(all_jobs)
    print(f"\n  ✓ 搜索完成：{total_scraped} 个岗位")

    print("\n【步骤4】公司自动发现（自动学习）")
    new_companies = [c for c in updated_whitelist if c.get("auto_added")]
    print(f"  ✓ 本次自动发现 {len(new_companies)} 家新公司")

    # ── 步骤5：AI评分 ──
    print("\n【步骤5】AI 评分")
    scored_jobs = score_jobs_with_gemini(all_jobs)
    print(f"  ✓ 评分完成，最高分: {max((j.get('score',0) for j in scored_jobs), default=0)}")

    # ── 步骤6：去重过滤 ──
    print("\n【步骤6】去重过滤")
    new_jobs = filter_new_jobs(scored_jobs, history)

    # ── 步骤7：发送邮件 ──
    print("\n【步骤7】发送邮件报告")
    if new_jobs:
        send_email(
            jobs=new_jobs,
            run_date=run_date,
            total_scraped=total_scraped,
            new_companies=new_companies,
        )
    else:
        print("  无新岗位，跳过发送")

    # ── 步骤8：保存 ──
    print("\n【步骤8】保存历史记录与白名单")
    updated_history = save_history(new_jobs, history, HISTORY_PATH)
    print(f"  历史记录: {len(updated_history)} 条（新增 {len(new_jobs)} 条）")

    # 安全保存白名单（带保护检查）
    if len(updated_whitelist) > len(original_whitelist):
        save_whitelist(updated_whitelist, original_whitelist)
    elif len(updated_whitelist) < len(original_whitelist):
        print(f"  ⚠️ 白名单保护：更新后({len(updated_whitelist)}) < 原始({len(original_whitelist)})，不保存")
    else:
        print(f"  白名单无变化（{len(updated_whitelist)} 家）")

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"运行完成，耗时 {elapsed:.1f} 秒")
    print(f"本次推送 {len(new_jobs)} 个新岗位")
    print("=" * 60)


if __name__ == "__main__":
    main()
