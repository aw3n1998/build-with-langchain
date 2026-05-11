from langchain_core.tools import tool
from datetime import datetime
import os
import subprocess
import tempfile

# 使用 @tool 装饰器定义工具
# 对标 Java 的 @Service 或 @Component，但带有自然语言描述 (docstring)

@tool
def get_current_time() -> str:
    """获取当前的系统时间。当用户询问时间或日期时使用。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def list_files(directory: str = ".") -> str:
    """
    列出指定目录下的所有文件。
    :param directory: 目录路径，默认为当前目录。
    """
    try:
        files = os.listdir(directory)
        return "\n".join(files) if files else "该目录为空。"
    except Exception as e:
        return f"读取目录失败: {str(e)}"

@tool
def read_file_content(file_path: str) -> str:
    """
    读取指定文件的文本内容。
    :param file_path: 文件的完整路径。
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read(1000) # 限制读取前1000字，防止 Token 溢出
    except Exception as e:
        return f"读取文件失败: {str(e)}"

@tool
def execute_python_code(code: str) -> str:
    """执行 Python 代码并返回输出。如果出错，返回完整的错误信息（用于自纠错 Agent）。

    Args:
        code: 要执行的 Python 代码字符串
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["python", tmp_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return f"执行成功:\n{result.stdout}"
        else:
            return f"执行失败:\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "执行超时（超过10秒）"
    finally:
        os.unlink(tmp_path)


# 导出工具列表（含代码执行，LLM 自动决策是否调用）
agent_tools = [get_current_time, list_files, read_file_content, execute_python_code]
