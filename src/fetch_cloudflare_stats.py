import os
import json
import requests
import time
import logging
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
from requests.exceptions import RequestException

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CloudflareStatsTracker:
    def __init__(self, config_path='config/config.json'):
        self.config = self._load_config(config_path)
        self.history_data = self._load_history()
        self.current_data = {}
        self.retry_attempts = self.config['retry']['max_attempts']
        self.retry_delay = self.config['retry']['delay']

    def _load_config(self, config_path):
        """加载配置文件"""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return {}

    def _load_history(self):
        """加载历史数据"""
        history_file = self.config['history']['data_file']
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载历史数据失败: {e}")
        return {}

    def _save_history(self):
        """保存历史数据"""
        history_file = self.config['history']['data_file']
        history_dir = os.path.dirname(history_file)
        
        # 创建历史数据目录（如果不存在）
        if not os.path.exists(history_dir):
            os.makedirs(history_dir)
            
        try:
            with open(history_file, 'w') as f:
                json.dump(self.history_data, f, indent=2)
            logger.info("历史数据已保存")
        except Exception as e:
            logger.error(f"保存历史数据失败: {e}")

    def _make_api_request(self, url, headers=None, params=None, method='GET'):
        """发送API请求并处理重试"""
        for attempt in range(self.retry_attempts):
            try:
                response = requests.request(method, url, headers=headers, params=params)
                response.raise_for_status()
                return response.json()
            except RequestException as e:
                logger.warning(f"API请求失败 (尝试 {attempt+1}/{self.retry_attempts}): {e}")
                if attempt < self.retry_attempts - 1:
                    time.sleep(self.retry_delay * (attempt + 1))  # 指数退避
        logger.error("API请求达到最大重试次数")
        return None

    def fetch_pages_stats(self):
        """获取Cloudflare Pages项目统计数据"""
        account_id = self.config['cloudflare']['account_id']
        api_token = self.config['cloudflare']['api_token']
        
        headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
        
        # 获取所有Pages项目
        pages_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects"
        pages_data = self._make_api_request(pages_url, headers=headers)
        
        if not pages_data or 'result' not in pages_data:
            logger.error("获取Pages项目列表失败")
            return {}
            
        projects = pages_data['result']
        pages_stats = {}
        
        # 获取每个项目的请求量
        for project in projects:
            project_name = project['name']
            project_id = project['id']
            
            # 构建时间范围（过去24小时）
            end_time = datetime.now().isoformat() + 'Z'
            start_time = (datetime.now() - timedelta(days=1)).isoformat() + 'Z'
            
            stats_url = (f"https://api.cloudflare.com/client/v4/accounts/{account_id}/analytics/pages/"
                        f"projects/{project_id}/requests?since={start_time}&until={end_time}")
            
            stats_data = self._make_api_request(stats_url, headers=headers)
            
            if stats_data and 'result' in stats_data and 'all' in stats_data['result']:
                requests_count = stats_data['result']['all']['requests']
                pages_stats[project_name] = requests_count
                logger.info(f"获取Pages项目 {project_name} 请求量: {requests_count}")
            else:
                pages_stats[project_name] = 0
                logger.warning(f"获取Pages项目 {project_name} 请求量失败")
        
        self.current_data['pages'] = pages_stats
        return pages_stats

    def fetch_workers_stats(self):
        """获取Cloudflare Workers统计数据"""
        account_id = self.config['cloudflare']['account_id']
        api_token = self.config['cloudflare']['api_token']
        
        headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
        
        # 获取所有Workers服务
        workers_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/services"
        workers_data = self._make_api_request(workers_url, headers=headers)
        
        if not workers_data or 'result' not in workers_data:
            logger.error("获取Workers服务列表失败")
            return {}
            
        services = workers_data['result']
        workers_stats = {}
        
        # 获取每个服务的请求量
        for service in services:
            service_name = service['name']
            
            # 构建时间范围（过去24小时）
            end_time = int(time.time())
            start_time = end_time - 86400  # 24小时前
            
            stats_url = (f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/analytics/"
                        f"requests?service={service_name}&from={start_time}&to={end_time}")
            
            stats_data = self._make_api_request(stats_url, headers=headers)
            
            if stats_data and 'result' in stats_data and 'sum' in stats_data['result']:
                requests_count = stats_data['result']['sum']['requests']
                workers_stats[service_name] = requests_count
                logger.info(f"获取Workers服务 {service_name} 请求量: {requests_count}")
            else:
                workers_stats[service_name] = 0
                logger.warning(f"获取Workers服务 {service_name} 请求量失败")
        
        self.current_data['workers'] = workers_stats
        return workers_stats

    def check_thresholds(self):
        """检查请求量波动是否超过阈值"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alerts = []
        
        # 获取昨天的日期
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # 检查Pages项目
        if 'pages' in self.current_data and yesterday in self.history_data.get('pages', {}):
            for project, current_count in self.current_data['pages'].items():
                if project in self.history_data['pages'][yesterday]:
                    yesterday_count = self.history_data['pages'][yesterday][project]
                    
                    if yesterday_count > 0:  # 避免除零错误
                        increase_percent = ((current_count - yesterday_count) / yesterday_count) * 100
                        
                        # 检查增长阈值
                        if increase_percent >= self.config['thresholds']['pages_request_increase']:
                            alerts.append(
                                f"📈 警告: Pages项目 '{project}' 请求量增长异常! "
                                f"昨日: {yesterday_count}, 今日: {current_count}, 增长: {increase_percent:.1f}%"
                            )
                        
                        # 检查下降阈值
                        if increase_percent <= -self.config['thresholds']['pages_request_decrease']:
                            alerts.append(
                                f"📉 警告: Pages项目 '{project}' 请求量下降异常! "
                                f"昨日: {yesterday_count}, 今日: {current_count}, 下降: {-increase_percent:.1f}%"
                            )
        
        # 检查Workers服务
        if 'workers' in self.current_data and yesterday in self.history_data.get('workers', {}):
            for service, current_count in self.current_data['workers'].items():
                if service in self.history_data['workers'][yesterday]:
                    yesterday_count = self.history_data['workers'][yesterday][service]
                    
                    if yesterday_count > 0:  # 避免除零错误
                        increase_percent = ((current_count - yesterday_count) / yesterday_count) * 100
                        
                        # 检查增长阈值
                        if increase_percent >= self.config['thresholds']['workers_request_increase']:
                            alerts.append(
                                f"📈 警告: Workers服务 '{service}' 请求量增长异常! "
                                f"昨日: {yesterday_count}, 今日: {current_count}, 增长: {increase_percent:.1f}%"
                            )
                        
                        # 检查下降阈值
                        if increase_percent <= -self.config['thresholds']['workers_request_decrease']:
                            alerts.append(
                                f"📉 警告: Workers服务 '{service}' 请求量下降异常! "
                                f"昨日: {yesterday_count}, 今日: {current_count}, 下降: {-increase_percent:.1f}%"
                            )
        
        return alerts

    def update_history(self):
        """更新历史数据"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # 更新Pages历史数据
        if 'pages' in self.current_data:
            if 'pages' not in self.history_data:
                self.history_data['pages'] = {}
            self.history_data['pages'][current_date] = self.current_data['pages']
        
        # 更新Workers历史数据
        if 'workers' in self.current_data:
            if 'workers' not in self.history_data:
                self.history_data['workers'] = {}
            self.history_data['workers'][current_date] = self.current_data['workers']
        
        # 清理旧数据
        self._cleanup_old_data()
        
        # 保存历史数据
        self._save_history()

    def _cleanup_old_data(self):
        """清理过期的历史数据"""
        storage_days = self.config['history']['storage_days']
        cutoff_date = (datetime.now() - timedelta(days=storage_days)).strftime("%Y-%m-%d")
        
        # 清理Pages历史数据
        if 'pages' in self.history_data:
            pages_data = self.history_data['pages']
            self.history_data['pages'] = {date: data for date, data in pages_data.items() if date >= cutoff_date}
        
        # 清理Workers历史数据
        if 'workers' in self.history_data:
            workers_data = self.history_data['workers']
            self.history_data['workers'] = {date: data for date, data in workers_data.items() if date >= cutoff_date}

    def generate_charts(self):
        """生成趋势图表"""
        charts = []
        
        # 生成Pages趋势图
        if 'pages' in self.history_data and len(self.history_data['pages']) > 1:
            chart_path = 'pages_trend.png'
            self._generate_trend_chart(self.history_data['pages'], chart_path, "Cloudflare Pages 请求量趋势")
            charts.append(chart_path)
        
        # 生成Workers趋势图
        if 'workers' in self.history_data and len(self.history_data['workers']) > 1:
            chart_path = 'workers_trend.png'
            self._generate_trend_chart(self.history_data['workers'], chart_path, "Cloudflare Workers 请求量趋势")
            charts.append(chart_path)
        
        return charts

    def _generate_trend_chart(self, data, output_path, title):
        """生成趋势图表"""
        try:
            # 确保中文显示正常
            plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
            
            # 按日期排序
            sorted_dates = sorted(data.keys())
            
            # 获取所有项目/服务名称
            all_items = set()
            for date_data in data.values():
                all_items.update(date_data.keys())
            all_items = sorted(all_items)
            
            # 准备绘图数据
            dates = []
            item_data = {item: [] for item in all_items}
            
            for date in sorted_dates:
                dates.append(date)
                for item in all_items:
                    item_data[item].append(data[date].get(item, 0))
            
            # 创建图表
            plt.figure(figsize=(12, 6))
            
            for item, values in item_data.items():
                plt.plot(dates, values, marker='o', label=item)
            
            plt.title(title)
            plt.xlabel('日期')
            plt.ylabel('请求量')
            plt.grid(True)
            plt.xticks(rotation=45)
            plt.legend()
            plt.tight_layout()
            
            # 保存图表
            plt.savefig(output_path)
            plt.close()
            
            logger.info(f"趋势图已保存到 {output_path}")
        except Exception as e:
            logger.error(f"生成趋势图失败: {e}")

    def send_telegram_message(self, message, charts=None):
        """发送消息到Telegram"""
        bot_token = self.config['telegram']['bot_token']
        chat_id = self.config['telegram']['chat_id']
        
        # 发送文本消息
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        try:
            response = requests.post(url, data=payload)
            response.raise_for_status()
            logger.info("Telegram消息发送成功")
        except Exception as e:
            logger.error(f"Telegram消息发送失败: {e}")
            return False
        
        # 发送图表
        if charts:
            for chart_path in charts:
                if os.path.exists(chart_path):
                    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                    files = {'photo': open(chart_path, 'rb')}
                    payload = {'chat_id': chat_id}
                    
                    try:
                        response = requests.post(url, data=payload, files=files)
                        response.raise_for_status()
                        logger.info(f"图表 {chart_path} 发送成功")
                    except Exception as e:
                        logger.error(f"图表 {chart_path} 发送失败: {e}")
        
        return True

    def generate_report(self):
        """生成统计报告"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        report = f"📊 *Cloudflare 统计报告* - {current_time}\n\n"
        
        # 添加Pages统计
        if 'pages' in self.current_data and self.current_data['pages']:
            report += "### 📄 Pages 项目请求量\n"
            for project, count in sorted(self.current_data['pages'].items()):
                report += f"- {project}: {count:,} 请求\n"
            report += "\n"
        
        # 添加Workers统计
        if 'workers' in self.current_data and self.current_data['workers']:
            report += "### 💻 Workers 服务请求量\n"
            for service, count in sorted(self.current_data['workers'].items()):
                report += f"- {service}: {count:,} 请求\n"
            report += "\n"
        
        return report

    def run(self):
        """运行统计跟踪器"""
        try:
            logger.info("开始获取Cloudflare统计数据...")
            
            # 获取统计数据
            pages_stats = self.fetch_pages_stats()
            workers_stats = self.fetch_workers_stats()
            
            if not pages_stats and not workers_stats:
                logger.error("未获取到任何统计数据，任务终止")
                return
            
            # 检查阈值
            alerts = self.check_thresholds()
            
            # 更新历史数据
            self.update_history()
            
            # 生成图表
            charts = self.generate_charts()
            
            # 生成报告
            report = self.generate_report()
            
            # 添加警报信息（如果有）
            if alerts:
                report += "\n⚠️ *警报信息*\n"
                report += "\n".join(alerts)
            
            # 发送到Telegram
            self.send_telegram_message(report, charts)
            
            logger.info("统计数据获取和推送完成")
        except Exception as e:
            logger.exception(f"执行过程中发生错误: {e}")
            # 发送错误通知
            error_msg = f"❗ *Cloudflare统计跟踪器错误*\n\n执行过程中发生错误:\n`{str(e)}`"
            self.send_telegram_message(error_msg)

if __name__ == "__main__":
    tracker = CloudflareStatsTracker()
    tracker.run()  