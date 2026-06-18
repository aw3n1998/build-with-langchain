# 蜃景 × lightx2v 文生视频(t2v)部署 — 状态与待办

> 交接文档 · 2026-06-17 · 换机继续用
> 配套笔记本：`colab_lightx2v_t2v.ipynb`（仓库根，已全推 `origin/main`）

---

## 一、最终目的

**Mirage 蜃景** = 中文小说 → AI 文生视频(t2v)短剧的 web agent。
流程：粘小说 → AI 分析人物/分镜 → 每个镜头用 **lightx2v + Wan2.2-T2V-A14B** 出竖屏短片 → 导出。

- **纯 t2v 路线**：不要图生视频(i2v)、不要出图/选图。
- **GPU 双机**：开发/训练机 = RTX PRO 6000(96G)；部署/出片机 = 公司 5090(32G, Blackwell)。当前在 **Colab** 上验证 lightx2v t2v 出片链路。
- **人物一致性**：用自训的角色 LoRA（Wan-T2V 双专家 `char_lora_high_noise/low_noise.safetensors`）锁人物。

## 二、整体架构

```
前端(纯 t2v 工作台)  ──HTTP──►  mirage 后端(FastAPI :8000)  ──HTTP──►  lightx2v server(:8189)
                                       │                                   └ Wan2.2-T2V-A14B 双专家(MoE)
                                  cloudflared 公网 URL
```
部署笔记本分格：§1 GPU探测 · §2 拉 mirage 仓库 · §3 装 lightx2v · §4 下权重到本地 · §5 起 server · §5b 转格式(备用) · §5c 查状态 · §6 后端+.env · §7 前端 · §8 起后端 · §9 公网URL · §10 实时日志。

## 三、已完成 ✅（今天扫平的坑，全部固化进 §3/§4/§5）

1. **lightx2v 安装（5 坑）**：
   - lightx2v 0.1.0 钉死 `torch<2.8.0`，撞 Colab/Blackwell 的 cu128 torch 2.8 → 本体 + 依赖全 `pip install -e . --no-deps`（绕过 torch 解析）。
   - 残留元数据(pip 说装了却 import 不了) → 装前 `pip uninstall -y lightx2v` 清掉；**别用 `pip install lightx2v`（PyPI 是残壳）**。
   - editable 的 `.pth` 内核不重读 → `sys.path.insert` + 一切以**干净子进程** import 为准。
   - `worldmirror`(硬 import flash_attn) / `ring_attn`(`@torch.jit.script` 新 torch 编不过) 跟单卡 t2v 无关却崩 import → patch 文件。
   - torch↔torchvision ABI 不匹配 → 子进程探测、坏了原子重装匹配的 cu128 三件套(torch2.8/tv0.23/ta2.8)。
2. **配置文件**：必须用 **`configs/wan22/wan_moe_t2v.json`**（含 `boundary=0.875` 双专家切换点）。**别用 `configs/wan/wan_t2v.json`**（旧 Wan2.1 单模型、缺 boundary → `KeyError 'boundary'` 崩）。§3 自动选对。
3. **注意力算子**：必须 `torch_sdpa`。配置里默认的 `flash_attn3` 没装、调到会 `'NoneType' object is not callable`。§3 已自动改成 torch_sdpa（SageAttention 编上了则用 sage_attn2）。
4. **权重加载提速**：直接 `snapshot_download` 到本地 `/content/wan_local`（HF CDN ~170MB/s，比 Drive FUSE 冷读 ~50MB/s 快 3 倍多；本地 SSD 加载秒级）。取舍=每会话重下 ~67G(~10 分钟)。
5. **5090(32G) 兼容**：§1 按显存自动切——小卡 `cpu_offload=true` + `offload_granularity=model` + `offload_ratio=1.0`（lightx2v 官方称 24G 即够）；大卡(>70G)双专家全 GPU bf16。
6. **已跑通（RTX PRO 6000 96G 实测，2026-06-18）**：server 起来、双专家权重加载成功（diffusers 格式直读）、**出片裸片成功**（关键修复=`rope_type=torch`，见下 ✅ 段）。`cpu_offload=False` 双专家全 GPU bf16；SageAttention sm120 编不过→`torch_sdpa`，不影响。

## 四、还未实现 ❌（待办，按优先级）

### ✅ 已定位并修复（原 🔴 出片 `'NoneType' object is not callable`）—— 2026-06-18
- **真凶**：`rope_type` 没设 → 代码默认 `flashinfer`，而 flashinfer 全程 `--no-deps` 装、**根本没装** → `apply_rope_with_cos_sin_cache_inplace` 是 `None`，第一个 transformer block 调它就崩。
  与现象完全吻合：attn 已是 `torch_sdpa`、无量化，却仍 NoneType。（之前 §3 补丁只强制了 3 个 attn 键，漏了 `rope_type`。）
