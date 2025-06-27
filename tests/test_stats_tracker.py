import unittest
from unittest.mock import patch, MagicMock
import json
import os
from datetime import datetime, timedelta
from src.fetch_cloudflare_stats import CloudflareStatsTracker

class TestCloudflareStatsTracker(unittest.TestCase):
    def setUp(self):
        # 创建临时配置文件
        self.config = {
            "cloudflare": {
                "account_id": "test_account_id",
                "api_token": "test_api_token"
            },
            "telegram": {
                "bot_token": "test_bot_token",
                "chat_id": "test_chat_id"
            },
            "thresholds": {
                "pages_request_increase": 30,
                "pages_request_decrease": 25,
                "workers_request_increase": 35,
                "workers_request_decrease": 30
            },
            "retry": {
                "max_attempts": 3,
                "delay": 1
            },
            "history": {
                "storage_days": 30,
                "data_file": "tests/history_test.json"
            }
        }
        
        with open("tests/config_test.json", "w") as f:
            json.dump(self.config, f)
        
        # 确保历史文件不存在
        if os.path.exists(self.config["history"]["data_file"]):
            os.remove(self.config["history"]["data_file"])
        
        self.tracker = CloudflareStatsTracker("tests/config_test.json")
    
    def tearDown(self):
        # 清理临时文件
        if os.path.exists("tests/config_test.json"):
            os.remove("tests/config_test.json")
        
        if os.path.exists(self.config["history"]["data_file"]):
            os.remove(self.config["history"]["data_file"])
    
    @patch('requests.request')
    def test_fetch_pages_stats(self, mock_request):
        # 设置模拟响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'result': [
                {'name': 'project1', 'id': 'project1_id'},
                {'name': 'project2', 'id': 'project2_id'}
            ]
        }
        
        mock_stats_response = MagicMock()
        mock_stats_response.json.return_value = {
            'result': {
                'all': {
                    'requests': 1000
                }
            }
        }
        
        mock_request.side_effect = [mock_response, mock_stats_response, mock_stats_response]
        
        # 执行测试
        stats = self.tracker.fetch_pages_stats()
        
        # 验证结果
        self.assertEqual(len(stats), 2)
        self.assertEqual(stats['project1'], 1000)
        self.assertEqual(stats['project2'], 1000)
    
    @patch('requests.request')
    def test_fetch_workers_stats(self, mock_request):
        # 设置模拟响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'result': [
                {'name': 'service1'},
                {'name': 'service2'}
            ]
        }
        
        mock_stats_response = MagicMock()
        mock_stats_response.json.return_value = {
            'result': {
                'sum': {
                    'requests': 500
                }
            }
        }
        
        mock_request.side_effect = [mock_response, mock_stats_response, mock_stats_response]
        
        # 执行测试
        stats = self.tracker.fetch_workers_stats()
        
        # 验证结果
        self.assertEqual(len(stats), 2)
        self.assertEqual(stats['service1'], 500)
        self.assertEqual(stats['service2'], 500)
    
    def test_check_thresholds_no_history(self):
        # 设置当前数据
        self.tracker.current_data = {
            'pages': {'project1': 1000, 'project2': 2000},
            'workers': {'service1': 500, 'service2': 1500}
        }
        
        # 执行测试
        alerts = self.tracker.check_thresholds()
        
        # 验证结果
        self.assertEqual(len(alerts), 0)
    
    def test_check_thresholds_with_increase(self):
        # 设置历史数据
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.tracker.history_data = {
            'pages': {
                yesterday: {'project1': 700, 'project2': 2000}
            },
            'workers': {
                yesterday: {'service1': 500, 'service2': 1000}
            }
        }
        
        # 设置当前数据
        self.tracker.current_data = {
            'pages': {'project1': 1000, 'project2': 2000},
            'workers': {'service1': 500, 'service2': 1500}
        }
        
        # 执行测试
        alerts = self.tracker.check_thresholds()
        
        # 验证结果
        self.assertEqual(len(alerts), 2)
        self.assertIn("📈 警告: Pages项目 'project1' 请求量增长异常", alerts[0])
        self.assertIn("📈 警告: Workers服务 'service2' 请求量增长异常", alerts[1])
    
    def test_check_thresholds_with_decrease(self):
        # 设置历史数据
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.tracker.history_data = {
            'pages': {
                yesterday: {'project1': 1500, 'project2': 2000}
            },
            'workers': {
                yesterday: {'service1': 800, 'service2': 1500}
            }
        }
        
        # 设置当前数据
        self.tracker.current_data = {
            'pages': {'project1': 1000, 'project2': 2000},
            'workers': {'service1': 500, 'service2': 1000}
        }
        
        # 执行测试
        alerts = self.tracker.check_thresholds()
        
        # 验证结果
        self.assertEqual(len(alerts), 2)
        self.assertIn("📉 警告: Pages项目 'project1' 请求量下降异常", alerts[0])
        self.assertIn("📉 警告: Workers服务 'service1' 请求量下降异常", alerts[1])
    
    def test_update_history(self):
        # 设置当前数据
        today = datetime.now().strftime("%Y-%m-%d")
        self.tracker.current_data = {
            'pages': {'project1': 1000, 'project2': 2000},
            'workers': {'service1': 500, 'service2': 1500}
        }
        
        # 执行测试
        self.tracker.update_history()
        
        # 验证结果
        self.assertIn('pages', self.tracker.history_data)
        self.assertIn('workers', self.tracker.history_data)
        self.assertIn(today, self.tracker.history_data['pages'])
        self.assertIn(today, self.tracker.history_data['workers'])
        self.assertEqual(self.tracker.history_data['pages'][today], self.tracker.current_data['pages'])
        self.assertEqual(self.tracker.history_data['workers'][today], self.tracker.current_data['workers'])
    
    @patch('matplotlib.pyplot.savefig')
    @patch('matplotlib.pyplot.close')
    @patch('matplotlib.pyplot.figure')
    def test_generate_charts(self, mock_figure, mock_close, mock_savefig):
        # 设置历史数据
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        self.tracker.history_data = {
            'pages': {
                yesterday: {'project1': 800, 'project2': 1800},
                today: {'project1': 1000, 'project2': 2000}
            },
            'workers': {
                yesterday: {'service1': 400, 'service2': 1400},
                today: {'service1': 500, 'service2': 1500}
            }
        }
        
        # 执行测试
        charts = self.tracker.generate_charts()
        
        # 验证结果
        self.assertEqual(len(charts), 2)
        self.assertIn('pages_trend.png', charts)
        self.assertIn('workers_trend.png', charts)
    
    @patch('requests.post')
    def test_send_telegram_message(self, mock_post):
        # 设置模拟响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        # 执行测试
        result = self.tracker.send_telegram_message("Test message")
        
        # 验证结果
        self.assertTrue(result)
        mock_post.assert_called_once()
    
    def test_generate_report(self):
        # 设置当前数据
        self.tracker.current_data = {
            'pages': {'project1': 1000, 'project2': 2000},
            'workers': {'service1': 500, 'service2': 1500}
        }
        
        # 执行测试
        report = self.tracker.generate_report()
        
        # 验证结果
        self.assertIn("📊 *Cloudflare 统计报告*", report)
        self.assertIn("### 📄 Pages 项目请求量", report)
        self.assertIn("- project1: 1,000 请求", report)
        self.assertIn("- project2: 2,000 请求", report)
        self.assertIn("### 💻 Workers 服务请求量", report)
        self.assertIn("- service1: 500 请求", report)
        self.assertIn("- service2: 1,500 请求", report)

if __name__ == '__main__':
    unittest.main()  