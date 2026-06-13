"""
文档加载器：将原始文件转成 LangChain Document 对象。

每个 Document 包含两部分：
  - page_content: 文本内容
  - metadata:     来源信息（file_name, file_type, page, ...）

metadata 会随着 chunk 传递到向量库，检索时可以知道答案来自哪个文档哪一页。
"""

import os
from pathlib import Path
from langchain_core.documents import Document
from mirage.app.core.logger import get_logger

logger = get_logger("rag.loader")


def load_txt(file_path: str) -> list[Document]:
    """加载纯文本文件。"""
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")
    logger.info("[Loader] TXT %s → %d 字符", path.name, len(text))
    return [Document(
        page_content=text,
        metadata={"source": path.name, "file_type": "txt"}
    )]


def load_pdf(file_path: str) -> list[Document]:
    """
    加载 PDF 文件，每页生成一个 Document。
    需要安装：pip install pypdf
    """
    try:
        from langchain_community.document_loaders import PyPDFLoader
    except ImportError:
        raise ImportError("请先安装 PDF 支持：pip install pypdf langchain-community")

    loader = PyPDFLoader(file_path)
    docs = loader.load()
    logger.info("[Loader] PDF %s → %d 页", Path(file_path).name, len(docs))
    return docs


def load_docx(file_path: str) -> list[Document]:
    """
    加载 Word 文件（.docx）。
    需要安装：pip install python-docx langchain-community
    """
    try:
        from langchain_community.document_loaders import Docx2txtLoader
    except ImportError:
        raise ImportError("请先安装：pip install python-docx docx2txt langchain-community")

    loader = Docx2txtLoader(file_path)
    docs = loader.load()
    logger.info("[Loader] DOCX %s → %d 段", Path(file_path).name, len(docs))
    return docs


def load_file(file_path: str) -> list[Document]:
    """
    自动识别文件类型并加载。
    支持：.txt  .pdf  .docx
    """
    ext = Path(file_path).suffix.lower()
    loaders = {
        ".txt":  load_txt,
        ".pdf":  load_pdf,
        ".docx": load_docx,
    }
    if ext not in loaders:
        raise ValueError(f"不支持的文件类型：{ext}，目前支持 {list(loaders.keys())}")
    return loaders[ext](file_path)


def load_directory(dir_path: str, extensions: list[str] = None) -> list[Document]:
    """
    批量加载目录下的所有文档。

    Args:
        dir_path:   目录路径
        extensions: 过滤后缀，例如 ['.txt', '.pdf']，None 表示加载全部支持类型
    """
    if extensions is None:
        extensions = [".txt", ".pdf", ".docx"]

    all_docs = []
    dir_p = Path(dir_path)
    for file in dir_p.iterdir():
        if file.suffix.lower() in extensions:
            try:
                docs = load_file(str(file))
                all_docs.extend(docs)
            except Exception as e:
                logger.warning("[Loader] 跳过 %s：%s", file.name, e)

    logger.info("[Loader] 目录 %s → 共加载 %d 个 Document", dir_path, len(all_docs))
    return all_docs
