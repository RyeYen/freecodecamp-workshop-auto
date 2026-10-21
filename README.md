# freeCodeCamp Workshop 自动答题脚本

基于 **Python + Playwright** 的非官方浏览器自动化工具，可自动读取 freeCodeCamp 公开课程源码中的参考代码，将代码填写到练习编辑器、运行测试，并在测试通过后提交和进入下一步。

脚本入口文件为 `fcc_workshop_auto.py`。

## 最常用：一条命令跑完整个 Workshop

已安装依赖、并在脚本打开的浏览器中登录过之后，在此文件夹的 PowerShell 中执行：

```powershell
python fcc_workshop_auto.py --url "https://www.freecodecamp.org/learn/javascript-v9/workshop-calculator/step-1" --no-login-pause
```

从浏览器地址栏复制你要做的 Workshop 的**完整题目网址，保留 `/step-N` 后缀**。例如上述命令会从 Calculator 第 1 步一直做到最后一步；`step-1` 只是起点，**不代表只做一道题，也不需要填写最后一步或设置 `--max-steps`**。

- **从第 1 步开始**：使用对应 Workshop 的 `/step-1` 题目链接。
- **从中间开始**：直接使用当前待做的 `/step-N` 题目链接；始终从指定步骤开始，覆盖该 Workshop 之前保存的起点。
- **第一次还没登录**：去掉 `--no-login-pause`，在弹出的浏览器登录后，回到终端按 Enter；之后再使用上面的命令。

脚本**不会自动读取账号以前完成的步骤**。如果网站上已经做到一半，请指定当前待做的 `step-N`，避免从第 1 步重做。以前示例中不含步骤的输入是脚本支持的路径简写，并不代表网站存在对应的目录页，详见下文的兼容输入说明。

> [!IMPORTANT]
> 本项目是个人学习与浏览器自动化实验工具，**不是 freeCodeCamp 官方项目**。建议先理解题目和参考代码，再用于验证自动化流程；使用时请遵守 freeCodeCamp 的课程及认证诚信要求。本脚本并不能保证完成所有课程或认证项目。

## 功能

- **获取参考代码**：从 freeCodeCamp 官方开源仓库读取课程结构和对应代码，并缓存到本地。
- **自动填写编辑器**：支持识别常见的 Monaco / CodeMirror 代码编辑区域。
- **多文件 Workshop**：等待页面加载，展开所需文件，并按文件名分别定位 HTML、CSS、JS 编辑器；已展开的文件不会被再次点击收起。
- **替换完整文件并校验**：优先通过当前 Monaco 编辑器接口替换整份源码，更新后再次核对，避免旧代码残留或粘贴事件失效。无法获取接口时才尝试整段粘贴并校验；不读取或改写系统剪贴板。
- **自动测试与提交**：依次点击 `Check Your Code`（或 `Run the Tests`）及可用的提交按钮；提交后核实是否导航离开当前题，不再仅根据点击动作计数。
- **连续完成步骤**：默认自动处理当前 Workshop 的全部剩余步骤；也可设置最大题数。
- **保存本地进度**：每次确认提交后记录下一步；兼容的路径简写模式可自动读取该进度续跑。
- **处理捐赠弹窗**：识别提交后偶尔弹出的捐赠提示，等待动画结束后自动点击 `Ask me later`。
- **处理项目预览**：首次进入项目出现 “Here's a preview of what you will build” 时，自动点击该预览窗口内的 `Start coding!`。
- **复用登录状态**：保存独立浏览器配置，通常无需每次登录。
- **失败诊断**：失败时自动保存截图和编辑器诊断文本，便于排查。
- **退出状态**：成功返回 `0`，运行失败返回 `1`，按 Ctrl+C 中断返回 `130`，便于终端或其他程序判断结果；参数使用错误返回 `2`。

## 运行环境

- Windows 10 / 11（下列操作以 PowerShell 为例）；其他系统可根据环境调整命令。
- Python **3.10 或更新版本**。
- 可访问 freeCodeCamp 网站和 GitHub 官方课程源码的网络环境。
- Chromium 浏览器，由 Playwright 安装和管理。

## 1. 安装

克隆本仓库：

```powershell
git clone https://github.com/RyeYen/freecodecamp-workshop-auto.git
cd freecodecamp-workshop-auto
```

也可以在仓库页面选择 **Code → Download ZIP**，解压后在项目文件夹中打开 PowerShell。

