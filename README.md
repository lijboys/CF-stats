# Cloudflare 统计数据获取与推送工具

这个 GitHub 项目可以自动获取 Cloudflare 账号下的 Pages 和 Workers 项目的请求量统计数据，并通过 Telegram Bot 推送给你。

## 功能特点

- 自动获取 Cloudflare Pages 项目的请求量
- 自动获取 Cloudflare Workers 的请求量
- 每天下午4点和晚上11点（UTC时间）定时执行
- 通过 Telegram Bot 推送统计报告和趋势图表
- 支持自定义波动报警阈值
- 存储历史数据用于趋势分析
- 完善的重试机制和错误处理

## 使用方法

### 前置条件

1. 拥有 Cloudflare 账号并有权限访问 API
2. 创建一个 Telegram Bot 并获取 Bot Token
3. 获取接收消息的 Telegram Chat ID
4. 准备一个 GitHub 仓库用于存储历史数据

### 部署步骤

1. Fork 此仓库到你的 GitHub 账号
2. 在仓库设置中添加以下 Secrets:
   - `CF_ACCOUNT_ID`: Cloudflare 账户 ID
   - `CF_API_TOKEN`: Cloudflare API Token（需要有 Pages 和 Workers 访问权限）
   - `TG_BOT_TOKEN`: Telegram Bot Token
   - `TG_CHAT_ID`: Telegram Chat ID
   - `GITHUB_TOKEN`: 具有写入仓库权限的 GitHub Token

3. 等待 GitHub Actions 自动触发，或手动触发工作流进行测试

### 配置说明

- 定时任务配置在 `.github/workflows/fetch-stats.yml` 文件中，可以根据需要修改 cron 表达式
- 数据获取逻辑在 `src/fetch_cloudflare_stats.py` 文件中，可以根据需要调整获取的数据范围和格式
- 波动报警阈值和其他配置项在 `config/config.json` 文件中

## 注意事项

- 请确保你的 Cloudflare API Token 具有足够的权限
- Telegram Bot 需要先启动并与你建立联系才能接收消息
- 默认统计时间范围为过去 24 小时，可以在代码中修改时间范围设置
- 如需调试，可以查看 GitHub Actions 运行日志获取详细信息
  