- **修复（已固化进 §3）**：attn 三键之后加 `c['rope_type']='torch'` + `c['rms_norm_type']='torch'`（防御性）。
  - 老会话热修(不重拉)：`import json;p='/content/wan_moe_t2v_use.json';c=json.load(open(p));c['rope_type']='torch';c['rms_norm_type']='torch';json.dump(c,open(p,'w'),indent=2)` → 回 §5 重起 server。
- **诊断法（留档）**：worker 真帧在 `worker.py:108 logger.exception` 打到日志，**在 REAL_TB 之前**：`grep -n 'inference failed' -A 120 /content/lightx2v.log`（base.py:196 的 REAL_TB 是重抛、真帧跨进程丢，要看 worker 那条）。
- **若仍崩**：grep 上面那条看最深帧的 `File ... line ...`，多半是又一个没装的算子；按同样思路把对应 `*_type` 键强制 torch。后台研究备选项：`feature_caching=NoCaching`、`dit_quantized=false`、并行标志全 false。

### 🟡 LoRA 挂载（两个缺口）
1. **笔记本没有「挂 LoRA」专用格**。手动挂法：server 的 config json 里加 `lora_configs`：
   ```json
   "lora_configs": [
     {"name": "high_noise_model", "path": ".../char_lora_high_noise.safetensors", "strength": 1.0},
     {"name": "low_noise_model",  "path": ".../char_lora_low_noise.safetensors",  "strength": 1.0}
   ]
   ```
   - `name` 是路由键，**只能是 `"high_noise_model"`/`"low_noise_model"`**（精确大小写），双专家各一条。
   - 多 LoRA 同 name 可**叠加**（如蒸馏加速 LoRA + 人物 LoRA 列 4 条）。
   - **改 LoRA 要重启 server**（per-request 传 lora 会被 server 忽略）。
   - **merge LoRA 与量化/lazy_load 互斥** → 挂人物 LoRA 必须 bf16，**5090 上别同时上 fp8**。
2. **mirage 后端的 LoRA 自动接入是坏的**（3 bug，要改代码，文件 `mirage/app/pipeline/providers/lightx2v.py:41-57,124-129`）：
   - `_lora_configs()` 产出的条目**缺 `name` 字段**（会 KeyError）。
   - LoRA 塞进 **per-request payload**（被 server 忽略），应写进**起 server 的 config json**。
   - 部署 §5 起 server 时 config 里**没开 lora**。
   - **修法**：部署侧生成带 `lora_configs`（4 条、带正确 name）的 config，server 用它启动；provider 把 lora 写进"起 server 的 config"而非请求 payload。

### ⚪ 更早的 backlog
- BGM 自动垫乐 + 平台导出预设（抖音竖屏 1080×1920）。
- fp8 量化（5090 提速）：lightx2v 无现成 T2V-A14B fp8 权重，要 `tools/convert/converter.py --linear_type fp8` 自转双专家 + 装 sgl-kernel，且与 merge LoRA 互斥；ComfyUI 的 fp8_scaled 线更现成。默认不开，§3 留了注释。

## 五、怎么在另一台电脑继续

1. 代码已全推 **`origin/main`**（`github.com/aw3n1998/build-with-langchain`），换机直接用，不用拉本地。
2. 打开 Colab 笔记本（GitHub 直链）→ 菜单「代码执行程序 → 全部运行」：
   `https://colab.research.google.com/github/aw3n1998/build-with-langchain/blob/main/colab_lightx2v_t2v.ipynb`
3. 跑到 §5 `✅ lightx2v 就绪` 后，**主攻「出片 NoneType」**（见 四·🔴 的调试法）。
4. 出片裸片通了，再做 LoRA（四·🟡）。

## 六、关键事实速查

| 项 | 值 |
|---|---|
| 配置文件 | `configs/wan22/wan_moe_t2v.json`（boundary 0.875） |
| attn | `torch_sdpa`（不能 flash_attn3） |
| 权重位置 | `/content/wan_local`（每会话从 HF 下，**不是** Drive） |
| 起 server | `python -m lightx2v.server --model_cls wan2.2_moe --task t2v --model_path /content/wan_local --config_json <上面config> --host 0.0.0.0 --port 8189` |
| server 状态 | `GET http://127.0.0.1:8189/v1/service/status` |
| 你训的人物 LoRA | `char_lora_high_noise.safetensors` / `char_lora_low_noise.safetensors` |
| 出片状态 | ✅ 裸片跑通（RTX PRO 6000）；关键修复 `rope_type=torch`（默认 flashinfer 没装）+ attn 三键 torch_sdpa |