安装 Python 依赖和浏览器：

```powershell
python --version
python -m pip install -r requirements.txt
python -m playwright install chromium
```

`requirements.txt` 固定为已验证的 Playwright 1.64.0。若只下载主程序，也可以手动安装依赖：

```text
freecodecamp脚本/
└── fcc_workshop_auto.py
```

在此文件夹打开 PowerShell，然后执行：

```powershell
python --version
python -m pip install playwright
python -m playwright install chromium
```

若电脑上需要通过 `py` 启动 Python，可将下文命令中的 `python` 替换为 `py`。

## 2. 第一次运行：先测试一道题

脚本默认从下面的示例课程开始：

<https://www.freecodecamp.org/learn/javascript-v9/workshop-greeting-bot/step-1>

建议首次仅运行一道题：

```powershell
python fcc_workshop_auto.py --max-steps 1
```

执行后：

1. 程序下载并解析相应课程源码。
2. 自动打开一个由 Playwright 管理的 Chromium 窗口。
3. 如未登录，请在该窗口中登录 freeCodeCamp。
4. 回到 PowerShell，按 **Enter** 开始。
5. 脚本填写代码、运行测试，并在出现可提交状态后提交。

> 第一次运行请观察页面是否正常加载。如果遇到登录验证或其他未识别的提示，先人工处理；脚本不会尝试绕过验证。

## 3. 连续完成当前 Workshop

**现在默认自动运行到当前 Workshop 的最后一步**，无需手动计算题目数量。

以 *Greeting Bot* 为例，使用实际的第 1 步题目链接即可连续完成整个 Workshop：

```powershell
python fcc_workshop_auto.py --url "https://www.freecodecamp.org/learn/javascript-v9/workshop-greeting-bot/step-1" --no-login-pause
```

如果你的浏览器目前已经完成到 Step 5，希望从 **Step 6** 一直完成到最后一步，则运行：

```powershell
python fcc_workshop_auto.py --url "https://www.freecodecamp.org/learn/javascript-v9/workshop-greeting-bot/step-6" --no-login-pause
```

**注意：** 指定具体 `step-N` 时，应填写**准备开始的题目**地址。`--max-steps` 是本次运行允许处理的**最大题数**，不是终点步骤编号；默认值 `0` 表示处理本 Workshop 的全部剩余步骤。脚本只处理当前课程单元，不会自动跨越到另一个 Workshop。

进度保存在脚本旁边的 `.fcc_progress.json` 中，按课程和 Workshop 分别记录。本地记录不与网站账号同步；指定具体 `step-N` 链接时，以你填写的步骤为起点。**重复使用 `/step-1` 命令会从第 1 步重做，不会自动续跑。**

如果需要运行其他类似课程，将 `--url` 换成对应 freeCodeCamp 练习页面网址即可；但并非所有课程格式都受支持。

### 兼容输入：不含步骤的路径简写

旧命令中类似 `https://www.freecodecamp.org/learn/javascript-v9/workshop-calculator` 的输入，是**脚本识别的 Workshop 路径简写**，不要求它是可以在浏览器中打开的页面。之前将它称为“目录链接”不准确。

脚本会先查找本地进度，将简写补全为实际的 `/step-N` 题目网址，再打开浏览器；没有记录时补成 `/step-1`。只有这种简写模式会自动选择本地记录的起点，已记录全部完成时会直接退出。

因此，旧命令仍然兼容。日常使用可以直接复制网站的完整题目链接；希望自动恢复本地进度时，也可以继续使用上述简写。两种输入都不需要网站存在一个不含步骤后缀的 Workshop 目录页。

### 最后一题无法自动完成怎么办？

例如 *String Transformer* 有 11 步，若仅剩 Step 11，请先在 PowerShell 查看最后一步参考代码：

```powershell
python fcc_workshop_auto.py --url "https://www.freecodecamp.org/learn/javascript-v9/workshop-string-transformer/step-11" --dry-run
```

确认能够输出包含 `.trimEnd()` 的参考代码后，再运行：

```powershell
python fcc_workshop_auto.py --url "https://www.freecodecamp.org/learn/javascript-v9/workshop-string-transformer/step-11" --no-login-pause
```

脚本会尝试提交最后一步，并核实提交后是否导航离开当前题。如果始终停留在当前网址，脚本将保存诊断截图并**报告无法核实完成状态**，不会把单纯点击提交算作完成。网站也可能直接更新题目列表中的完成状态而不导航，此时需要人工核查最终进度。

