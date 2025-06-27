import os
import requests
import json
import logging
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import numpy as np
import time
from urllib.parse import quote

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

class CloudflareAPI:
    """与 Cloudflare API 交互的类"""
    
    def __init__(self, account_id: str, api_token: str):
        self.account_id = account_id
        self.api_token = api_token
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
    
    def fetch_pages_projects(self) -> List[Dict[str, Any]]:
        try:
            url = f"{self.base_url}/pages/projects"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()["result"]
        except Exception as e:
            logger.error(f"获取 Pages 项目失败: {str(e)}")
            return []
    
    def fetch_workers(self) -> List[Dict[str, Any]]:
        try:
            url = f"{self.base_url}/workers/scripts"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()["result"]
        except Exception as e:
            logger.error(f"获取 Workers 失败: {str(e)}")
            return []
    
    def fetch_pages_metrics(self, project_name: str, start: str, end: str) -> Dict[str, Any]:
        try:
            encoded_project_name = quote(project_name, safe='')
            url = f"{self.base_url}/pages/projects/{encoded_project_name}/metrics"
            params = {
                "since": start,
                "until": end,
                "continuous": "true"
            }
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()["result"]
        except Exception as e:
            logger.error(f"获取 Pages 指标失败: {str(e)}")
            return {}
    
    def fetch_workers_metrics(self, script_name: str, start: str, end: str) -> Dict[str, Any]:
        try:
            encoded_script_name = quote(script_name, safe='')
            url = f"{self.base_url}/workers/analytics/dashboard"
            params = {
                "script_name": encoded_script_name,
                "since": start,
                "until": end
            }
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()["result"]
        except Exception as e:
            logger.error(f"获取 Workers 指标失败: {str(e)}")
            return {}

