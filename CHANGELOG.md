# Changelog

本技能由使用数据驱动迭代。每个版本记录：数据基线（任务数/时间范围）+ 规则变化。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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
