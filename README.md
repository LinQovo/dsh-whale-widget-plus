# DSH 小鲸鱼余额挂件 · Plus

> 住在 DSH（DeepSeek Harness）Web 界面右下角的小挂件：盯着余额、统计今日与每轮消耗；
> 现在还能**换成你喜欢的角色形象**、**上传立绘自动 AI 抠图**、**换成你喜欢的音效**。

![showcase](assets/showcase.png)

这是 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)（MIT）的增强分支。
原有的余额、记账、拖拽吸附、Q 弹、气泡台词、峰谷定价等功能**全部保留**，在这个基础上加了三件事：

| 新增 | 一句话说明 |
| --- | --- |
| 🎭 **可换形象** | 内置小鲸鱼 + 洛天依 V3/V4/V5；菜单里随时切换，也能 `＋图` 上传任意立绘 |
| ✂️ **AI 抠图** | 上传立绘自动去背景：IS-Net(1024) / U²-Net / 纯色背景连通域 **三引擎 + 融合**，引导滤波 + 去白边 |
| 🔊 **自定义音效** | 内置小黄鸭 / 音效1，可上传 mp3/wav/ogg…；按下音与松开音分开，`▶` 可试听 |

---

## 截图里有什么

| 面板 | 内容 |
| --- | --- |
| 左 | 默认小鲸鱼：气泡显示「当前时间段 / 今日已用」 |
| 右 | 换成洛天依立绘：气泡显示「上一轮对话消耗」 |

形象与气泡位置是分开设计的：不同体型的立绘可以用菜单里的 `←` `→` `↑` `↓` 和 `缩放 %` 微调，让气泡尾巴正好指向角色的头。

## 特性

**增强部分**

- 🎭 形象管理：内置 4 套 + 自定义上传，选择记进配置，重启后保持；内置形象可切不可删
- ✂️ 抠图引擎可切换（自动 / IS-Net 精细 / u2netp 快速 / 纯色背景 / 不抠图），每张图可以单独选，`重抠` 用原图重跑
- 🧠 **纯色背景融合策略**：AI 模型遇到「白头发 + 白背景」会把角色抠出洞，所以先判断背景是否纯色，纯色时改用「边框连通域 + AI 蒙版取并集」——AI 管平滑边缘，连通域保证轮廓内一定保留
- 🪶 抠图后处理：引导滤波（边缘吸附真实轮廓）、去白边（半透明边缘反解前景色）、补洞、去碎块
- 🔊 音效集：内置 3 套 + 自定义上传（1 个文件=按下/松开同音，2 个文件=按下/松开），`▶` 试听，未知音效自动回退
- 🎵 附带 `tools/audio_cut.py`：把长音频裁成短音效，**MP3 按帧边界裁，不重新编码、不需要 ffmpeg**

**原有部分（未改动）**

- 💰 余额 60 秒自动刷新 + 点击手动刷新，数字滚动动画，网络抖动沿用最近余额
- 📊 今日已用：小鲸鱼记账（免令牌）/ 实时·令牌（峰谷定价）两种模式
- 💬 每轮对话消耗：监听本机会话事件，按真实 usage 结算
- 🖱️ 拖拽 + 四边吸附 + 左吸附整体镜像翻转
- 🧸 按压 Q 弹、随机台词、gif 气泡、音效音量、峰谷文案、滚动条避让

## 安装

```powershell
# 需要机器上有 git（dsh 会把 github: 说明符交给 pnpm，用 git 解析）
dsh plugin --profile web add github:LinQovo/dsh-whale-widget-plus
```

装完重启 `dsh web`，再刷新浏览器。插件会出现在 DSH 的插件管理页面里，之后可以直接在页面里更新。

本地开发用链接安装：

```powershell
dsh plugin --profile web add link:<本仓库绝对路径>
```

## 形象与 AI 抠图

菜单最上面三行：

| 行 | 用途 |
| --- | --- |
| **形象** | 下拉切换 + `＋图` 上传立绘（png/jpg/webp/bmp，≤15MB） |
| **抠图** | 引擎选择 + `重抠`（用原图重跑）+ `删除`（自定义形象） |
| **位置** | 气泡微调：`←` `→` `↑` `↓` + 缩放 % |

自定义形象存在 `$DSH_HOME/.dshw-characters/`（原图与抠好的 PNG 各留一份，方便随时重抠）。

### 抠图引擎

| 引擎 | 说明 |
| --- | --- |
| 自动（推荐） | 先看背景是否纯色：纯色 → 连通域 + IS-Net 融合；复杂背景 → IS-Net |
| IS-Net 精细 | IS-Net 1024×1024，适合照片 / 复杂背景 |
| u2netp 快速 | 4.4MB 轻量模型 320×320，最快 |
| 纯色背景 | 边框连通域，不需要模型，扁平插画/白底最快最准 |
| 不抠图 | 保留原图，仅统一转成 PNG |

> **为什么白底立绘不能只用 AI？** 白色头发、白衣服和白背景颜色一样，显著性模型会把它们当成背景，抠出一堆透明的洞。所以 `自动` 会先识别「纯色背景」，改用**边框连通域**：只有与画面边框连通的背景色区域才删，被轮廓包住的白色完整保留；再和 AI 蒙版**取并集**。

