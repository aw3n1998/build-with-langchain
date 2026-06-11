"""
远程 GPU 客户端 —— 通过 SSH/SFTP 在 RTX 4090 服务器上跑 FLUX 出图 + Wan2.2 图生视频。

为什么走 SSH 而不在本机推理？
  推理模型（FLUX.1-dev / Wan2.2-TI2V-5B）需要 24G 显存，跑在远程 AutoDL 服务器上。
  本框架只做编排（状态机 + Agent），把重活通过 SSH 下发到 GPU 机，产物再 SFTP 拉回本机。

凭据来源：全部从 Settings（.env）读取，绝不硬编码。私钥路径优先于密码。

已验证可跑通的 Wan2.2 配置（单卡 24G，省显存）：
  --task ti2v-5B --size 704*1280 --frame_num 25 --sample_steps 25
  --offload_model True --convert_model_dtype --t5_cpu
  + 环境变量 CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
  + 服务器端 wan/modules/model.py 已打补丁，把 flash_attention 别名为 SDPA 回退实现。
"""

from __future__ import annotations

import os
import posixpath
import shlex
import time
from dataclasses import dataclass
from typing import Optional

from agent_lab.app.core.config import settings
from agent_lab.app.core.logger import get_logger

logger = get_logger("pipeline.gpu_client")

# 下发命令前统一注入的环境变量：
#  - OpenSSL legacy 开关（paramiko/cryptography 兼容）
#  - CUDA 碎片化分配（缓解 24G 压线 OOM）
#  - 把 cu13 的 nvjitlink 库目录加入 LD_LIBRARY_PATH，否则 bitsandbytes 导入时
#    报 `libnvJitLink.so.13: cannot open shared object file`，连带 Wan2.2 起不来。
_NVJITLINK_DIR = (
    "/root/autodl-tmp/miniconda3/lib/python3.12/site-packages/nvidia/cu13/lib"
)
_ENV_PREFIX = (
    "export CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1 && "
    "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True && "
    f"export LD_LIBRARY_PATH={_NVJITLINK_DIR}:$LD_LIBRARY_PATH && "
)


class GpuConfigError(RuntimeError):
    """GPU 服务器未配置（缺 host / 凭据）。"""


class GpuRunError(RuntimeError):
    """远程命令非零退出。"""


