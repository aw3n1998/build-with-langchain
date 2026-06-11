# ── 构建阶段 ────────────────────────────────────────────────────
# 用 slim 镜像减小体积，python:3.11 是目前生产最稳定的版本
FROM python:3.11-slim AS builder

WORKDIR /app

# 先复制依赖文件，利用 Docker 层缓存
# 优先用锁定版本 requirements.lock（精确 ==，保证可复现）；缺失时回退 requirements.txt
COPY requirements*.txt requirements.lock* ./

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN pip install --no-cache-dir --upgrade pip \
    && if [ -f requirements.lock ]; then \
         pip install --no-cache-dir -r requirements.lock; \
       else \
         pip install --no-cache-dir -r requirements.txt; \
       fi

# 从构建上下文复制本地预下载的 FastEmbed 模型（100% 离线构建，避免容器联网 SSL 报错）
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

# FastEmbed 模型缓存目录与 HuggingFace 离线模式限制
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed
ENV HF_HUB_OFFLINE=1

# 非 root 用户运行（安全实践）
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 生产用 --workers 4，开发用 --reload
CMD ["uvicorn", "agent_lab.main_api:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1"]
