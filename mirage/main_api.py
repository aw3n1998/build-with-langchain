"""
FastAPI 启动入口

运行方式：
    python mirage/main_api.py
    # 或者
    uvicorn mirage.main_api:app --host 0.0.0.0 --port 8000 --reload

访问：
    接口文档：http://localhost:8000/docs      （Swagger UI，可直接在浏览器里测试）
    健康检查：http://localhost:8000/api/health
    对话接口：POST http://localhost:8000/api/chat

面试问答：
Q: 为什么选 FastAPI 不选 Flask/Django？

A: 三个核心原因：
   1. 原生 async：我们的 Agent 是全链路 async，FastAPI 基于 Starlette
      天然支持，Flask 需要额外安装 quart 等扩展才能处理 async
   2. 自动文档：根据 Pydantic Schema 自动生成 Swagger UI（/docs）和
      OpenAPI JSON（/openapi.json），不需要手写接口文档
   3. 性能：基于 ASGI（Starlette），IO 密集型场景（等 LLM 返回、等 DB）
      并发性能远超 WSGI 的 Flask/Django

Q: uvicorn 是什么？

A: ASGI 服务器，FastAPI 的运行时。
   类比：FastAPI 是 Django，uvicorn 是 gunicorn。
   生产环境：uvicorn + gunicorn（多进程）+ Nginx（反向代理）
"""

import os
import sys

# 确保项目根目录在 Python 路径里
root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mirage.app.api.routes import router
from mirage.app.core.logger import get_logger

logger = get_logger("main_api")


# ── 生命周期管理 ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期钩子（替代已废弃的 @app.on_event）。
    yield 前：应用启动时执行（初始化资源）
    yield 后：应用关闭时执行（释放资源）
    """
    logger.info("=" * 50)
    logger.info("  AgentLab API 服务启动中...")
    logger.info("  文档地址：http://localhost:8000/docs")
    logger.info("=" * 50)

    # ai_service 在模块导入时已经初始化（包括 RAG Pipeline）
    # 这里只做日志，不需要额外操作
    from mirage.app.services.ai_service import ai_service
    logger.info("AI 服务就绪，RAG 连接状态: %s", ai_service._rag_pipeline.is_connected)

    yield  # ← 应用运行期间在这里

    logger.info("AgentLab API 服务关闭")


# ── FastAPI 应用实例 ────────────────────────────────────────────

app = FastAPI(
    title="AgentLab API",
    description=(
        "工程行业 AI Agent 服务接口\n\n"
        "- **chat**：与多 Agent 系统对话（SSE 流式推送）\n"
        "- **rag/ingest**：导入文档到知识库\n"
        "- **rag/status**：查询知识库状态\n"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS 配置 ────────────────────────────────────────────────────
# 允许前端跨域访问（生产环境应限制为具体域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 生产改为 ["https://yourdomain.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册路由 ─────────────────────────────────────────────────────
app.include_router(router, prefix="/api")

# ── 对外开放 API(/api/v1)：独立 router + APIKey 鉴权（预留口子，默认放行）──
try:
    from mirage.app.api.v1_public import router as public_router
    app.include_router(public_router)        # 自带 /api/v1 前缀
except Exception as _e:  # noqa: BLE001 - 公开 API 出问题不应拖垮内部面板
    import logging
    logging.getLogger("mirage").warning("公开 API(/api/v1) 未加载: %s", _e)

# ── serve 前端静态产物（预留口子）：让单端口能跑整套 UI（生产/toC）。──
# 必须在 include_router 之后挂，确保 /api、/api/v1 优先匹配；目录不存在则自动跳过(开发态用 vite dev)。
try:
    import os as _os
    from mirage.app.core.config import settings as _st
    _dist = _st.FRONTEND_DIST_DIR if _os.path.isabs(_st.FRONTEND_DIST_DIR) \
        else _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), _st.FRONTEND_DIST_DIR)
    if _st.SERVE_FRONTEND and _os.path.isdir(_dist) and _os.path.exists(_os.path.join(_dist, "index.html")):
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
        import logging
        logging.getLogger("mirage").info("已挂载前端静态目录: %s", _dist)
except Exception as _e:  # noqa: BLE001
    import logging
    logging.getLogger("mirage").warning("前端静态挂载跳过: %s", _e)


# ── 本地直接运行 ─────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "mirage.main_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,    # 代码改动自动热重载，开发用
        reload_dirs=["mirage"],
    )
