import os
import sys
import logging
import traceback
import urllib.request
import urllib.error
from datetime import datetime

from ai_todo_assistant.infrastructure.llm.clients import build_llm_client
from ai_todo_assistant.infrastructure.config import load_settings

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

# 配置日志记录
LOG_DIR = os.path.join(PROJECT_ROOT, "log")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def _get_log_level():
    """获取初始日志级别，默认 ERROR"""
    try:
        config = load_settings(PROJECT_ROOT)
        level_name = str(config.get("log_level", "ERROR")).upper()
        return getattr(logging, level_name, logging.ERROR)
    except Exception:
        return logging.ERROR

LOG_FILE = os.path.join(LOG_DIR, "ai_agent.log")
logging.basicConfig(
    level=_get_log_level(),
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AITodoAgent")


class AITodoAgent:
    """基于LLM的待办事项管家"""
    
    def __init__(self, manager):
        self.manager = manager
        # 统一配置优先级：默认值 < 本地运行配置 < 环境变量。
        config = load_settings(PROJECT_ROOT)
        self.config = config
        self.api_key = config["api_key"]
        self.api_base = config["api_base"]
        self.model = config["model"]
        self.auth_mode = config["auth_mode"]
        self.codex_command = config["codex_command"]
        self.codex_timeout = config["codex_timeout"]
        self.request_timeout = int(
            config.get("request_timeout")
            or config.get("codex_request_timeout")
            or config.get("codex_timeout", 30)
        )
        self.llm_client = build_llm_client(self._client_config())

    def _client_config(self):
        """构造 LLM 客户端配置"""
        return {
            **self.config,
            "auth_mode": self.auth_mode,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "model": self.model,
            "codex_command": self.codex_command,
            "codex_timeout": self.codex_timeout,
        }
        
    def is_configured(self):
        """检查AI是否已正确配置"""
        return self.llm_client.is_configured()
        
    def get_current_todos_str(self):
        """获取当前待办事项的简化格式给AI上下文"""
        todos = self.manager.get_all()
        if not todos:
            return "当前系统无待办事项。"
        
        res = []
        for t in todos:
            status = "已完成" if t.completed else "未完成"
            due_info = f"，截止时间: {t.end_time}" if t.end_time else ""
            res.append(f"ID:{t.id} - 标题:{t.title} [状态:{status}]{due_info}")
            
        return "\n".join(res)

    def process_command(self, text: str) -> str:
        """解析并处理自然语言命令"""
        if not self.is_configured():
            if self.auth_mode == "codex_cli":
                return "❌ AI 管家未配置。请先安装 Codex CLI，并运行 `codex login` 完成登录。"
            return "❌ AI 管家未配置。您可以通过以下任一方式配置：\n\n" \
                   "1. 修改配置文件 [推荐]: \n" \
                   "   在项目主目录下复制 `config/settings.example.json` 为 `config/settings.local.json`，并填入您的 API Key。\n\n" \
                   "2. 设置系统环境变量: \n" \
                   "   $env:AI_API_KEY='您的API_KEY' (PowerShell)"
                   
        system_prompt = f"""你是一个智能、得力的待办管理管家。当前系统时间是 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}。
你可以帮用户添加、删除、完成工作，或者进行待办事务进度汇报和总结。

系统目前的待办事项列表如下:
{self.get_current_todos_str()}

用户的输入是自然语言，你需要解析用户的意图，并仅仅输出一个合法的 JSON 文本！严禁输出任何 markdown 格式如 ```json 等内容。
你的 JSON 必须严格符合以下格式，且可以直接通过 json.loads 解析:
{{
    "action": "add|delete|complete|list|chat",
    "params": {{
        // 若 action=add: 需要 "title"(字符串), "description"(字符串,可选), "start_time"(字符串,可选,格式:YYYY-MM-DD HH:MM), "end_time"(字符串,可选,格式:YYYY-MM-DD HH:MM)
        // 若 action=delete 或 action=complete: 需要 "id"(字符串,待操作的待办ID)
        // 若 action=list 或 action=chat: 参数留空对象即可 {{}}
    }},
    "response": "在此处使用温暖体贴的管家口吻填写你要回答给用户的话，包括执行结果的反馈、总结报告或日常回复。"
}}"""
        
        # 自动补全 OpenAI 兼容协议的 Endpoint 后缀
        endpoint = self.api_base
        if not endpoint.endswith("/chat/completions"):
            endpoint = endpoint.rstrip("/") + "/chat/completions"

        logger.info(f"发送 AI 请求到: {endpoint} (模型: {self.model})")
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "temperature": 0.2
        }
        
        try:
            resp_data = self.llm_client.request(data, timeout=self.request_timeout)
            logger.debug(f"AI 原始响应: {resp_data}")
            ai_text = resp_data['choices'][0]['message']['content'].strip()
            # 兼容即使AI强行带了Markdown包裹块
            if ai_text.startswith('```json'): ai_text = ai_text[7:]
            if ai_text.startswith('```'): ai_text = ai_text[3:]
            if ai_text.endswith('```'): ai_text = ai_text[:-3]

            result = json.loads(ai_text.strip())
            return self.execute_action(result)
                
        except json.JSONDecodeError:
            error_msg = "❌ 对不起，我的语言模型返回了无法识别的内容，请换种说法再试一次。"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            return error_msg
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e else ""
            error_msg = f"❌ AI 服务返回错误 (HTTP {e.code}): {e.reason}\n详情: {error_body}"
            logger.error(f"HTTP 错误内容: {error_body}")
            logger.error(f"完整请求信息 - URL: {self.api_base}, Model: {self.model}")
            return error_msg
        except urllib.error.URLError as e:
            error_msg = f"❌ 无法连接到 AI 服务: {e.reason}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            return error_msg
        except Exception as e:
            error_msg = f"❌ 处理指令期间发生未知异常: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            return error_msg

    def execute_action(self, ai_result: dict) -> str:
        """执行被解析出的系统动作，并返回AI提供的文本响应"""
        action = ai_result.get("action", "chat")
        params = ai_result.get("params", {})
        response_text = ai_result.get("response", "")
        
        try:
            if action == "add":
                self.manager.add(
                    title=params.get("title", "未命名事务"),
                    description=params.get("description", ""),
                    start_time=params.get("start_time"),
                    end_time=params.get("end_time")
                )
            elif action == "delete":
                todo_id = params.get("id")
                if todo_id:
                    self.manager.delete(todo_id)
            elif action == "complete":
                todo_id = params.get("id")
                if todo_id:
                    self.manager.toggle_completed(todo_id)
            elif action == "list" or action == "chat":
                # 无需直接操作实体类，仅仅利用 response 的回复即可
                pass
                
            return response_text
            
        except Exception as e:
            return f"我已经尝试去执行，但在跟数据库打交道时出了一点差错: {e}\n(附AI初始回复: {response_text})"