@dataclass
class RemoteResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class GpuClient:
    """对 GPU 服务器的一层薄封装：执行命令 + 上传/下载文件 + 跑 FLUX / Wan2.2。"""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        key_path: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.host = host or settings.GPU_SSH_HOST
        self.port = port or settings.GPU_SSH_PORT
        self.user = user or settings.GPU_SSH_USER
        self.key_path = key_path or settings.GPU_SSH_KEY_PATH
        self.password = password or settings.GPU_SSH_PASSWORD
        if not self.host:
            raise GpuConfigError(
                "未配置 GPU 服务器。请在 .env 设置 GPU_SSH_HOST 及 GPU_SSH_KEY_PATH 或 GPU_SSH_PASSWORD。"
            )
        if not self.key_path and not self.password:
            raise GpuConfigError("缺少 SSH 凭据：需 GPU_SSH_KEY_PATH 或 GPU_SSH_PASSWORD 之一。")
        self._client = None  # 延迟建连

    # ── 连接 ──────────────────────────────────────────────────────
    def _connect(self):
        # 复用缓存连接前先体检：共享主机/网关常把空闲连接掐断，缓存的死连接会让后续
        # 操作报 "SSH session not active"。transport 不活就丢弃重连，做到自愈。
        if self._client is not None:
            t = self._client.get_transport()
            if t is not None and t.is_active():
                return self._client
            logger.info("[GpuClient] 检测到 SSH 连接已失效，重连")
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        try:
            import paramiko
        except ImportError as e:
            raise GpuConfigError("缺少依赖 paramiko，请 `pip install paramiko`。") from e

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = dict(
            hostname=self.host,
            port=self.port,
            username=self.user,
            timeout=30,
            allow_agent=False,
            look_for_keys=False,
        )
        if self.key_path:
            kwargs["key_filename"] = os.path.expanduser(self.key_path)
        if self.password:
            kwargs["password"] = self.password
        logger.info("[GpuClient] 连接 %s@%s:%s", self.user, self.host, self.port)
        client.connect(**kwargs)
        # AutoDL 的 connect 代理会掐掉长时间无数据流的 channel（如 Wan2.2 加载/采样时
        # 输出稀疏的几十秒），导致 exec 提前以 exit -1 断开。心跳保活避免被误杀。
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(20)
        self._client = client
        return client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "GpuClient":
        self._connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── 基础操作 ──────────────────────────────────────────────────
    def run(self, command: str, timeout: Optional[int] = None) -> RemoteResult:
        """执行远程命令（自动注入环境前缀），**逐行流式读取** stdout/stderr。

        每读到一行就转发到 log_bus（供面板实时显示进度，如 tqdm 的采样步数），
        同时累积完整输出按原契约返回 RemoteResult。tqdm 用 \\r 刷新，这里按 \\r/\\n 切行。
        """
        import time as _t
        from agent_lab.app.pipeline import log_bus

        client = self._connect()
        full = _ENV_PREFIX + command
        logger.debug("[GpuClient] $ %s", command)

        chan = client.get_transport().open_session()
        chan.exec_command(full)

        out_parts: list[str] = []
        err_parts: list[str] = []
        out_tail = ""   # 未成行的残段
        err_tail = ""
        deadline = (_t.time() + timeout) if timeout else None

        def _split_emit(tail: str, data: str) -> str:
            buf = tail + data
            # tqdm 进度用 \r 覆盖，归一成 \n 切行
            *lines, rest = buf.replace("\r", "\n").split("\n")
            for ln in lines:
                if ln.strip():
                    log_bus.emit(ln.rstrip())
            return rest

        while True:
            got = False
            if chan.recv_ready():
                data = chan.recv(8192).decode("utf-8", "replace")
                out_parts.append(data)
                out_tail = _split_emit(out_tail, data)
                got = True
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(8192).decode("utf-8", "replace")
                err_parts.append(data)
                err_tail = _split_emit(err_tail, data)
                got = True
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
            if deadline and _t.time() > deadline:
                chan.close()
                raise GpuRunError(f"远程命令超时（{timeout}s）已中止")
            if not got:
                _t.sleep(0.05)

        # 收尾残段
        for ln in (out_tail, err_tail):
            if ln.strip():
                log_bus.emit(ln.rstrip())
        code = chan.recv_exit_status()
        chan.close()
        return RemoteResult(code, "".join(out_parts), "".join(err_parts))

    def kill_inference(self) -> None:
        """杀掉 GPU 上正在跑的推理进程（取消任务时清远程残留，避免僵尸进程占卡堆积）。

        单飞队列保证同一时刻只有一个 GPU 任务在跑，故按命令名全杀是安全的。
        exec_command 立即返回，pkill 在服务器侧执行，不阻塞调用方。
        """
        # 立即杀一次 + 延迟 5 秒再杀一次（后台）：取消往往发生在远程进程"刚下发还没起来"
        # 的瞬间，单次 pkill 会扑空、进程随后才启动而存活。延迟二次清理堵住这个竞态。
        kill = ("pkill -9 -f ltx_i2v.py; pkill -9 -f generate.py; pkill -9 -f flux_candidates.py")
        try:
            c = self._connect()
            c.exec_command(f"{kill}; (sleep 5; {kill}) >/dev/null 2>&1 &")
            logger.info("[GpuClient] 已下发远程推理进程清理（含延迟二次）")
        except Exception as e:  # noqa: BLE001 - 清理是尽力而为
            logger.warning("[GpuClient] kill_inference 失败: %s", e)

    def upload(self, local_path: str, remote_path: str, *,
               stall_timeout: int = 90, retries: int = 3) -> None:
        """上传文件。云 GPU 网络不稳时传输可能中途卡死，故加「停顿超时 + 断线重连重试」。"""
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                client = self._connect()
                sftp = client.open_sftp()
                try:
                    chan = sftp.get_channel()
                    if chan is not None:
                        chan.settimeout(stall_timeout)  # 传输停顿超过该秒数即报错，避免永久挂起
                    self._sftp_makedirs(sftp, posixpath.dirname(remote_path))
                    sftp.put(local_path, remote_path)
                    logger.info("[GpuClient] 上传 %s → %s", local_path, remote_path)
                    return
                finally:
                    sftp.close()
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.warning("[GpuClient] 上传失败(第%d/%d次) %s: %s，重连重试",
                               attempt, retries, remote_path, e)
                self.close()  # 丢弃可能已坏的连接，下次重连
                time.sleep(2)
        raise GpuRunError(f"上传 {remote_path} 失败（重试 {retries} 次）：{last_err}")

    def download(self, remote_path: str, local_path: str, *,
                 stall_timeout: int = 90, retries: int = 3) -> str:
        """下载文件。同 upload：停顿超时 + 断线重连重试，杜绝因传输卡死导致整轮挂起。"""
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                client = self._connect()
                sftp = client.open_sftp()
                try:
                    chan = sftp.get_channel()
                    if chan is not None:
                        chan.settimeout(stall_timeout)
                    sftp.get(remote_path, local_path)
                    logger.info("[GpuClient] 下载 %s → %s", remote_path, local_path)
                    return local_path
                finally:
                    sftp.close()
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.warning("[GpuClient] 下载失败(第%d/%d次) %s: %s，重连重试",
                               attempt, retries, remote_path, e)
                try:
                    if os.path.exists(local_path):
                        os.remove(local_path)  # 删掉可能的半截文件，下次从头下
                except OSError:
                    pass
                self.close()
                time.sleep(2)
        raise GpuRunError(f"下载 {remote_path} 失败（重试 {retries} 次）：{last_err}")

    def exists(self, remote_path: str) -> bool:
        client = self._connect()
        sftp = client.open_sftp()
        try:
            sftp.stat(remote_path)
            return True
        except IOError:
            return False
        finally:
            sftp.close()

    @staticmethod
    def _sftp_makedirs(sftp, remote_dir: str) -> None:
        if not remote_dir or remote_dir == "/":
            return
        parts = remote_dir.strip("/").split("/")
        cur = ""
        for p in parts:
            cur += "/" + p
            try:
                sftp.stat(cur)
            except IOError:
                sftp.mkdir(cur)

    # 本机随仓库携带的服务器出图脚本（首次运行自动上传，幂等）
    _LOCAL_FLUX_SOURCE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "remote_scripts", "flux_candidates.py"
    )

    # ── 高层能力 ──────────────────────────────────────────────────
    def _ensure_flux_script(self) -> str:
        """确保服务器上有多候选出图脚本，返回其远程路径（本地源存在则上传，幂等）。"""
        remote_script = settings.GPU_FLUX_CANDIDATES_SCRIPT
        if os.path.exists(self._LOCAL_FLUX_SOURCE):
            self.upload(self._LOCAL_FLUX_SOURCE, remote_script)
        elif not self.exists(remote_script):
            raise GpuConfigError(
                f"本地缺出图脚本 {self._LOCAL_FLUX_SOURCE}，服务器也没有 {remote_script}。"
            )
        return remote_script

    def generate_candidates(
        self,
        prompt: str,
        out_remote_dir: str,
        *,
        n: Optional[int] = None,
        lora: Optional[str] = None,
        base: Optional[str] = None,
        steps: Optional[int] = None,
        guidance: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        seed: int = -1,
        offload: Optional[str] = None,
        timeout: int = 1800,
    ) -> list[str]:
        """跑 FLUX 多候选出图（单次加载、多种子），返回服务器上生成图的绝对路径列表。

        用已验证的 flux_candidates.py：每张 `SAVED::<path>` 解析收集。
        """
        script = self._ensure_flux_script()
        py = settings.GPU_PYTHON
        n = n or settings.FLUX_N
        lora = lora or settings.GPU_FLUX_LORA
        base = base or settings.GPU_FLUX_BASE
        steps = steps or settings.FLUX_STEPS
        guidance = settings.FLUX_GUIDANCE if guidance is None else guidance
        width = width or settings.FLUX_WIDTH
        height = height or settings.FLUX_HEIGHT
        offload = offload or settings.FLUX_OFFLOAD

        cmd = (
            f"{shlex.quote(py)} {shlex.quote(script)} "
            f"--prompt {shlex.quote(prompt)} --n {int(n)} "
            f"--outdir {shlex.quote(out_remote_dir)} "
            f"--lora {shlex.quote(lora)} --base {shlex.quote(base)} "
            f"--steps {int(steps)} --guidance {float(guidance)} "
            f"--width {int(width)} --height {int(height)} "
            f"--seed {int(seed)} --offload {shlex.quote(offload)}"
        )
        t0 = time.time()
        res = self.run(cmd, timeout=timeout)
        logger.info("[GpuClient] FLUX 候选出图耗时 %.0fs, exit=%s", time.time() - t0, res.exit_code)
        saved = [
            line.split("::", 1)[1].strip()
            for line in res.stdout.splitlines()
            if line.startswith("SAVED::")
        ]
        if not res.ok or not saved:
            raise GpuRunError(
                f"FLUX 出图失败 (exit {res.exit_code}, 出图 {len(saved)} 张):\n{res.stderr[-2000:]}"
            )
        return saved

    # 图生视频已解耦到 pipeline/providers/*（Wan2.2 / LTX ...）；
    # GpuClient 只保留传输与 FLUX 出图，不再认识具体视频模型。


_CLIENT_SINGLETON: Optional[GpuClient] = None


def get_gpu_client() -> GpuClient:
    """获取全局 GPU 客户端单例（按 .env 配置建连）。"""
    global _CLIENT_SINGLETON
    if _CLIENT_SINGLETON is None:
        _CLIENT_SINGLETON = GpuClient()
    return _CLIENT_SINGLETON