### 模型

仓库不带模型权重，按需下载（离线可用）：

```powershell
py tools/download_model.py --list
py tools/download_model.py --model isnet-general-use   # 约 170MB，推荐
```

抠图需要 Python（`py -3.12`）+ `Pillow` / `numpy` / `onnxruntime` / `opencv-python`。
**没装 Python 也能用**：菜单里把引擎切成「纯色背景」或「不抠图」即可，其余功能不受影响。

## 音效

菜单「音效」行选择 + `▶` 试听；「自定音效」行 `＋音效` / `删除`。

- 内置：**小黄鸭**、**音效1**
- 上传：选 1 个文件 = 按下/松开同音；选 2 个 = 第一个按下音、第二个松开音；支持 mp3/wav/ogg/m4a/aac/flac/webm，单个 ≤8MB
- 自定义音效存在 `$DSH_HOME/.dshw-sounds/`

把长音频（比如一首歌）裁成音效：

```powershell
py tools/audio_cut.py --info --input song.mp3
py tools/audio_cut.py --input song.mp3 --output press.mp3 --start 0 --end 2.6
py tools/audio_cut.py --input song.mp3 --output release.mp3 --start 21.3
```

> ⚠️ 本仓库**不包含任何受版权保护的音频**。想给挂件加某个角色的语音，请自行裁剪后通过菜单上传，注意你自己对素材的使用权。

## 目录结构

```text
dsh-whale-widget-plus/
├── package.json            # DSH bundle 插件元数据
├── cordis.patch.yml        # 插件挂载声明
├── lib/index.js            # 宿主侧插件本体（含内嵌的前端挂件脚本）
├── assets/
│   ├── DSniang1.png        # 默认小鲸鱼立绘
│   ├── characters/         # 内置形象（洛天依 V3/V4/V5，AI 抠好的透明 PNG）
│   ├── DSH2.png            # 展示图
│   └── Ya1/Ya2/D1/D2.mp3   # 内置音效
├── models/README.md        # 模型说明（*.onnx 需自行下载）
└── tools/
    ├── matting.py          # 抠图引擎 CLI（三引擎 + 引导滤波 + 去白边）
    ├── download_model.py   # 模型下载器（多镜像重试）
    ├── audio_cut.py        # 音效裁剪（MP3 帧级，不重编码）
    └── preview_layout.py   # 布局预览（不开浏览器检查气泡有没有盖住脸）
```

## 验证

```powershell
dsh --profile web --dump-config | Select-String -Pattern "whale"
curl http://127.0.0.1:3080/dsh-whale/characters.json   # 形象列表 + 抠图引擎可用情况
curl http://127.0.0.1:3080/dsh-whale/sounds.json       # 音效集列表
curl http://127.0.0.1:3080/dsh-whale/balance.json      # 余额
```

## 常见问题

- **挂件不出现**：确认 `dsh plugin add` 成功；`dsh --profile web --dump-config` 里有 `dsh-whale-widget`；重启 `dsh web` 后刷新。
- **上传后抠图报错**：检查 Python 依赖与模型是否就绪（菜单提示行 / `characters.json` 的 `matting` 字段）；也可以直接切「纯色背景」。
- **抠图有白边**：引擎选「自动」或「IS-Net 精细」，后处理里默认会去白边；纯色背景图选「纯色背景」最好。
- **换了形象后气泡位置不对**：用「位置」行微调，数值按形象单独保存。
- **音效没声音**：确认音量滑块不为 0；自定义音效是否被浏览器自动播放策略拦下（先点一下挂件再试听）。

## 桌宠模式（PET_MODE）

挂件脚本内置一个**桌宠模式**开关：宿主只要在加载 `widget.js` 之前设 `window.__dshwPetMode = true`，
就得到一个「不查余额、不记消耗」的桌面宠物版本 —— 形象、AI 抠图、音效、台词气泡、拖拽吸附、
按压 Q 弹全部保留，菜单里会自动隐藏「用量 / 峰谷 / 每轮消耗 / 避让滚动条」这些与余额和浏览器相关的行，
台词池也会换成桌宠版（去掉要钱的那几句）。

DSH 里这个标志不存在，所以插件行为与以前完全一致。基于它的 Electron 桌宠实现见
`dsh-whale-pet`（同一个作者的 `dsh-whale-*` 系列项目）。

## 致谢

- 原项目：[MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)（MIT）——小鲸鱼形象、气泡、吸附、记账等全部来自原作者
- 抠图模型：[rembg](https://github.com/danielgatis/rembg) 发布包中的 U²-Net / IS-Net（模型各自遵循其原始许可）
- 洛天依形象：本仓库内置的是通用占位插画（`assets/characters/`），**不是**官方立绘；洛天依版权归 Vsinger 所有，正式立绘请自行获取授权后通过菜单上传

## 许可证

MIT，详见 [LICENSE](LICENSE)：原始版权归 MeteorNOX，修改部分归 LinQovo。
