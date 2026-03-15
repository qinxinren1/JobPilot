# Job Application Agent

独立的投递流程模块，所有数据存储在 `~/.jobpilot/` 目录下。

## 在 Claude Desktop 中使用

### 1. 配置 MCP 服务器

在 Claude Desktop 的 MCP 配置文件中添加 agent 服务器：

**配置文件位置**:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

**配置内容**:
```json
{
  "mcpServers": {
    "jobpilot-agent": {
      "command": "python",
      "args": ["-m", "jobpilot.agent.mcp_server"]
    },
    "playwright": {
      "command": "npx",
      "args": [
        "@playwright/mcp@latest",
        "--cdp-endpoint=http://localhost:9222"
      ]
    }
  }
}
```

### 2. 启动 Chrome（带 CDP）

在使用前，需要启动一个 Chrome 实例：

```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-debug

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

# Windows
chrome.exe --remote-debugging-port=9222 --user-data-dir=%TEMP%\chrome-debug
```

### 3. 在 Claude Desktop 中使用

重启 Claude Desktop 后，你可以直接与 Claude 对话来管理岗位和申请：

**添加岗位（最简单的方式）**:
```
我复制了一个职位链接，请帮我添加到申请队列：
https://greenhouse.io/company/jobs/123
```

或者：
```
请帮我添加这个岗位：https://example.com/jobs/123
```

工具会自动：
- ✅ 使用enrichment模块提取完整职位描述（full_description）
- ✅ 提取职位标题、公司名称、位置、薪资
- ✅ 检测申请URL（application_url）
- ✅ **存储到SQLite数据库**（与pipeline一致）
- ✅ **自动打分**（使用LLM评估匹配度，1-10分）
- ✅ 添加到agent申请队列

**手动添加岗位（如果自动提取失败）**:
```
请帮我添加一个岗位到申请队列：
- URL: https://example.com/jobs/123
- 职位: Software Engineer
- 公司: Example Corp
- 申请URL: https://example.com/jobs/123/apply
```

**查看岗位列表**:
```
显示所有待申请的岗位
```

**申请单个岗位**:
```
请帮我申请这个岗位：https://example.com/jobs/123
```

**批量申请**:
```
处理队列中的前5个岗位，使用2个并行worker
```

**查看结果**:
```
显示最近的申请结果
```

## 可用工具（MCP）

| 工具 | 说明 |
|------|------|
| `add_job_from_url` | **推荐** 只需粘贴URL，自动提取职位信息并添加到队列 |
| `add_job` | 手动添加岗位（需要提供所有信息） |
| `list_jobs` | 查看所有待申请的岗位 |
| `apply_to_job` | 申请单个岗位 |
| `run_agent_batch` | 批量处理多个岗位 |
| `get_profile` | 获取用户profile信息 |
| `detect_ats` | 检测ATS类型 |
| `get_results` | 查看申请结果 |
| `score_job_in_database` | 对数据库中的职位进行打分（或重新打分） |
| `remove_job` | 从队列中移除岗位 |

## 使用示例（Claude Desktop）

### 示例1: 快速添加并申请岗位（推荐）

```
用户: 我复制了这个职位链接，请帮我添加并申请：
      https://greenhouse.io/example/jobs/123

Claude: [使用add_job_from_url]
        - 访问页面并提取完整职位信息
        - 存储到SQLite数据库（jobs表）
        - 添加到agent申请队列
        [使用apply_to_job申请岗位]
        [返回申请结果]
```

**注意**: 职位信息会同时存储在：
- SQLite数据库 (`~/.jobpilot/jobpilot.db` 的 `jobs` 表)
- Agent队列 (`~/.jobpilot/agent_jobs.json`)

这样你可以：
- 在数据库中查看和管理（与其他pipeline的职位一起）
- 使用agent工具进行申请

### 示例1b: 只添加不申请

```
用户: 请把这个职位添加到队列：
      https://linkedin.com/jobs/view/123456

Claude: [使用add_job_from_url提取信息并添加]
        [显示提取到的职位信息]
```

