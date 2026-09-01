# my-gptimage-habits

一个 Agent 技能（Skill）：把个人的 **gpt-image-2 使用习惯**（提示词模板 + 参数偏好 +
工作流 SOP）固化成可执行规则，任何装有它的 Agent（DeepSeek Harness / Claude Code 等）
都能直接调用生图 API，按你的习惯出图并迭代。

由 272 条真实历史任务（视频封面 / 字幕条 / 绿幕抠图 / 多图合成 / 改字 / PPT 封面 /
分镜图）提炼，接口协议对照 gpt-image-playground 平台源码逐一核实。

## 支持的工作流

| 场景 | 说明 |
|---|---|
| W1 视频封面加字 | 背景图 + 主/副标题，16:9 / 9:16 |
| W2 字幕条 / 人名条批量 | 首版探索 n=2，定稿后批量“字改成 X，保留板式” |
| W3 元素提取 / 绿幕 / 透明底 | 绿幕（剪辑软件色度键）或真透明底（自动 [背景指令]+本地抠键色） |
| W4 多图合成 | 人物并图、水平面/身高匹配/脸部细节 |
| W5 就地改字 | 最小改动 + 保护句“其他不变” |
| W6 单张 PPT 封面 | 结构化 prompt（主题/内容/素材/风格要点） |
| W7 分镜图 | N 宫格分镜 |
| W8 风格复刻 | 仿照参考图风格 |

## 安装

把本仓库整个目录放到 Agent 技能目录下（目录名保持 `my-gptimage-habits`）：

### Windows

```powershell
git clone <本仓库地址> C:\Users\<你>\.agents\skills\my-gptimage-habits
# 或：powershell -ExecutionPolicy Bypass -File install\install.ps1   （在本仓库内执行）
```

### macOS / Linux

```sh
git clone <本仓库地址> ~/.agents/skills/my-gptimage-habits
# 或：sh install/install.sh   （在本仓库内执行）
```

装好后 Agent 会话中自动识别技能 `my-gptimage-habits`（新会话生效）。

## 配置 API key（每台设备一次）

三选一：

```sh
# 1) 非交互（推荐）
python scripts/gimg.py --set-key <你的key> [--set-base-url https://speed.ai-pixel.online]

# 2) 交互式
python scripts/gimg.py --configure

# 3) 环境变量
export GPTIMAGE_API_KEY=<你的key>
```

验证：`python scripts/gimg.py --show-config`（key 会打码显示）。
key 只保存在 `~/.gptimage/config.json`（600 权限）或环境变量里，**仓库内不含任何明文 key**。

## 用法（对 Agent 说人话即可）

- “按我的习惯，给这个视频画面做个封面：主标题 XX，副标题 YY，9:16”
- “做一个人名字幕条：张 XX，娄底三中小学校长，绿底的”
- “把图里的标题提取出来，透明底”
- “把图二的人加到图一右边，注意水平面”
- “图里的字改成 XX，其他不变”
- “做一张 PPT 封面，21:9，政务风”

也可以直接跑脚本（Agent 内部就是这么调的）：

```sh
python scripts/gimg.py --prompt "把以下文字加到画面中作为我的视频封面（9：16）↵主标题↵副标题↵要有高级感设计感" \
  --images 背景图.jpg --size 720x1280 --n 2 --out-dir out --name cover
```

## 目录结构

```
my-gptimage-habits/
├── SKILL.md              Agent 执行手册（触发条件 + 7 步流程）
├── scripts/gimg.py       出图 CLI（纯标准库，无第三方依赖）
├── references/           规则文档（参数/提示词模板/SOP/迭代与排错）
├── .env.example          接口配置示例
├── VERSION / CHANGELOG.md  数据版本与更新记录
├── install/              跨平台安装脚本
└── README.md / LICENSE
```

## 可持续更新

本技能由使用数据驱动：平台使用数据增长后，在数据侧项目里跑
`python analysis/analyze.py --diff` 产出规则变更报告 → 更新 `references/` →
bump `VERSION` + `CHANGELOG.md` → 提交推送。新设备 `git pull` 即完成升级。
（完整流程见数据侧项目的 `UPDATING.md`。）

## 许可

MIT。规则与提示词模板源于个人使用数据，请勿用于冒充他人风格对外商用。
