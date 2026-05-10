import json
import aiosqlite
from typing import List, Sequence
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, messages_from_dict, message_to_dict

class AsyncSQLiteHistory(BaseChatMessageHistory):
    """
    进阶异步 SQLite 聊天记录存储实现。
    对标 Java 中的异步 DAO (Data Access Object) 模式。
    """
    def __init__(self, db_path: str, session_id: str):
        self.db_path = db_path
        self.session_id = session_id
        self._initialized = False

    async def _ensure_table(self):
        """确保表结构存在"""
        if self._initialized:
            return
        async with aiosqlite.connect(self.db_path) as db:
            # 更改表名，彻底避开之前失败尝试遗留的旧表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_message_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    message_json TEXT
                )
            """)
            await db.commit()
        self._initialized = True

    async def aget_messages(self) -> List[BaseMessage]:
        """异步获取消息历史"""
        await self._ensure_table()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT message_json FROM agent_message_history WHERE session_id = ? ORDER BY id",
                (self.session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                items = [json.loads(row[0]) for row in rows]
                return messages_from_dict(items)

    async def aadd_messages(self, messages: Sequence[BaseMessage]) -> None:
        """异步保存消息"""
        await self._ensure_table()
        async with aiosqlite.connect(self.db_path) as db:
            for m in messages:
                message_json = json.dumps(message_to_dict(m))
                await db.execute(
                    "INSERT INTO agent_message_history (session_id, message_json) VALUES (?, ?)",
                    (self.session_id, message_json)
                )
            await db.commit()

    async def aclear(self) -> None:
        """异步清空历史"""
        await self._ensure_table()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM agent_message_history WHERE session_id = ?", (self.session_id,))
            await db.commit()

    # 同步接口的空实现 (为了满足基类要求，但在异步链中不会被调用)
    @property
    def messages(self) -> List[BaseMessage]:
        return []
    
    def add_message(self, message: BaseMessage) -> None:
        pass

    def clear(self) -> None:
        pass