### HTML、CSS、JS 同时存在的 Workshop

例如 Todo App 使用三个源码文件，运行方式相同：

```powershell
python fcc_workshop_auto.py --url "https://www.freecodecamp.org/learn/javascript-v9/workshop-todo-app/step-1" --no-login-pause
```

脚本会等待课程编辑器加载，自动关闭已识别的项目预览，再分别展开并填写 `index.html`、`styles.css`、`script.js`。写入与延迟核对会绑定到对应文件的同一个编辑器实例；即使页面把焦点切回 JS，也会继续核对原来的 HTML/CSS 文件。源码内容确实不一致时仍会停止。

## 4. 只查看参考代码，不提交

可以使用 `--dry-run` 查看题目的参考代码，不打开浏览器，也不会修改任何学习进度：

```powershell
python fcc_workshop_auto.py --url "https://www.freecodecamp.org/learn/javascript-v9/workshop-greeting-bot/step-1" --dry-run
```

此命令仍可能联网下载课程源码（已有缓存时会优先使用本地缓存）。

## 5. 命令行参数

| 参数 | 含义 | 默认值 |
| --- | --- | --- |
| `--url` | 推荐填写完整的 `step-N` 题目链接，指定起点；兼容不含步骤的路径简写（自动读取本地进度） | Greeting Bot Step 1 |
| `--max-steps N` | 本次最多处理 `N` 道题；`0` 表示全部剩余题目 | `0` |
| `--no-login-pause` | 跳过等待人工登录的暂停，直接使用已保存的浏览器配置 | 不启用 |
| `--dry-run` | 只输出参考代码，不打开浏览器或提交 | 不启用 |
| `-h`、`--help` | 显示帮助信息 | — |

查看完整参数帮助：

```powershell
python fcc_workshop_auto.py --help
```

## 6. 自动处理捐赠弹窗

有时提交成功后，freeCodeCamp 会弹出带有 **“Help millions of people learn”** 字样的捐赠提示。

脚本会在填写编辑器前、点击按钮前以及等待下一题时检查此弹窗。如果检测到，会：

1. 等待弹窗动画播放，直到 `Ask me later` 按钮可用。
2. 自动点击 `Ask me later`。
3. 确认弹窗关闭后继续。

动画本身可能持续约 **20 秒**，这是正常等待，不代表程序卡死。如果超过脚本设定的等待时间（45 秒）仍无法关闭，程序会停止并保留诊断信息。未识别的弹窗仍可能需要人工处理。

## 7. 工作原理与支持范围

脚本根据当前网址中的课程单元和步骤编号定位 freeCodeCamp 开源课程数据：

```text
freeCodeCamp 页面 URL
        ↓
读取 curriculum/structure/blocks/<block>.json
        ↓
查找对应 challenge 的 Markdown 文件
        ↓
提取显式 solutions，或读取下一步的 seed（Workshop）
        ↓
填写编辑器 → 运行测试 → 提交 → 核实页面跳转 → 下一题
```

**当前主要支持：** 具有常规步骤 URL 和可提取参考代码的 Workshop，以及部分带有显式 `solutions` 的编码挑战。支持提取 `html`、`css`、`js` 等常见代码块；实际多文件编辑器的兼容性取决于网页结构。

**不保证支持：** 所有 Lab、Quiz、选择题、认证考试、没有可提取答案的挑战，或 freeCodeCamp 后续大幅修改页面结构的情况。网站正在使用的课程版本也可能与 GitHub `main` 分支不完全一致。

## 8. 常见问题

### 提示“找不到可编辑的代码区域”

检查浏览器是否已打开正确的练习页面、是否完成登录、是否被其他弹窗遮挡，以及编辑器是否加载完成。失败后检查 `fcc_editor_diagnostic.txt` 和 `fcc_failed_step.png`。

若旧版本进入多文件课程立即提示“找不到 html 文件标签”，而诊断中的标题、编辑器、按钮都为空，说明脚本在应用界面加载前就开始查找。更新后会先等待编辑器和文件标签；已识别的项目预览也会自动关闭。诊断中另会记录每个文件标签的展开状态。

若旧版本连续运行 Todo App 时出现“预期 2296 字符，实际 2208 字符”，可能是核对 HTML 时焦点已切回 JS，读到了另一个文件。新版本会固定核对目标实例；更新后用报错步骤的 `/step-N` 地址继续即可，无需从第 1 步重做。

