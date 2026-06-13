"""
RAG 工具集 —— 把 RAGPipeline 封装为 LangChain Tool。

Agent 通过这两个工具访问知识库：
  1. search_knowledge_base：查询知识库，回答用户问题
  2. ingest_document：导入新文档到知识库

工具描述（docstring）很重要：
  SkillRegistry 会把 docstring embed 成向量，
  用户提问时通过语义匹配决定调哪个工具。
  所以描述要贴近用户真实的提问方式。
"""

from langchain_core.tools import tool
from mirage.app.rag.pipeline import get_pipeline
from mirage.app.core.logger import get_logger

logger = get_logger("rag.tools")


@tool
def search_knowledge_base(query: str, project_id: str = "default") -> str:
    """
    在知识库中检索与问题相关的文档内容，用于回答用户关于工程规范、
    施工验收、质量标准、安全管理、合同管理等专业问题。

    当用户询问具体的规范要求、流程步骤、标准参数时，优先调用此工具。
    返回最相关的文档片段，包含来源文件名和相关度。

    Args:
        query:      用户的具体问题，例如"防水层蓄水试验时间要求"
        project_id: 项目 ID，用于过滤特定项目的文档（默认查全库）
    """
    pipeline = get_pipeline()
    if pipeline is None:
        return "【知识库未初始化】RAG Pipeline 尚未启动，请联系管理员。"

    logger.info("[RAGTool] search query='%s' project='%s'", query[:40], project_id)
    return pipeline.search(query, top_k=5, project_id=project_id if project_id != "default" else None)


@tool
def ingest_document(file_path: str, project_id: str = "default") -> str:
    """
    将文档文件导入知识库，使其内容可被检索。
    支持 .txt、.pdf、.docx 格式。
    导入后知识库立即生效，无需重启。

    Args:
        file_path:  文档的完整文件路径，例如 "D:/规范/施工验收规范.pdf"
        project_id: 项目 ID，用于隔离不同项目的文档（默认为 "default"）
    """
    pipeline = get_pipeline()
    if pipeline is None:
        return "【知识库未初始化】RAG Pipeline 尚未启动。"

    logger.info("[RAGTool] ingest file='%s' project='%s'", file_path, project_id)
    return pipeline.ingest(file_path, project_id=project_id)


# 导出工具列表，供 ai_service.py 注册
rag_tools = [search_knowledge_base, ingest_document]
