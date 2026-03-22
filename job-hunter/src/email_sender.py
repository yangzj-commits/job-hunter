"""
Gmail 邮件发送模块
生成美观的 HTML 格式每日求职报告
包含：岗位卡片、AI评分、申请链接、新发现公司候选
"""

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_RECIPIENT


def _score_badge(score: int) -> tuple[str, str]:
    """根据分数返回标签文字和颜色"""
    if score >= 80:
        return "强烈推荐", "#1a7f37"
    elif score >= 60:
        return "值得申请", "#0969da"
    elif score >= 40:
        return "可以考虑", "#9a6700"
    else:
        return "仅供参考", "#888"


def _source_badge_color(source: str) -> str:
    colors = {
        "前程无忧": "#e05d00",
        "猎聘": "#2c5fff",
        "官网监控": "#6f42c1",
        "欧盟商会招聘": "#1a7f37",
        "发现模块": "#0969da",
    }
    return colors.get(source, "#444")


def _render_job_card(job: dict) -> str:
    score = job.get("score", 0)
    badge_text, badge_color = _score_badge(score)
    source_color = _source_badge_color(job.get("source", ""))
    monitor_note = ""
    if job.get("_monitor_flag"):
        monitor_note = '<div style="color:#9a6700;font-size:12px;margin-top:6px;">⚠️ 来自官网监控，建议前往官网确认岗位信息</div>'

    return f"""
<div style="border:1px solid #e1e4e8;border-radius:8px;padding:16px;margin-bottom:12px;background:#fff;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
    <div style="flex:1;min-width:200px;">
      <div style="font-size:16px;font-weight:600;color:#1f2328;margin-bottom:4px;">
        {job.get('title','')}
      </div>
      <div style="font-size:14px;color:#57606a;margin-bottom:8px;">
        {job.get('company','')}
        &nbsp;·&nbsp;{job.get('location','郑州')}
        &nbsp;·&nbsp;{job.get('salary','薪资面议')}
      </div>
      {"<div style='font-size:12px;color:#57606a;'>经验: " + job.get('experience','') + "&nbsp;|&nbsp;学历: " + job.get('education','') + "</div>" if job.get('experience') or job.get('education') else ""}
    </div>
    <div style="text-align:right;flex-shrink:0;">
      <div style="font-size:22px;font-weight:700;color:{badge_color};">{score}分</div>
      <div style="font-size:11px;color:{badge_color};margin-bottom:4px;">{badge_text}</div>
      <span style="background:{source_color};color:#fff;font-size:11px;padding:2px 8px;border-radius:12px;">{job.get('source','')}</span>
    </div>
  </div>
  {"<div style='font-size:12px;color:#57606a;margin-top:8px;padding-top:8px;border-top:1px solid #f0f0f0;'>AI评语: " + job.get('score_reason','') + "</div>" if job.get('score_reason') else ""}
  {monitor_note}
  <div style="margin-top:10px;">
    <a href="{job.get('url','#')}" style="background:#0969da;color:#fff;text-decoration:none;padding:6px 14px;border-radius:6px;font-size:13px;">查看岗位 →</a>
    {"&nbsp;&nbsp;<span style='font-size:12px;color:#57606a;'>投递类型: " + job.get('apply_type','') + "</span>" if job.get('apply_type') else ""}
  </div>
</div>"""


def _render_company_candidates(companies: list[dict]) -> str:
    """渲染新发现公司候选列表"""
    if not companies:
        return ""
    items = ""
    for c in companies[:15]:  # 最多展示15个
        items += f"<li style='margin-bottom:4px;'><b>{c.get('name','')}</b> — 来源: {c.get('source','')}</li>"
    return f"""
<div style="border:1px solid #d4a017;border-radius:8px;padding:16px;margin-bottom:20px;background:#fffbec;">
  <h3 style="margin:0 0 10px;color:#9a6700;font-size:15px;">🔍 本周新发现企业候选（待你确认）</h3>
  <p style="font-size:13px;color:#57606a;margin:0 0 10px;">以下企业由自动发现模块从杰出雇主榜单等渠道获取，请确认后告知是否加入监控白名单：</p>
  <ul style="font-size:13px;color:#1f2328;margin:0;padding-left:20px;">{items}</ul>
</div>"""


def build_email_html(
    jobs: list[dict],
    new_companies: list[dict],
    run_date: str,
    total_scraped: int,
) -> str:
    """构建完整的 HTML 邮件内容"""
    # 按分数分组
    top_jobs = [j for j in jobs if j.get("score", 0) >= 60]
    rest_jobs = [j for j in jobs if j.get("score", 0) < 60]

    top_cards = "".join(_render_job_card(j) for j in top_jobs)
    rest_cards = "".join(_render_job_card(j) for j in rest_jobs[:20]) if rest_jobs else ""

    company_section = _render_company_candidates(new_companies)

    rest_section = ""
    if rest_cards:
        rest_section = f"""
<details style="margin-top:20px;">
  <summary style="cursor:pointer;color:#0969da;font-size:14px;">▶ 查看其他岗位（共 {len(rest_jobs)} 个，分数 &lt; 60）</summary>
  <div style="margin-top:12px;">{rest_cards}</div>
</details>"""

    no_jobs_msg = ""
    if not jobs:
        no_jobs_msg = '<div style="padding:20px;text-align:center;color:#57606a;">今日暂无新岗位推送</div>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f6f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<div style="max-width:680px;margin:0 auto;padding:20px;">

  <!-- 顶部标题 -->
  <div style="background:#1f2328;border-radius:8px;padding:20px 24px;margin-bottom:20px;color:#fff;">
    <h1 style="margin:0 0 6px;font-size:20px;">📡 求职雷达日报</h1>
    <div style="font-size:13px;color:#aaa;">{run_date} · 共抓取 {total_scraped} 个岗位 · 推送 {len(jobs)} 个新岗位</div>
  </div>

  {company_section}

  <!-- 推荐岗位 -->
  {"<h2 style='font-size:16px;color:#1f2328;margin:0 0 12px;'>⭐ 推荐岗位（评分 ≥ 60）</h2>" if top_jobs else ""}
  {top_cards}
  {no_jobs_msg}
  {rest_section}

  <!-- 底部 -->
  <div style="margin-top:24px;padding-top:16px;border-top:1px solid #e1e4e8;font-size:12px;color:#57606a;text-align:center;">
    由求职雷达自动生成 · 运行于 GitHub Actions<br>
    如需调整筛选条件，请修改 config.py
  </div>
</div>
</body>
</html>"""


def send_report(
    jobs: list[dict],
    new_companies: list[dict],
    total_scraped: int,
):
    """发送每日求职报告到 Gmail"""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("[邮件] 未配置 Gmail 凭据，跳过发送（本地调试模式）")
        # 本地调试时把 HTML 保存到文件
        html = build_email_html(jobs, new_companies,
                                datetime.now().strftime("%Y-%m-%d %H:%M"), total_scraped)
        with open("/tmp/report_preview.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("[邮件] 已将报告保存到 /tmp/report_preview.html")
        return

    run_date = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    subject = f"📡 求职雷达 {datetime.now().strftime('%m/%d')} · {len(jobs)} 个新岗位"

    html_content = build_email_html(jobs, new_companies, run_date, total_scraped)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = EMAIL_RECIPIENT
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, EMAIL_RECIPIENT, msg.as_string())
        print(f"[邮件] 发送成功 → {EMAIL_RECIPIENT}")
    except Exception as e:
        print(f"[邮件] 发送失败: {e}")
        raise