### 停在捐赠弹窗页面

若动画还在播放，先等待按钮出现。脚本会尝试自动点击 `Ask me later`。如最终超时，保存终端报错和诊断文件排查，不建议强制移除遮罩。

### 提示“测试未出现可提交状态”

通常表示测试尚未通过、页面按钮名称变化或加载超时。脚本不会直接跳过失败的测试。检查页面上的测试结果及失败截图。

若旧版本运行 Calculator 时出现多余的 `}`、`SyntaxError` 或一直报告“预期 35 字符，实际 47 字符”，更新脚本后使用同一条命令重试；新版本优先调用 Monaco 接口替换完整文件，终端会显示“通过 Monaco 完整文件接口替换并核对”。若内容仍不一致，程序会停在当前步骤并保存诊断信息。

### 提示“无法下载官方课程文件”

请检查网络是否可以访问 `raw.githubusercontent.com`。脚本将成功下载的课程文件保存在 `.fcc_curriculum_cache/` 目录；需要更新课程源码时，可在关闭脚本后删除该缓存目录，再重新运行。

### 一直要求重新登录

请确认使用的是脚本弹出的 Chromium 窗口，而不是日常使用的 Chrome。登录状态保存在脚本旁边的 `.fcc_browser_profile/` 目录中，使用同一个目录再次运行通常可以复用登录状态。

### 明明剩最后一题，却只做完前面几题

先检查是否手动设置了 `--max-steps`。这个参数限制的是**此次运行总题数**，不是目标的最后一步。现在省略该参数便会根据课程结构自动计算剩余题数。

### 想从上次中断的地方继续

使用终端最后显示的当前待做题目网址（含 `/step-N`）重新运行即可。如果希望脚本自动选择本地记录的步骤，可以使用上文说明的**路径简写模式**。脚本只在提交并确认进入下一页后前移本地进度；若最后一次提交结果无法核实，重试时可能再次处理该题。

具体题目链接始终指定起点：例如 `/step-6` 会从第 6 步继续做到最后，`/step-1` 会从第 1 步重新开始。

## 9. 文件说明与隐私

脚本运行后，所在目录可能包含：

```text
freecodecamp脚本/
├── fcc_workshop_auto.py   # 主程序
├── README.md                 # 使用说明
├── requirements.txt          # Python 依赖（固定已验证的版本）
├── test_fcc_workshop_auto.py  # 离线回归测试
├── .gitignore                # 排除登录状态、缓存和本地进度
├── .fcc_browser_profile/     # Chromium 配置及登录状态（敏感）
├── .fcc_curriculum_cache/    # 官方课程源码缓存
├── .fcc_progress.json       # 各 Workshop 的待执行步骤和更新时间
├── fcc_failed_step.png       # 失败页面截图（出错后生成）
└── fcc_editor_diagnostic.txt # 页面/编辑器诊断信息（出错后生成）
```

**请勿将 `.fcc_browser_profile/` 上传到 GitHub、发送给其他人，或随项目公开分享**：其中可能包含已登录会话的 Cookie。共享失败截图前，也请自行检查是否显示了个人信息。

工作区已提供 `.gitignore`，包含：

```gitignore
.fcc_browser_profile/
.fcc_curriculum_cache/
.fcc_progress.json
.fcc_progress.json.tmp
__pycache__/
*.pyc
.venv/
venv/
.env
.env.*
fcc_failed_step.png
fcc_editor_diagnostic.txt
```

## 10. 注意事项

- 推荐先用 `--dry-run` 检查参考答案，再用 `--max-steps 1` 验证网页兼容性。
- 运行时不要同时启动两个使用同一 `.fcc_browser_profile/` 的脚本实例。
- 自动化流程会实际提交题目并改变账号的学习进度；请确认这是你希望进行的操作。
- 浏览器自动化容易受到网页更新影响；若出现异常，应优先查看终端信息和诊断文件。
- freeCodeCamp 是第三方平台，本项目与其官方没有关联。

开发时可运行离线回归测试（模拟浏览器导航，不会向网站提交）：

```powershell
python -m unittest -v test_fcc_workshop_auto.py
```

---

**技术栈：** Python · Playwright · Chromium  
**示例课程：** [Build a Greeting Bot](https://www.freecodecamp.org/learn/javascript-v9/workshop-greeting-bot/step-1)
