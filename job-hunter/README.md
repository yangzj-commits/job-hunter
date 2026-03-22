# 求职雷达 · Job Hunter

自动抓取郑州岗位 → Gemini AI 评分筛选 → Gmail 每日推送

## 项目结构

```
job-hunter/
├── main.py                    # 主程序入口
├── config.py                  # 所有可调参数（关键词、画像、城市等）
├── requirements.txt
├── .github/workflows/
│   └── daily_job_hunt.yml     # 定时任务（周二/三/四 北京时间9点）
├── src/
│   ├── scrapers/
│   │   ├── job51.py           # 前程无忧抓取（无需登录）
│   │   └── website_monitor.py # 白名单官网监控
│   ├── discovery/
│   │   └── company_finder.py  # 自动发现新公司
│   ├── ai_scorer.py           # Gemini AI 评分
│   ├── email_sender.py        # Gmail 推送
│   └── state_manager.py       # 历史记录去重
└── data/
    ├── company_whitelist.json # 公司白名单（可手动编辑）
    ├── sent_jobs.json         # 已推送记录（自动维护）
    ├── website_hashes.json    # 官网哈希缓存（自动维护）
    └── discovered_companies.json # 新发现公司候选
```

---

## 部署步骤（Windows，约15分钟）

### 第一步：Fork 或上传到你的 GitHub

1. 登录 GitHub，点击右上角 **+** → **New repository**
2. 仓库名填 `job-hunter`，选 **Public**（公开仓库 Actions 完全免费）
3. 点击 **Create repository**

然后把整个 `job-hunter` 文件夹上传：
- 点击 **uploading an existing file**
- 把所有文件拖进去，点击 **Commit changes**

### 第二步：准备 Gmail App Password

1. 打开 [Google 账号安全设置](https://myaccount.google.com/security)
2. 找到 **两步验证**，确保已开启
3. 搜索 **应用专用密码**，点击进入
4. "选择应用"选 **邮件**，"选择设备"选 **其他（自定义名称）**
5. 输入名称 `job-hunter`，点击 **生成**
6. 复制这个 **16位密码**（只显示一次！）

### 第三步：准备 Gemini API Key

1. 打开 [Google AI Studio](https://aistudio.google.com/)
2. 左侧点击 **Get API key** → **Create API key**
3. 复制 API Key

### 第四步：在 GitHub 设置 Secrets

在你的仓库页面，点击 **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，依次添加：

| Secret 名称 | 值 |
|---|---|
| `GEMINI_API_KEY` | 你的 Gemini API Key |
| `GMAIL_USER` | 你的 Gmail 地址（如 xxx@gmail.com）|
| `GMAIL_APP_PASSWORD` | 第二步生成的16位密码 |
| `EMAIL_RECIPIENT` | 收件邮箱（可以和 GMAIL_USER 相同）|

### 第五步：手动触发测试

1. 进入仓库，点击 **Actions** 标签
2. 找到 **求职雷达每日运行**
3. 点击 **Run workflow** → **Run workflow**
4. 等待约3-5分钟，查看运行日志
5. 检查你的邮箱是否收到报告

---

## 自定义调整

**修改搜索关键词**：编辑 `config.py` 中的 `SEARCH_KEYWORDS` 列表

**添加要监控的公司官网**：编辑 `data/company_whitelist.json`，在对应公司的 `careers_url` 字段填入招聘页URL

**修改运行时间**：编辑 `.github/workflows/daily_job_hunt.yml` 中的 `cron` 表达式（UTC时间）

**修改 AI 评分依据**：编辑 `config.py` 中的 `PROFILE` 字典

---

## 运行频率说明

- **周二/三/四 北京时间9点**：主运行（岗位搜索+评分+推送）
- **官网监控**：每次主运行时执行
- **公司自动发现**：每次主运行时执行（杰出雇主榜单、欧盟商会）

---

## 成本说明

| 项目 | 成本 |
|---|---|
| GitHub Actions | 完全免费（公开仓库） |
| Gemini API | 完全免费（每天 < 250次调用） |
| Gmail SMTP | 完全免费 |
| **总计** | **¥0/月** |