class TelegramBot:
    """与 Telegram Bot API 交互的类"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        logger.info(f"Telegram Bot Token 验证: {bot_token[:5] + '...'}")
    
    def send_message(self, message: str) -> bool:
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }
            response = requests.post(url, json=data)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"发送 Telegram 消息失败: {str(e)}")
            return False
    
    def send_photo(self, photo_path: str, caption: str = "") -> bool:
        try:
            url = f"{self.base_url}/sendPhoto"
            files = {'photo': open(photo_path, 'rb')}
            data = {
                "chat_id": self.chat_id,
                "caption": caption,
                "parse_mode": "Markdown"
            }
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"发送 Telegram 图片失败: {str(e)}")
            return False

class CloudflareStatsTracker:
    """Cloudflare 统计数据跟踪器"""
    
    def __init__(self, config_path: str = "config/config.json"):
        # 从环境变量读取敏感信息（优先于配置文件）
        self.cf_account_id = os.getenv("CF_ACCOUNT_ID")
        self.cf_api_token = os.getenv("CF_API_TOKEN")
        self.tg_bot_token = os.getenv("TG_BOT_TOKEN")
        self.tg_chat_id = os.getenv("TG_CHAT_ID")
        
        # 验证环境变量
        if not all([self.cf_account_id, self.cf_api_token, self.tg_bot_token, self.tg_chat_id]):
            logger.error("环境变量中缺少必要的配置，请检查 GitHub Secrets")
            # 尝试从配置文件读取（作为备用）
            self._load_config(config_path)
        
        # 初始化 API 客户端
        self.cf_api = CloudflareAPI(self.cf_account_id, self.cf_api_token)
        self.tg_bot = TelegramBot(self.tg_bot_token, self.tg_chat_id)
        
        # 初始化数据存储
        self.current_data = {"pages": {}, "workers": {}}
        self.history_data = self._load_history()
        self.thresholds = self._get_thresholds()
        self.retry_config = self._get_retry_config()
    
    def _load_config(self, config_path: str) -> None:
        """从配置文件加载非敏感配置（备用方案）"""
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 从配置文件读取备用配置
                self.cf_account_id = self.cf_account_id or config.get("cloudflare", {}).get("account_id")
                self.cf_api_token = self.cf_api_token or config.get("cloudflare", {}).get("api_token")
                self.tg_bot_token = self.tg_bot_token or config.get("telegram", {}).get("bot_token")
                self.tg_chat_id = self.tg_chat_id or config.get("telegram", {}).get("chat_id")
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
    
    def _load_history(self) -> Dict[str, Any]:
        """加载历史数据"""
        history_file = os.getenv("HISTORY_FILE", "history/history.json")
        try:
            os.makedirs(os.path.dirname(history_file), exist_ok=True)
            if os.path.exists(history_file):
                with open(history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {"pages": {}, "workers": {}}
        except Exception as e:
            logger.error(f"加载历史数据失败: {str(e)}")
            return {"pages": {}, "workers": {}}
    
    def _save_history(self) -> None:
        """保存历史数据"""
        history_file = os.getenv("HISTORY_FILE", "history/history.json")
        try:
            os.makedirs(os.path.dirname(history_file), exist_ok=True)
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存历史数据失败: {str(e)}")
    
    def _get_thresholds(self) -> Dict[str, int]:
        """获取阈值配置（从环境变量或默认值）"""
        thresholds = {}
        for key in ["pages_request_increase", "pages_request_decrease", 
                   "workers_request_increase", "workers_request_decrease"]:
            env_key = f"THRESHOLD_{key.upper()}"
            thresholds[key] = int(os.getenv(env_key, 30)) if key.startswith("pages") else int(os.getenv(env_key, 35))
        return thresholds
    
    def _get_retry_config(self) -> Dict[str, int]:
        """获取重试配置（从环境变量或默认值）"""
        return {
            "max_attempts": int(os.getenv("RETRY_MAX_ATTEMPTS", 3)),
            "delay": int(os.getenv("RETRY_DELAY", 1))
        }
    
    def _retry(self, func, *args, **kwargs):
        """重试机制装饰器"""
        max_attempts = self.retry_config["max_attempts"]
        delay = self.retry_config["delay"]
        
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise
                logger.warning(f"尝试 {attempt + 1}/{max_attempts} 失败: {str(e)}，{delay}秒后重试")
                time.sleep(delay)
    
    def fetch_stats(self) -> None:
        """获取当前统计数据"""
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=24)
        start_str = start_time.isoformat(timespec='seconds') + 'Z'
        end_str = end_time.isoformat(timespec='seconds') + 'Z'
        
        pages_projects = self._retry(self.cf_api.fetch_pages_projects)
        for project in pages_projects:
            project_name = project["name"]
            metrics = self._retry(self.cf_api.fetch_pages_metrics, project_name, start_str, end_str)
            if metrics and "requests" in metrics:
                self.current_data["pages"][project_name] = metrics["requests"]
        
        workers = self._retry(self.cf_api.fetch_workers)
        for worker in workers:
            # 关键修改：安全获取 worker 名称
            worker_name = worker.get("name", f"未知Worker_{id(worker)}")
            logger.info(f"处理 Worker: {worker_name}")  # 添加日志帮助调试
            
            # 验证 worker 对象结构是否符合预期
            if not isinstance(worker, dict):
                logger.warning(f"Worker 对象不是字典类型: {type(worker)}")
                continue
            
            metrics = self._retry(self.cf_api.fetch_workers_metrics, worker_name, start_str, end_str)
            if metrics and "script" in metrics and "requests" in metrics["script"]:
                self.current_data["workers"][worker_name] = metrics["script"]["requests"]
        
        logger.info(f"成功获取统计数据: Pages项目={len(self.current_data['pages'])}, Workers={len(self.current_data['workers'])}")
    
    def update_history(self) -> None:
        """更新历史数据"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        for project, requests in self.current_data["pages"].items():
            if project not in self.history_data["pages"]:
                self.history_data["pages"][project] = {}
            self.history_data["pages"][project][today] = requests
        
        for worker, requests in self.current_data["workers"].items():
            if worker not in self.history_data["workers"]:
                self.history_data["workers"][worker] = {}
            self.history_data["workers"][worker][today] = requests
        
        storage_days = int(os.getenv("HISTORY_STORAGE_DAYS", 30))
        cutoff_date = (datetime.now() - timedelta(days=storage_days)).strftime("%Y-%m-%d")
        
        for project in list(self.history_data["pages"].keys()):
            self.history_data["pages"][project] = {date: req for date, req in self.history_data["pages"][project].items() if date >= cutoff_date}
            if not self.history_data["pages"][project]:
                del self.history_data["pages"][project]
        
        for worker in list(self.history_data["workers"].keys()):
            self.history_data["workers"][worker] = {date: req for date, req in self.history_data["workers"][worker].items() if date >= cutoff_date}
            if not self.history_data["workers"][worker]:
                del self.history_data["workers"][worker]
        
        self._save_history()
    
    def check_thresholds(self) -> List[str]:
        """检查阈值并生成警报"""
        alerts = []
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        for project, requests in self.current_data["pages"].items():
            if project in self.history_data["pages"] and yesterday in self.history_data["pages"][project]:
                yesterday_requests = self.history_data["pages"][project][yesterday]
                if yesterday_requests > 0:
                    change_percent = ((requests - yesterday_requests) / yesterday_requests) * 100
                    if change_percent >= self.thresholds["pages_request_increase"]:
                        alerts.append(f"📈 警告: Pages项目 '{project}' 请求量增长异常 ({change_percent:.1f}%)\n"
                                     f"昨日: {yesterday_requests:,} → 今日: {requests:,}")
                    if change_percent <= -self.thresholds["pages_request_decrease"]:
                        alerts.append(f"📉 警告: Pages项目 '{project}' 请求量下降异常 ({abs(change_percent):.1f}%)\n"
                                     f"昨日: {yesterday_requests:,} → 今日: {requests:,}")
        
        for worker, requests in self.current_data["workers"].items():
            if worker in self.history_data["workers"] and yesterday in self.history_data["workers"][worker]:
                yesterday_requests = self.history_data["workers"][worker][yesterday]
                if yesterday_requests > 0:
                    change_percent = ((requests - yesterday_requests) / yesterday_requests) * 100
                    if change_percent >= self.thresholds["workers_request_increase"]:
                        alerts.append(f"📈 警告: Workers服务 '{worker}' 请求量增长异常 ({change_percent:.1f}%)\n"
                                     f"昨日: {yesterday_requests:,} → 今日: {requests:,}")
                    if change_percent <= -self.thresholds["workers_request_decrease"]:
                        alerts.append(f"📉 警告: Workers服务 '{worker}' 请求量下降异常 ({abs(change_percent):.1f}%)\n"
                                     f"昨日: {yesterday_requests:,} → 今日: {requests:,}")
        
        return alerts
    
    def generate_charts(self) -> List[str]:
        """生成趋势图表"""
        charts = []
        plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
        plt.rcParams["axes.unicode_minus"] = False
        
        if self.history_data["pages"]:
            plt.figure(figsize=(12, 6))
            for project, data in self.history_data["pages"].items():
                if len(data) > 1:
                    dates = sorted(data.keys())
                    requests = [data[date] for date in dates]
                    plt.plot(dates, requests, marker='o', label=project)
            plt.title("Cloudflare Pages 项目请求量趋势")
            plt.xlabel("日期")
            plt.ylabel("请求量")
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            plt.tight_layout()
            chart_path = "pages_trend.png"
            plt.savefig(chart_path)
            plt.close()
            charts.append(chart_path)
        
        if self.history_data["workers"]:
            plt.figure(figsize=(12, 6))
            for worker, data in self.history_data["workers"].items():
                if len(data) > 1:
                    dates = sorted(data.keys())
                    requests = [data[date] for date in dates]
                    plt.plot(dates, requests, marker='o', label=worker)
            plt.title("Cloudflare Workers 服务请求量趋势")
            plt.xlabel("日期")
            plt.ylabel("请求量")
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            plt.tight_layout()
            chart_path = "workers_trend.png"
            plt.savefig(chart_path)
            plt.close()
            charts.append(chart_path)
        
        return charts
    
    def generate_report(self) -> str:
        """生成统计报告文本"""
        report = "📊 *Cloudflare 统计报告*\n\n"
        report += f"📅 统计日期: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}\n\n"
        
        if self.current_data["pages"]:
            report += "### 📄 Pages 项目请求量\n"
            for project, requests in sorted(self.current_data["pages"].items()):
                report += f"- *{project}*: {requests:,} 请求\n"
            report += "\n"
        
        if self.current_data["workers"]:
            report += "### 💻 Workers 服务请求量\n"
            for worker, requests in sorted(self.current_data["workers"].items()):
                report += f"- *{worker}*: {requests:,} 请求\n"
            report += "\n"
        
        report += "🔄 数据每24小时更新一次\n"
        report += "📈 图表展示最近7天趋势"
        return report
    
    def send_report(self) -> None:
        """发送报告和图表"""
        report = self.generate_report()
        success = self.tg_bot.send_message(report)
        if not success:
            logger.error("发送报告文本失败")
            return
        
        alerts = self.check_thresholds()
        if alerts:
            alert_message = "\n\n⚠️ *异常情况警报* ⚠️\n\n" + "\n\n".join(alerts)
            self.tg_bot.send_message(alert_message)
        
        charts = self.generate_charts()
        for chart in charts:
            if "pages" in chart:
                caption = "📄 Cloudflare Pages 项目请求量趋势图"
            else:
                caption = "💻 Cloudflare Workers 服务请求量趋势图"
            self.tg_bot.send_photo(chart, caption)

def main():
    try:
        tracker = CloudflareStatsTracker()
        tracker.fetch_stats()
        tracker.update_history()
        tracker.send_report()
        logger.info("统计数据获取和推送完成")
    except Exception as e:
        logger.exception(f"执行过程中发生错误: {str(e)}")
        try:
            tg_bot = TelegramBot(os.getenv("TG_BOT_TOKEN"), os.getenv("TG_CHAT_ID"))
            error_msg = f"❌ *执行失败*\n\n错误信息: {str(e)}\n\n请检查日志获取更多详情"
            tg_bot.send_message(error_msg)
        except Exception:
            logger.error("发送错误通知失败")

if __name__ == "__main__":
    main()
