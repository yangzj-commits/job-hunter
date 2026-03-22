"""
求职雷达 · 主程序
运行顺序：
  1. 抓取前程无忧岗位（主力数据源）
  2. 监控白名单公司官网（哈希对比）
  3. 公司自动发现（杰出雇主榜单 + 欧盟商会）
  4. 合并数据，AI 批量评分
  5. 去重过滤（排除历史已推送）
  6. 发送 Gmail 日报
  7. 持久化历史记录（git commit 由 GitHub Actions 执行）
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.scrapers.job51 import fetch_51job_jobs
from src.scrapers.website_monitor import monitor_company_websites
from src.discovery.company_finder import run_company_discovery
from src.ai_scorer import score_jobs_with_gemini
from src.state_manager import filter_new_jobs, save_sent_jobs, make_job_id
from src.email_sender import send_report


def main():
    print("=" * 60)
    print("求职雷达启动")
    print("=" * 60)
    start_time = time.time()
    all_jobs = []

    # ── 步骤1：前程无忧主力抓取 ──────────────────────────────────
    print("\n【步骤1】前程无忧岗位抓取")
    try:
        jobs_51 = fetch_51job_jobs(max_pages=2)
        all_jobs.extend(jobs_51)
        print(f"  ✓ 前程无忧抓取完成：{len(jobs_51)} 个岗位")
    except Exception as e:
        print(f"  ✗ 前程无忧抓取失败：{e}")

    # ── 步骤2：官网监控 ───────────────────────────────────────────
    print("\n【步骤2】白名单公司官网监控")
    try:
        jobs_monitor = monitor_company_websites()
        all_jobs.extend(jobs_monitor)
        print(f"  ✓ 官网监控完成：{len(jobs_monitor)} 个变动提示")
    except Exception as e:
        print(f"  ✗ 官网监控失败：{e}")

    # ── 步骤3：公司自动发现 ───────────────────────────────────────
    print("\n【步骤3】公司自动发现")
    new_companies = []
    try:
        discovered_jobs, new_companies = run_company_discovery()
        all_jobs.extend(discovered_jobs)
        print(f"  ✓ 发现完成：{len(discovered_jobs)} 个岗位，{len(new_companies)} 家新公司候选")
    except Exception as e:
        print(f"  ✗ 公司发现模块失败：{e}")

    total_scraped = len(all_jobs)
    print(f"\n合计抓取：{total_scraped} 个岗位（含所有来源）")

    if not all_jobs:
        print("本次运行未抓取到任何岗位，发送空报告")
        send_report([], new_companies, 0)
        return

    # ── 步骤4：AI 批量评分 ────────────────────────────────────────
    print("\n【步骤4】Gemini AI 评分")
    try:
        all_jobs = score_jobs_with_gemini(all_jobs)
        print(f"  ✓ 评分完成")
    except Exception as e:
        print(f"  ✗ AI评分失败：{e}，使用默认分数")
        for job in all_jobs:
            job.setdefault("score", 50)
            job.setdefault("score_reason", "")
            job.setdefault("apply_type", "")

    # ── 步骤5：去重过滤 ───────────────────────────────────────────
    print("\n【步骤5】去重过滤")
    new_jobs = filter_new_jobs(all_jobs)
    print(f"  ✓ 过滤完成：{len(new_jobs)} 个新岗位待推送")

    # ── 步骤6：发送邮件 ───────────────────────────────────────────
    print("\n【步骤6】发送邮件报告")
    send_report(new_jobs, new_companies, total_scraped)

    # ── 步骤7：持久化历史记录 ─────────────────────────────────────
    print("\n【步骤7】保存历史记录")
    if new_jobs:
        new_ids = {make_job_id(j) for j in new_jobs}
        save_sent_jobs(new_ids)
        print(f"  ✓ 已保存 {len(new_ids)} 条新记录")
    else:
        print("  无新岗位，无需更新记录")

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"运行完成，耗时 {elapsed:.1f} 秒")
    print(f"本次推送 {len(new_jobs)} 个新岗位")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
