import asyncio
import os
import sys
import io
import uuid

# 解决 Windows 终端中文乱码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_path not in sys.path:
    sys.path.append(root_path)

from agent_lab.app.schemas.base import AIRequest
from agent_lab.app.services.ai_service import ai_service

def get_or_create_session():
    if len(sys.argv) > 1:
        return sys.argv[1]
    else:
        sid = f"sid-{str(uuid.uuid4())[:8]}"
        print(f"[系统] 已为你生成新会话: {sid}")
        return sid

async def chat_loop():
    print("\n" + "="*50)
    print("   AI Agent 进阶开发实验室 (AgentLab) 交互模式")
    print("   输入 'exit' 或 'quit' 退出程序")
    print("="*50 + "\n")
    
    current_session_id = get_or_create_session()
    
    while True:
        try:
            user_input = input(f"\n[{current_session_id}] 用户 > ").strip()
        except EOFError:
            break
            
        if user_input.lower() in ['exit', 'quit']:
            break
            
        if not user_input:
            continue
            
        request = AIRequest(session_id=current_session_id, content=user_input)
        
        try:
            # AIService.chat 现在内部处理打印（流式输出）
            await ai_service.chat(request)
        except Exception as e:
            print(f"\n[错误] 服务异常: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(chat_loop())
    except KeyboardInterrupt:
        print("\n[系统] 退出。")
