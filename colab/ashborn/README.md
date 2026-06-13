# 《ASHBORN / 灰烬之子》— 原创短剧制作包

把中文修仙小说《从寒微杂役到万世帝尊》**转化为原创欧美竖屏短剧**的全部创意资产。

> **版权立场**:只借用"寒微逆袭"这一通用类型套路(创意/套路不受著作权保护),
> 世界观、人名、功法体系、场景、台词**全部原创重写**,是一部全新作品,非翻译/改写。

## 目录
- `character_bible.md` — 世界观 + 三主角设定(含外貌锚点,喂 FLUX 用)
- `ep01_script.md` — 第一集竖屏分镜剧本(钩子/反转/集尾钩)
- `lora_triggers.md` — 三角色 LoRA 触发词 + 定妆照 FLUX 提示词
- `flf2v_prompts.md` — 首尾帧(start/end)提示词 + 写法规则
- `scenes_ep01.json` — 第一集结构化分镜(供出片参考/导入)

## 这些资产怎么进出片流水线
1. 用 `lora_triggers.md` 的提示词在 ComfyUI 出**三张定妆照**。
2. 以定妆照为锚训练**角色 LoRA**(见 `../train_character_lora.ipynb`,待建)。
3. 出片时每镜 `image_prompt` 带上该镜出场角色的**触发词** → FLUX 出图脸一致。
4. 需要"受控动作"的镜头用 `flf2v_prompts.md` 的首尾帧法;普通镜头用文字驱动 i2v。
5. 对口型镜头走 Wan2.2-S2V + edge-tts。
