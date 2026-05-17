# ── 构建阶段 ────────────────────────────────────────────────────
# 用 slim 镜像减小体积，python:3.11 是目前生产最稳定的版本
FROM python:3.11-slim AS builder

WORKDIR /app

# 先复制依赖文件，利用 Docker 层缓存
# 只要 requirements.txt 没变，这一层就不会重新构建
COPY requirements.txt .

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 直接从构建上下文复制本地预下载的 FastEmbed 模型（避免构建时联网）
# 本地模型已在 fastembed_cache/ 中，通过 Python 脚本解析符号链接后复制进来
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed
COPY fastembed_cache /app/.cache/fastembed


# ── 运行阶段 ────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# 从构建阶段复制已安装的包（避免在运行镜像里装编译工具）
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制预下载的 FastEmbed 模型缓存（~50MB，避免运行时下载）
COPY --from=builder /app/.cache/fastembed /app/.cache/fastembed

# 复制项目代码
COPY agent_lab/ ./agent_lab/

# FastEmbed 模型缓存目录
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed

# 非 root 用户运行（安全实践）
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 生产用 --workers 4，开发用 --reload
CMD ["uvicorn", "agent_lab.main_api:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1"]
