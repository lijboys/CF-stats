import os
import requests
import json
import logging
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import time

# 配置日志，设置编码为utf - 8保证中文输出正常
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)


class CloudflareAPI:
    """与 Cloudflare API 交互的类，用于获取 Pages 和 Workers 相关数据"""

    def __init__(self, account_id: str, api_token: str):
        self.account_id = account_id
        self.api_token = api_token
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

    def fetch_pages_projects(self) -> List[Dict[str, Any]]:
        """获取 Cloudflare Pages 项目列表"""
        try:
            url = f"{self.base_url}/pages/projects"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()["result"]
        except Exception as e:
            logger.error(f"获取 Pages 项目失败: {str(e)}")
            return []

    def fetch_workers(self) -> List[Dict[str, Any]]:
        """获取 Cloudflare Workers 列表"""
        try:
            url = f"{self.base_url}/workers/scripts"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()["result"]
        except Exception as e:
            logger.error(f"获取 Workers 失败: {str(e)}")
            return []

    def fetch_pages_metrics(self, project_name: str, start: str, end: str) -> Dict[str, Any]:
        """获取 Pages 项目的指标数据，如请求量等"""
        try:
            url = f"{self.base_url}/pages/projects/{project_name}/metrics"
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
        """获取 Workers 的指标数据，如请求量等"""
        try:
            url = f"{self.base_url}/workers/analytics/dashboard"
            params = {
                "script_name": script_name,
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
    """与 Telegram Bot API 交互的类，用于发送文本消息和图片"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def send_message(self, message: str) -> bool:
        """发送文本消息到 Telegram"""
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
        """发送图片到 Telegram，可带标题"""
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
    """
    Cloudflare 统计数据跟踪器核心类，
    负责整合数据获取、历史存储、阈值检查、图表生成和消息推送等功能
    """

    def __init__(self, config_path: str = "config.json"):
        # 加载配置文件，若失败则抛出异常
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            logger.error(f"配置文件 {config_path} 未找到，请检查路径是否正确")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 {config_path} 格式错误，解析失败: {str(e)}")
            raise

        # 初始化 Cloudflare API 客户端
        self.cf_api = CloudflareAPI(
            self.config["cloudflare"]["account_id"],
            self.config["cloudflare"]["api_token"]
        )

        # 初始化 Telegram Bot 客户端
        self.tg_bot = TelegramBot(
            self.config["telegram"]["bot_token"],
            self.config["telegram"]["chat_id"]
        )

        # 初始化数据存储相关属性
        self.current_data = {"pages": {}, "workers": {}}
        self.history_data = self._load_history()
        self.thresholds = self.config.get("thresholds", {})
        self.retry_config = self.config.get("retry", {
            "max_attempts": 3,
            "delay": 1
        })

    def _load_history(self) -> Dict[str, Any]:
        """加载历史数据，若文件不存在则返回默认空结构"""
        history_file = self.config["history"]["data_file"]
        try:
            if os.path.exists(history_file):
                with open(history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {"pages": {}, "workers": {}}
        except Exception as e:
            logger.error(f"加载历史数据失败: {str(e)}")
            return {"pages": {}, "workers": {}}

    def _save_history(self) -> None:
        """保存历史数据到文件，覆盖原内容"""
        history_file = self.config["history"]["data_file"]
        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存历史数据失败: {str(e)}")

    def _retry(self, func, *args, **kwargs):
        """
        重试机制装饰器，对传入的函数进行重试
        :param func: 要执行的函数
        :param args: 函数位置参数
        :param kwargs: 函数关键字参数
        :return: 函数执行结果，若达到最大重试次数则抛出异常
        """
        max_attempts = self.retry_config.get("max_attempts", 3)
        delay = self.retry_config.get("delay", 1)

        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise
                logger.warning(f"尝试 {attempt + 1}/{max_attempts} 失败: {str(e)}，{delay}秒后重试")
                time.sleep(delay)

    def fetch_stats(self) -> None:
        """获取当前 Cloudflare Pages 和 Workers 的统计数据（请求量等）"""
        # 生成过去24小时的时间范围，转换为 RFC3339 格式
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=24)
        start_str = start_time.isoformat(timespec='seconds') + 'Z'
        end_str = end_time.isoformat(timespec='seconds') + 'Z'

        # 获取 Pages 项目数据并填充 current_data
        pages_projects = self._retry(self.cf_api.fetch_pages_projects)
        for project in pages_projects:
            project_name = project["name"]
            metrics = self._retry(self.cf_api.fetch_pages_metrics, project_name, start_str, end_str)
            if metrics and "requests" in metrics:
                self.current_data["pages"][project_name] = metrics["requests"]

        # 获取 Workers 数据并填充 current_data
        workers = self._retry(self.cf_api.fetch_workers)
        for worker in workers:
            worker_name = worker["name"]
            metrics = self._retry(self.cf_api.fetch_workers_metrics, worker_name, start_str, end_str)
            if metrics and "requests" in metrics.get("script", {}):
                self.current_data["workers"][worker_name] = metrics["script"]["requests"]

        logger.info(f"成功获取统计数据: Pages项目={len(self.current_data['pages'])}, Workers={len(self.current_data['workers'])}")

    def update_history(self) -> None:
        """更新历史数据，包含数据清理和保存操作"""
        today = datetime.now().strftime("%Y-%m-%d")

        # 更新 Pages 历史数据
        for project, requests in self.current_data["pages"].items():
            if project not in self.history_data["pages"]:
                self.history_data["pages"][project] = {}
            self.history_data["pages"][project][today] = requests

        # 更新 Workers 历史数据
        for worker, requests in self.current_data["workers"].items():
            if worker not in self.history_data["workers"]:
                self.history_data["workers"][worker] = {}
            self.history_data["workers"][worker][today] = requests

        # 清理旧数据，保留配置指定天数内的数据
        storage_days = self.config["history"].get("storage_days", 30)
        cutoff_date = (datetime.now() - timedelta(days=storage_days)).strftime("%Y-%m-%d")

        # 清理 Pages 历史数据
        for project in list(self.history_data["pages"].keys()):
            self.history_data["pages"][project] = {date: req for date, req in self.history_data["pages"][project].items() if date >= cutoff_date}
            if not self.history_data["pages"][project]:
                del self.history_data["pages"][project]

        # 清理 Workers 历史数据
        for worker in list(self.history_data["workers"].keys()):
            self.history_data["workers"][worker] = {date: req for date, req in self.history_data["workers"][worker].items() if date >= cutoff_date}
            if not self.history_data["workers"][worker]:
                del self.history_data["workers"][worker]

        # 保存更新后的历史数据
        self._save_history()

    def check_thresholds(self) -> List[str]:
        """检查请求量波动是否超过阈值，生成警报信息列表"""
        alerts = []
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        # 检查 Pages 项目
        for project, requests in self.current_data["pages"].items():
            if project in self.history_data["pages"] and yesterday in self.history_data["pages"][project]:
                yesterday_requests = self.history_data["pages"][project][yesterday]

                if yesterday_requests > 0:
                    change_percent = ((requests - yesterday_requests) / yesterday_requests) * 100

                    # 检查增长阈值
                    increase_threshold = self.thresholds.get("pages_request_increase", 30)
                    if change_percent >= increase_threshold:
                        alerts.append(f"📈 警告: Pages项目 '{project}' 请求量增长异常 ({change_percent:.1f}%)\n"
                                     f"昨日: {yesterday_requests:,} → 今日: {requests:,}")

                    # 检查下降阈值
                    decrease_threshold = self.thresholds.get("pages_request_decrease", 25)
                    if change_percent <= -decrease_threshold:
                        alerts.append(f"📉 警告: Pages项目 '{project}' 请求量下降异常 ({abs(change_percent):.1f}%)\n"
                                     f"昨日: {yesterday_requests:,} → 今日: {requests:,}")

        # 检查 Workers 服务
        for worker, requests in self.current_data["workers"].items():
            if worker in self.history_data["workers"] and yesterday in self.history_data["workers"][worker]:
                yesterday_requests = self.history_data["workers"][worker][yesterday]

                if yesterday_requests > 0:
                    change_percent = ((requests - yesterday_requests) / yesterday_requests) * 100

                    # 检查增长阈值
                    increase_threshold = self.thresholds.get("workers_request_increase", 35)
                    if change_percent >= increase_threshold:
                        alerts.append(f"📈 警告: Workers服务 '{worker}' 请求量增长异常 ({change_percent:.1f}%)\n"
                                     f"昨日: {yesterday_requests:,} → 今日: {requests:,}")

                    # 检查下降阈值
                    decrease_threshold = self.thresholds.get("workers_request_decrease", 30)
                    if change_percent <= -decrease_threshold:
                        alerts.append(f"📉 警告: Workers服务 '{worker}' 请求量下降异常 ({abs(change_percent):.1f}%)\n"
                                     f"昨日: {yesterday_requests:,} → 今日: {requests:,}")

        return alerts

    def generate_charts(self) -> List[str]:
        """生成 Pages 和 Workers 请求量趋势图表，返回图表文件路径列表"""
        charts = []
        # 设置中文字体支持，避免图表中文显示异常
        plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
        plt.rcParams["axes.unicode_minus"] = False  # 解决负号显示为方块的问题

        # 生成 Pages 趋势图
        if self.history_data["pages"]:
            plt.figure(figsize=(12, 6))

            for project, data in self.history_data["pages"].items():
                if len(data) > 1:  # 至少有两个数据点才绘制趋势
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

        # 生成 Workers 趋势图
        if self.history_data["workers"]:
            plt.figure(figsize=(12, 6))

            for worker, data in self.history_data["workers"].items():
                if len(data) > 1:  # 至少有两个数据点才绘制趋势
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
        """生成统计报告文本，包含 Pages 和 Workers 请求量等信息"""
        report = "📊 *Cloudflare 统计报告*\n\n"
        # 添加统计日期
        report += f"📅 统计日期: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}\n\n"

        # 添加 Pages 项目数据
        if self.current_data["pages"]:
            report += "### 📄 Pages 项目请求量\n"
            for project, requests in sorted(self.current_data["pages"].items()):
                report += f"- *{project}*: {requests:,} 请求\n"
            report += "\n"

        # 添加 Workers 数据
        if self.current_data["workers"]:
            report += "### 💻 Workers 服务请求量\n"
            for worker, requests in sorted(self.current_data["workers"].items()):
