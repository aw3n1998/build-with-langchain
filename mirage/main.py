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

from mirage.app.services.ai_service import ai_service


def get_or_create_session():
    if len(sys.argv) > 1:
        return sys.argv[1]
    sid = f"sid-{str(uuid.uuid4())[:8]}"
    print(f"[系统] 已为你生成新会话: {sid}")
    return sid


async def chat_loop():
    print("\n" + "="*50)
    print("   AI Agent 进阶开发实验室 (蜃景 Mirage)")
    print("   输入 'exit' 或 'quit' 退出")
    print("="*50 + "\n")

    session_id = get_or_create_session()

    while True:
        try:
            user_input = input(f"\n[{session_id}] 用户 > ").strip()
        except EOFError:
            break

        if user_input.lower() in ['exit', 'quit']:
            break

        if not user_input:
            continue

        try:
            await ai_service.chat(session_id, user_input)
        except Exception as e:
            print(f"\n[错误] 服务异常: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(chat_loop())
    except KeyboardInterrupt:
        print("\n[系统] 退出。")
