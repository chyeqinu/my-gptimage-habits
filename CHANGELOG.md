# Changelog

本技能由使用数据驱动迭代。每个版本记录：数据基线（任务数/时间范围）+ 规则变化。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## v1.1.0（2026-09-04）

**接口端点迁移 + 协议行为实测修正**（实测环境：`https://ai-pixel.online`，模型 gpt-image-2）。

数据基线：同 v1.0.0（272 条任务）；本版为**协议层**更新，任务数据不变。

### 变更

- 默认端点 `https://speed.ai-pixel.online` → **`https://ai-pixel.online`**（用户告知端点变更；本机配置已同步）
- 实测证实：**平台参数 UI 不作用到出图，提示词是控制项**：
  - `size` 参数被中转站忽略（实测发 720x1280 返回 1672x941）→ **比例必须写进 prompt**（“（16：9）”→1672x941、“（9：16）”→941x1672，均实测）
  - prompt 含“透明底”→ **直接返回带 alpha 的真透明 PNG**（实测 73% 像素 alpha=0、无颜色残留、视觉验证棋盘格透出）→ 透明底不再需要 background 参数 / 平台选项 / 本地抠键色
- `--transparent` 降级为**兜底模式**（[背景指令]+本地抠键色保留，仅在返回图无 alpha 时使用）
- `gimg.py` 新增：出图后自动校验 alpha 通道（prompt 含“透明底”但返回无 alpha 时明确警告）
- 规则文档全面更新：`parameters.md`（§1/§2.1/§3/§6/§9）、`prompt-recipes.md`（比例与用途速查改为 prompt 写法）、`workflows.md`、`iteration-and-errors.md`（新增两条错误处理）
- 视觉验证：测试图经视觉模型复核（16:9 横版/9:16 竖版/透明底棋盘格透出，文字 OCR 无误）

### 不变

- 8 类工作流模板、风格词库、迭代节奏（短句+保护句）、n=1/n=2 规则
- 绿幕抠图习惯（“方便抠图的纯绿色背景”）
- 串行出图、1000s timeout、key 配置方式（env > ~/.gptimage > ~/.gptimage-ppt）

## v1.0.0（2026-09-01）

数据基线：**272 条任务**（2026-07-21 → 2026-09-01，268 成功 / 4 失败），
来源为 gpt-image-playground 三份导出备份合并去重。

### 新增

- 8 类工作流提示词模板（封面/字幕条批量/绿幕抠图/多图合成/就地改字/单张PPT封面/分镜图/风格复刻）
- 参数规则：size 默认 auto、quality 默认 auto、n=1 定稿 / n=2 探索、png、绿幕优先于透明
- `scripts/gimg.py`：直连 API 出图（纯标准库），包含——
  - `@图N`（含零宽标记）自动转 `[image N]`
  - 有参考图自动走 `images/edits`（multipart `image[]`），无参考图走 `images/generations`（JSON）
  - 单请求 n>1 被拒时自动退化为串行 n=1
  - `--transparent` 真透明底：追加平台同款 [背景指令] 块（#00FF00/#FF00FF）+ 本地键色抠除（纯标准库 PNG 编解码 + 与平台同算法的泛洪/去溢色）
  - key 读取：环境变量 `GPTIMAGE_API_KEY` > `~/.gptimage/config.json` > `~/.gptimage-ppt/config.json`
- 接口协议对照 gpt-image-playground 源码（github.com/CookSleep/gpt_image_playground）核实
  （端点 / mention 转换 / 透明底实现 / n>1 与 background 限制），并实测三条链路通过
- 跨平台安装脚本（Windows PowerShell / macOS·Linux sh）
- 迭代规则：短句修改 + 保护句“其他不变”、绿底每轮重申、先出图确认再批量
