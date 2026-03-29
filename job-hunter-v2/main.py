"""
求职雷达 · 主程序 (v3.4)
每次运行流程：
  1. 从文件加载白名单和历史记录
  2. 双轨搜索（轨道A关键词 + 轨道B定向）
  3. AI评分（Kimi thinking 模式，429时规则引擎兜底）
  4. 去重过滤
  5. 发送邮件
  6. 保存历史 + 更新白名单（自动学习）
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
    AUTO_LEARN_MAX_CANDIDATES
)
from src.scrapers.job51 import fetch_all_jobs
from src.ai_scorer import score_jobs_with_gemini
from src.state_manager import load_history, filter_new_jobs, save_history
from src.email_sender import send_email

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
WHITELIST_PATH = os.path.join(DATA_DIR, "company_whitelist.json")
HISTORY_PATH = os.path.join(DATA_DIR, "sent_jobs.json")


def load_whitelist() -> list:
    try:
        with open(WHITELIST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        print("[配置] 白名单文件不存在，使用空列表")
        return []


def save_whitelist(whitelist: list):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(WHITELIST_PATH, "w", encoding="utf-8") as f:
            json.dump(whitelist, f, ensure_ascii=False, indent=2)
        print(f"[配置] 白名单已保存（共 {len(whitelist)} 家公司）")
    except Exception as e:
        print(f"[配置] 白名单保存失败: {e}")


def main():
    start_time = time.time()
    run_date = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    print("=" * 60)
    print("求职雷达启动 (v3.4)")
    print("=" * 60)

    print("\n【步骤1】前程无忧岗位抓取")
    whitelist = load_whitelist()
    history = load_history(HISTORY_PATH)
    print(f"  白名单: {len(whitelist)} 家公司")
    print(f"  历史记录: {len(history)} 条")

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
    print(f"\n  ✓ 前程无忧抓取完成：{total_scraped} 个岗位")

    print("\n【步骤2】官网监控（跳过）")

    print("\n【步骤3】公司自动发现")
    new_companies = [c for c in updated_whitelist if c.get("auto_added")]
    print(f"  ✓ 本次自动发现 {len(new_companies)} 家新公司")

    print("\n【步骤4】Gemini AI 评分")
    scored_jobs = score_jobs_with_gemini(all_jobs)
    print(f"  ✓ 评分完成，最高分: {max((j.get('score',0) for j in scored_jobs), default=0)}")

    print("\n【步骤5】去重过滤")
    new_jobs = filter_new_jobs(scored_jobs, history)

    print("\n【步骤6】发送邮件报告")
    if new_jobs:
        send_email(
            jobs=new_jobs,
            run_date=run_date,
            total_scraped=total_scraped,
            new_companies=new_companies,
        )
    else:
        print("  无新岗位，跳过发送")

    print("\n【步骤7】保存历史记录")
    updated_history = save_history(new_jobs, history, HISTORY_PATH)
    print(f"  已保存 {len(updated_history)} 条历史记录，新增 {len(new_jobs)} 条")

    if len(updated_whitelist) > len(whitelist):
        save_whitelist(updated_whitelist)

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"运行完成，耗时 {elapsed:.1f} 秒")
    print(f"本次推送 {len(new_jobs)} 个新岗位")
    print("=" * 60)


if __name__ == "__main__":
    main()