### 示例2: 批量处理

```
用户: 我有10个岗位在队列中，请帮我处理前5个

Claude: [使用run_agent_batch处理5个岗位]
        [显示处理结果和统计]
```

### 示例3: 查看状态

```
用户: 显示我的申请统计

Claude: [使用get_results获取结果]
        [显示已申请、失败、待处理的数量]
```

### 示例4: 手动打分

```
用户: 请对这个职位重新打分：
      https://example.com/jobs/123

Claude: [使用score_job_in_database对职位进行打分]
        [返回打分结果：匹配度分数、关键词、理由]
```

## 目录结构

```
src/jobpilot/agent/
├── __init__.py          # 模块导出
├── config.py            # 配置管理（读取~/.jobpilot/）
├── ats_detector.py      # ATS类型检测（Greenhouse/Lever/Workday等）
├── prompts.py           # Claude提示构建
├── apply_agent.py       # 主调度逻辑
└── mcp_server.py        # MCP服务器（用于Claude Desktop）
```

## 数据文件

所有数据存储在 `~/.jobpilot/` 目录：

- `agent_jobs.json` - 待申请的岗位列表
- `agent_results.json` - 申请结果记录
- `agent_settings.json` - Agent配置
- `agent_logs/` - 申请日志目录
- `agent_chrome_workers/` - Chrome worker配置
- `agent_apply_workers/` - 申请worker工作目录

## 使用方式（Python API）

### 1. 准备岗位数据

创建 `~/.jobpilot/agent_jobs.json`:

```json
[
  {
    "url": "https://example.com/jobs/123",
    "application_url": "https://example.com/jobs/123/apply",
    "title": "Software Engineer",
    "company": "Example Corp",
    "tailored_resume_path": "~/.jobpilot/tailored_resumes/job_123.pdf",
    "cover_letter_path": "~/.jobpilot/cover_letters/job_123.pdf"
  }
]
```

### 2. 运行Agent

```python
from jobpilot.agent import run_agent

# 运行agent，处理10个岗位，使用2个并行worker
run_agent(
    limit=10,           # 处理10个岗位（None = 处理所有）
    workers=2,          # 2个并行worker
    model="sonnet",     # Claude模型
    headless=False,     # 显示浏览器窗口
    dry_run=False,      # 实际提交（True = 仅测试，不提交）
)
```

### 3. 查看结果

结果保存在 `~/.jobpilot/agent_results.json`:

```json
[
  {
    "status": "applied",
    "job_url": "https://example.com/jobs/123",
    "job_title": "Software Engineer",
    "company": "Example Corp",
    "duration_ms": 45000,
    "timestamp": "2024-01-01T12:00:00"
  }
]
```

## 核心功能

### ATS检测

自动检测ATS类型（Greenhouse, Lever, Workday等），提供针对性的填写指导。

### 导航工具

从职位列表页自动导航到真正的申请表：
- 检测"Apply"按钮
- 处理重定向
- 识别表单页面
- 支持多种ATS模式

### 智能提示

根据ATS类型、用户资料、岗位信息构建完整的Claude提示，包含：
- 导航指引
- ATS特定规则
- CAPTCHA处理
- 表单填写策略

## 配置

Agent设置保存在 `~/.jobpilot/agent_settings.json`:

```json
{
  "workers": 1,
  "model": "sonnet",
  "headless": false,
  "min_score": 7,
  "poll_interval": 60,
  "viewport": "1280x720"
}
```

## 依赖

- Claude Code CLI（必须）
- Chrome/Chromium（必须）
- Node.js + npx（用于Playwright MCP）
- CapSolver API key（可选，用于CAPTCHA）

## 注意事项

1. 确保 `~/.jobpilot/profile.json` 存在并配置完整
2. 确保简历PDF文件路径正确
3. 如果岗位URL是列表页，agent会自动导航到申请表
4. 支持多worker并行处理，每个worker使用独立的Chrome实例
