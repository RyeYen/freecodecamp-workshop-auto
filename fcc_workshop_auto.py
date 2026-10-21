"""freeCodeCamp v9 Workshop 自动填写 / 检查 / 进入下一步（非官方脚本）.

来源：freeCodeCamp 开源 curriculum：
- curriculum/structure/blocks/<block>.json 的 challengeOrder
- curriculum/challenges/english/blocks/<block>/<id>.md 的 seed / solutions

运行：
    pip install playwright
    python -m playwright install chromium
    python fcc_workshop_auto.py --url "https://www.freecodecamp.org/learn/javascript-v9/workshop-calculator/step-1" --no-login-pause

首次登录去掉 --no-login-pause。step-N 题目链接指定起点，并连续处理本 Workshop 的剩余步骤。
兼容不含步骤的路径简写：先按 .fcc_progress.json 补成真实题目 URL 再导航，不要求该简写是网页。
复用 .fcc_browser_profile 登录态。只处理 Workshop 和带有显式 solutions 的编码挑战。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

START_URL = "https://www.freecodecamp.org/learn/javascript-v9/workshop-greeting-bot/step-1"
RAW = "https://raw.githubusercontent.com/freeCodeCamp/freeCodeCamp/main"
BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = BASE_DIR / ".fcc_browser_profile"
CACHE_DIR = BASE_DIR / ".fcc_curriculum_cache"
PROGRESS_FILE = BASE_DIR / ".fcc_progress.json"
FILE_PATTERNS = {
    "html": r"(?:\.html?\b|\bhtml\b)",
    "css": r"(?:\.css\b|\bcss\b)",
    "js": r"(?:\.js\b|\bjavascript\b)",
    "ts": r"(?:\.ts\b|\btypescript\b)",
    "jsx": r"(?:\.jsx\b|\bjsx\b)",
    "tsx": r"(?:\.tsx\b|\btsx\b)",
    "py": r"(?:\.py\b|\bpython\b)",
}
EDITOR_MODES = {
    "html": "html", "css": "css", "js": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript", "py": "python",
}


class UnsupportedChallenge(RuntimeError):
    pass


def get_text(relative_path: str) -> str:
    """获取并缓存官方源码，避免重复请求。"""
    cache_file = CACHE_DIR / relative_path
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    url = f"{RAW}/{relative_path}"
    request = Request(url, headers={"User-Agent": "fcc-workshop-helper/1.0"})
    try:
        with urlopen(request, timeout=25) as response:
            data = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"无法下载官方课程文件：{url}\n{exc}") from exc
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(data, encoding="utf-8")
    return data


def parse_page_url(url: str) -> tuple[str, str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "www.freecodecamp.org", "freecodecamp.org"
    }:
        raise UnsupportedChallenge("不是 freeCodeCamp 官方课程网址。")
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "learn":
        raise UnsupportedChallenge(f"无法识别课程路径：{parsed.path}")
    if any(not re.fullmatch(r"[a-z0-9-]+", part) for part in parts[1:]):
        raise UnsupportedChallenge("课程路径只能包含小写字母、数字和连字符。")
    return parts[1], parts[2], parts[3]


def normalize_start_url(url: str) -> tuple[str, bool]:
    """接受具体题目网址或不含步骤的路径简写，补齐 step 后再用于导航。"""
    parsed = urlparse(url.strip())
    parts = parsed.path.strip("/").split("/")
    is_workshop_url = len(parts) == 3 and parts[0] == "learn"
    if is_workshop_url:
        parts.append("step-1")
    candidate = parsed._replace(path="/" + "/".join(parts), query="", fragment="").geturl()
    course, block, step = parse_page_url(candidate)
    return f"https://www.freecodecamp.org/learn/{course}/{block}/{step}", is_workshop_url


def load_progress() -> dict:
    if not PROGRESS_FILE.exists():
        return {"version": 1, "workshops": {}}
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("workshops"), dict):
            raise ValueError("不支持的进度文件格式")
        return data
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"无法读取进度文件 {PROGRESS_FILE}：{exc}；请将该文件改名后重试。") from exc


def saved_next_step(progress: dict, course: str, block: str, total: int) -> int:
    record = progress["workshops"].get(f"{course}/{block}")
    if record is None:
        return 1
    if not isinstance(record, dict):
        raise RuntimeError(f"{block} 的进度记录损坏，请检查 {PROGRESS_FILE}。")
    if record.get("total_steps") != total:
        print("官方课程步数已变化，本地记录不再适用；将从第 1 步开始。")
        return 1
    step = record.get("next_step")
    if type(step) is not int or not 1 <= step <= total + 1:
        raise RuntimeError(f"{block} 的进度记录损坏，请检查 {PROGRESS_FILE}。")
    return step


def save_progress(progress: dict, course: str, block: str, next_step: int, total: int) -> None:
    """保存待执行步骤；total + 1 表示最后一步也已经确认完成。"""
    progress["workshops"][f"{course}/{block}"] = {
        "next_step": next_step,
        "total_steps": total,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    # 替换整个文件，避免中途退出留下写了一半的 JSON。
    temporary = PROGRESS_FILE.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(PROGRESS_FILE)
    except OSError as exc:
        raise RuntimeError(f"无法保存进度文件 {PROGRESS_FILE}：{exc}") from exc


def get_structure(block: str) -> dict:
    # block slug 只允许简单 URL 字符，防止把意外字符用作目录名
    if not re.fullmatch(r"[a-z0-9-]+", block):
        raise UnsupportedChallenge("不支持的课程 block 名称。")
    data = json.loads(get_text(f"curriculum/structure/blocks/{block}.json"))
    if not data.get("challengeOrder"):
        raise UnsupportedChallenge("该 block 没有已公布的题目顺序。")
    return data


def fenced_code(section: str) -> dict[str, str]:
    """从 seed / solutions 正文提取 ```js、```html、```css 等代码。"""
    files: dict[str, str] = {}
    pat = re.compile(r"(?ms)^```([^\n`]*)\n(.*?)\n```[ \t]*$")
    aliases = {
        "javascript": "js", "typescript": "ts", "htm": "html", "python": "py",
    }
    for m in pat.finditer(section):
        syntax = m.group(1).strip().lower().split()[0] if m.group(1).strip() else ""
        syntax = aliases.get(syntax, syntax)
        if syntax not in {"html", "css", "js", "jsx", "ts", "tsx", "py"}:
            continue
        code = m.group(2)
        # editable-region 是课程描述性标记，不能输入编辑器
        code = re.sub(r"(?m)^[ \t]*--fcc-editable-region--[ \t]*\n?", "", code)
        code = code.strip("\n") + "\n"
        if syntax in files:
            raise UnsupportedChallenge(f"同一源码部分有多个 {syntax} 文件，无法可靠区分。")
        files[syntax] = code
    return files


def markdown_section(doc: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^# --{re.escape(name)}--[ \t]*\n(.*?)(?=^# --[^\n]+--[ \t]*$|\Z)",
        doc,
    )
    if not match:
        return ""
    return match.group(1)


def parse_code(doc: str, section_name: str) -> dict[str, str]:
    text = markdown_section(doc, section_name)
    if section_name == "seed":
        # --seed-contents-- 与 --seed-config-- 等小节分离
        match = re.search(
            r"(?ms)^## --seed-contents--[ \t]*\n(.*?)(?=^## --[^\n]+--[ \t]*$|\Z)",
            text,
        )
        text = match.group(1) if match else ""
    return fenced_code(text)


def get_solution(block: str, step_slug: str) -> tuple[dict[str, str], int, int]:
    structure = get_structure(block)
    order = structure["challengeOrder"]
    if m := re.fullmatch(r"step-(\d+)", step_slug):
        index = int(m.group(1)) - 1
    elif len(order) == 1:
        index = 0  # 单题实验（有显式 solutions 时）
    else:
        raise UnsupportedChallenge(f"非 step-N 路径，且该 block 有多题：{step_slug}")
    if not 0 <= index < len(order):
        raise UnsupportedChallenge("step 超出官方题目序列。")

    def load_challenge(i: int) -> str:
        challenge_id = order[i]["id"]
        return get_text(
            f"curriculum/challenges/english/blocks/{block}/{challenge_id}.md"
        )

    current_doc = load_challenge(index)
    # 最终一步以及部分特殊步骤含显式答案；优先使用这些答案
    files = parse_code(current_doc, "solutions")
    if not files and index + 1 < len(order) and structure.get("blockLabel") == "workshop":
        # 官方 workshop 约定：下一步的 seed 是本步的标准完成状态
        files = parse_code(load_challenge(index + 1), "seed")
    if not files:
        raise UnsupportedChallenge(
            "课程源码没有可直接使用的答案。可能是 lab、测验或特殊格式；不会猜测提交。"
        )
    return files, index + 1, len(order)



def visible_donation_dialog(page):
    """仅识别 freeCodeCamp 的捐赠弹窗，不误操作测试结果或登录对话框。"""
    try:
        dialogs = page.get_by_role("dialog").filter(
            has_text=re.compile(
                r"Become a Supporter|Help millions of people learn|Support us",
                re.I,
            )
        )
        for index in range(min(dialogs.count(), 4)):
            dialog = dialogs.nth(index)
            if dialog.is_visible():
                return dialog
    except Exception:
        # SPA 页面导航/React 组件卸载的短暂状态；由调用方再次轮询。
        pass
    return None


def dismiss_donation_modal(page, timeout_ms: int = 45000) -> bool:
    """等官方 20 秒动画结束，点击 Ask me later 并核实弹窗消失。"""
    dialog = visible_donation_dialog(page)
    if dialog is None:
        return False

    print("    检测到 freeCodeCamp 捐赠弹窗，等待动画结束后自动关闭……")
    end = time.monotonic() + timeout_ms / 1000
    last_error = None
    while time.monotonic() < end:
        dialog = visible_donation_dialog(page)
        if dialog is None:
            print("    捐赠弹窗已关闭。")
            return True

        try:
            # freeCodeCamp 官方 E2E 测试也使用这个按钮；动画播放时不会显示。
            later = dialog.get_by_role("button", name=re.compile(r"^Ask me later$", re.I))
            if later.count() and later.first.is_visible() and later.first.is_enabled():
                later.first.click(timeout=5000)
                dialog.wait_for(state="hidden", timeout=8000)
                print("    已点击 Ask me later，继续做题。")
                return True
        except Exception as exc:
            last_error = exc
            # 点击遇到过渡动画/重新渲染时再试，不绕过官方的关闭限制。

        page.wait_for_timeout(500)

    hint = f" 最后一次尝试：{type(last_error).__name__}。" if last_error else ""
    raise UnsupportedChallenge(
        "捐赠弹窗超过 45 秒仍无法通过 Ask me later 关闭；停止以保留现场。" + hint
    )


def dismiss_project_preview_modal(page) -> bool:
    """关闭 Workshop 首次展示的项目预览，仅点击该对话框中的 Start coding。"""
    dialogs = page.get_by_role("dialog").filter(
        has_text=re.compile(r"(?:Here's|Here is) a preview of what you will build", re.I)
    )
    for index in range(min(dialogs.count(), 3)):
        dialog = dialogs.nth(index)
        if not dialog.is_visible():
            continue
        start = dialog.get_by_role("button", name=re.compile(r"^Start coding!?$", re.I))
        if start.count() != 1:
            raise UnsupportedChallenge("项目预览已打开，但找不到唯一的 Start coding 按钮。")
        start.click(timeout=8000)
        dialog.wait_for(state="hidden", timeout=10000)
        print("    已关闭项目预览，开始编辑。")
        return True
    return False


def dismiss_known_modals(page) -> None:
    dismiss_donation_modal(page)
    dismiss_project_preview_modal(page)


def wait_for_submission_confirmation(
    page, block: str, previous: str, *, is_final: bool, timeout_ms: int = 85000,
    course: str | None = None,
) -> str:
    """等待提交后离开当前题，避免把单纯点击按钮当成成功。

    非最终步骤：确认同一课程的下一题 URL；最终步骤：确认跳转到课程目录或下一单元。
    如果最终步骤保持在原 URL，不擅自把它算作已完成。
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        dismiss_donation_modal(page)
        try:
            _, next_block, next_step = parse_page_url(page.url)
            same_challenge = next_block == block and next_step == previous
        except UnsupportedChallenge:
            # 课程目录、总结页等 URL 不符合 challenge 格式，也属于导航离开当前题。
            same_challenge = False

        if not same_challenge:
            page.wait_for_timeout(700)
            dismiss_donation_modal(page)
            destination = urlparse(page.url)
            if destination.hostname not in {"www.freecodecamp.org", "freecodecamp.org"}:
                raise UnsupportedChallenge(
                    f"提交后导航到了非 freeCodeCamp 页面：{page.url}；不计入完成数。"
                )
            if destination.path.startswith(("/login", "/signin", "/sign-in")):
                raise UnsupportedChallenge("提交后进入登录页面；请重新登录，不计入完成数。")
            if is_final:
                if not destination.path.startswith("/learn/"):
                    raise UnsupportedChallenge(f"最后一步提交后进入了非课程页面：{page.url}；无法核实完成状态。")
                try:
                    final_course, final_block, _ = parse_page_url(page.url)
                except UnsupportedChallenge:
                    pass  # 课程目录或 Workshop 目录。
                else:
                    if final_block == block or (course is not None and final_course != course):
                        raise UnsupportedChallenge(f"最后一步没有进入课程目录或下一单元：{page.url}；无法核实完成状态。")
                return f"最后一题提交后，页面已导航至：{page.url}"
            next_course, next_block, next_step = parse_page_url(page.url)
            previous_number = re.fullmatch(r"step-(\d+)", previous)
            if (next_block != block or (course is not None and next_course != course)
                    or previous_number is None
                    or next_step != f"step-{int(previous_number.group(1)) + 1}"):
                raise UnsupportedChallenge(f"提交后没有进入预期的下一步：{page.url}；不计入完成数。")
            return f"已进入下一页：{page.url}"
        page.wait_for_timeout(400)

    if is_final:
        raise UnsupportedChallenge(
            "最后一题已尝试提交，但页面始终停在当前 URL，无法核实完成状态。"
            "请检查提交结果及课程进度；脚本不会将其误报为成功。"
        )
    raise UnsupportedChallenge("提交后未跳转至下一题（已等待并处理捐赠弹窗）。")


def choose_file_tab(page, language: str, timeout_ms: int = 45000) -> bool:
    """等待文件标签可用，已展开时保持打开，避免再次点击反而收起。"""
    rx = re.compile(FILE_PATTERNS[language], re.I)
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        dismiss_known_modals(page)
        for role in ("tab", "button"):
            loc = page.get_by_role(role, name=rx)
            visible = [loc.nth(i) for i in range(min(loc.count(), 10)) if loc.nth(i).is_visible()]
            if len(visible) > 1:
                raise UnsupportedChallenge(f"发现多个可见的 {language} 文件标签，无法可靠区分。")
            if not visible or not visible[0].is_enabled():
                continue
            tab = visible[0]
            if tab.get_attribute("aria-expanded") != "true" and tab.get_attribute("aria-selected") != "true":
                tab.click(timeout=8000)
            return True
        page.wait_for_timeout(300)
    return False


def monaco_roots_for_language(page, language: str | None):
    if language is None:
        return page.locator(".monaco-editor")
    # 文件名优先；否则使用 Monaco 容器公开的语言标记。
    roots = page.locator(".monaco-editor").filter(
        has=page.get_by_role("textbox", name=re.compile(FILE_PATTERNS[language], re.I))
    )
    if roots.count():
        return roots
    return page.locator(
        f'.react-monaco-editor-container[data-mode-id="{EDITOR_MODES[language]}"] .monaco-editor'
    )


def editor_diagnostics(page) -> str:
    """仅记录编辑器定位信息（不导出登录 cookie、页面 HTML 或答案）。"""
    locator_names = {
        "official-textbox": page.get_by_role("textbox", name=re.compile("editor content", re.I)),
        "monaco-root": page.locator(".monaco-editor"),
        "monaco-view-lines": page.locator(".monaco-editor .view-lines"),
        "monaco-input": page.locator(".monaco-editor textarea.inputarea"),
        "monaco-contenteditable": page.locator(".monaco-editor [contenteditable='true']"),
        "codemirror-content": page.locator(".cm-editor .cm-content[contenteditable='true']"),
        "generic-code-textbox": page.locator("[role='code'] [role='textbox']"),
        "code-tab": page.get_by_role("tab", name=re.compile(r"^Code$", re.I)),
        "donation-dialog": page.get_by_role("dialog").filter(has_text=re.compile(r"Become a Supporter|Help millions of people learn|Support us", re.I)),
        "ask-later-button": page.get_by_role("button", name=re.compile(r"^Ask me later$", re.I)),
        "project-preview": page.get_by_role("dialog").filter(has_text=re.compile(r"preview of what you will build", re.I)),
        "file-tabs": page.locator(".monaco-editor-tabs button"),
    }
    lines = [
        f"recorded_at: {datetime.now().isoformat(timespec='seconds')}",
        f"url: {page.url.split('?')[0].split('#')[0]}",
        f"title: {page.title()}",
    ]
    for name, loc in locator_names.items():
        try:
            count = loc.count()
            vis = sum(loc.nth(i).is_visible() for i in range(min(5, count)))
            lines.append(f"{name}: total={count}, visible_first_five={vis}")
        except Exception as exc:
            lines.append(f"{name}: error={type(exc).__name__}")
    try:
        lines.append(f"iframes: {len(page.frames) - 1}")
    except Exception:
        pass
    try:
        active = page.evaluate("""() => ({
            element: document.activeElement?.tagName || '',
            className: String(document.activeElement?.className || '').slice(0, 100),
            insideMonaco: Boolean(document.activeElement?.closest?.('.monaco-editor')),
            insideCodeMirror: Boolean(document.activeElement?.closest?.('.cm-editor')),
            readyState: document.readyState
        })""")
        lines.append(f"active_element: {active}")
    except Exception:
        pass
    try:
        labels = page.get_by_role("button").all()
        names = []
        for btn in labels[:30]:
            if btn.is_visible():
                label = btn.get_attribute("aria-label") or btn.inner_text(timeout=700)
                if label:
                    names.append(label.strip()[:60])
        lines.append("visible_buttons: " + " | ".join(names[:20]))
    except Exception:
        pass
    try:
        tabs = page.locator(".monaco-editor-tabs button").all()
        lines.append("file_tab_states: " + " | ".join(
            f"{tab.inner_text(timeout=700).strip()}: expanded={tab.get_attribute('aria-expanded')}"
            for tab in tabs[:10]
        ))
    except Exception:
        pass
    return "\n".join(lines) + "\n"


def wait_for_editable_editor(page, timeout_ms: int = 45000, *, language: str | None = None):
    """定位 Monaco/CodeMirror 编辑器；优先使用 freeCodeCamp 官方选择器。"""
    deadline = time.monotonic() + timeout_ms / 1000
    code_tab_clicked = False
    last_error = None

    while time.monotonic() < deadline:
        dismiss_known_modals(page)
        roots = monaco_roots_for_language(page, language)
        official = (roots.get_by_role("textbox", name=re.compile("editor content", re.I))
                    if language else page.get_by_role("textbox", name=re.compile("editor content", re.I)))
        codemirror = page.locator(".cm-editor .cm-content[contenteditable='true']")
        if language:
            codemirror = codemirror.and_(page.get_by_role("textbox", name=re.compile(FILE_PATTERNS[language], re.I)))
        # 免费课程是 React SPA；networkidle 不一定成立，所以循环等编辑器挂载。
        candidates = [
            ("freeCodeCamp official textbox", official, "focus"),
            ("Monaco textbox", roots.locator("[role='textbox']"), "focus"),
            ("Monaco view-lines", roots.locator(".view-lines"), "click"),
            ("Monaco root", roots, "click"),
            ("CodeMirror", codemirror, "click"),
        ]
        for name, locator, action in candidates:
            try:
                count = locator.count()
                for i in range(min(count, 3)):
                    item = locator.nth(i)
                    if not item.is_visible():
                        continue
                    if action == "focus":
                        item.focus(timeout=1500)
                    else:
                        item.click(timeout=2000)
                    # 必须确保焦点真的落在代码编辑器里；避免误清空整个网页。
                    is_editor_active = page.evaluate("""() => {
                        const el = document.activeElement;
                        return Boolean(el && (el.closest?.('.monaco-editor') ||
                            el.closest?.('.cm-editor') ||
                            (el.getAttribute?.('aria-label') || '').toLowerCase().includes('editor content')));
                    }""")
                    if is_editor_active:
                        return name
            except Exception as exc:
                last_error = exc

        # 有些窗口尺寸下，编辑器被 Code 选项卡隐藏。
        if not code_tab_clicked:
            try:
                tab = page.get_by_role("tab", name=re.compile(r"^Code$", re.I))
                if tab.count() and tab.first.is_visible():
                    tab.first.click(timeout=1800, force=True)
                    code_tab_clicked = True
            except Exception:
                pass
        page.wait_for_timeout(600)

    # 只有在编辑器主区域已经可见、但辅助输入框没有可访问 role 的情况下才尝试直接 focus。
    try:
        root = monaco_roots_for_language(page, language).first
        if root.count() and root.is_visible():
            raw_input = root.locator('textarea.inputarea, [contenteditable="true"]').first
            if raw_input.count():
                raw_input.focus(timeout=2000)
                if page.evaluate("() => Boolean(document.activeElement?.closest?.('.monaco-editor'))"):
                    return 'Monaco input fallback'
    except Exception as exc:
        last_error = exc

    hint = "当前页面可能未加载出编辑器、显示了登录/人机验证页，或 Code 标签页未打开。"
    if last_error:
        hint += f" 最后一次定位错误：{type(last_error).__name__}。"
    target = f" {language} 文件的" if language else ""
    raise UnsupportedChallenge(f"{timeout_ms / 1000:g} 秒内没有找到{target}可编辑的代码区域。" + hint)


def monaco_model_contents(page, replacement: str | None = None) -> str | None:
    """只访问当前编辑器实例，用 Monaco 自身接口读写完整文件。"""
    return page.evaluate("""replacement => {
        const root = document.activeElement?.closest('.monaco-editor');
        if (!root) return null;
        const matches = editor => editor
            && typeof editor.getModel === 'function'
            && typeof editor.getValue === 'function'
            && typeof editor.setValue === 'function'
            && typeof editor.getDomNode === 'function'
            && editor.getDomNode() === root;
        const use = editor => {
            if (replacement !== null) editor.setValue(replacement);
            return editor.getValue();
        };
        // 有些页面公开 Monaco 注册表；freeCodeCamp 的 ESM 版本则由 React 持有实例。
        for (const editor of window.monaco?.editor?.getEditors?.() || []) {
            if (matches(editor)) return use(editor);
        }
        // 只沿当前 DOM 的组件祖先查找 editor/editorRef，不遍历其他应用状态。
        for (let node = root, level = 0; node && level < 8; node = node.parentElement, level++) {
            const key = Object.keys(node).find(key => key.startsWith('__reactFiber$'));
            for (let fiber = node[key], depth = 0; fiber && depth < 50; fiber = fiber.return, depth++) {
                const candidates = [fiber.stateNode?.editor, fiber.memoizedProps?.editorRef?.current];
                // 多文件页面的公共 editorRef 可能指向另一个文件；各组件自身的 ref
                // 才持有该文件实例。只检查这些 ref，仍要求 DOM 根节点精确匹配。
                for (let hook = fiber.memoizedState, index = 0; hook && index < 40; hook = hook.next, index++) {
                    const ref = hook.memoizedState?.current;
                    candidates.push(ref, ref?.monaco?.editor);
                }
                for (const editor of candidates) {
                    if (matches(editor)) return use(editor);
                }
            }
        }
        return null;
    }""", replacement)


def verify_editor_contents(actual: str | None, expected: str) -> None:
    if not isinstance(actual, str):
        raise UnsupportedChallenge("无法读回编辑器内容，停止测试和提交；请检查诊断文件。")
    # Windows 的 Monaco 可能使用 CRLF；除换行编码外，所有空格、括号均须一致。
    actual = actual.replace("\r\n", "\n").replace("\r", "\n")
    expected = expected.replace("\r\n", "\n").replace("\r", "\n")
    if actual != expected:
        raise UnsupportedChallenge(
            f"编辑器内容与参考代码不一致（预期 {len(expected)} 字符，实际 {len(actual)} 字符）；"
            "停止测试和提交，避免多余括号或缺失代码。"
        )


def replace_editor_code(page, code: str) -> str:
    """优先替换完整 Monaco 模型；无实例接口时才使用粘贴并校验。"""
    actual = monaco_model_contents(page, code)
    if actual is not None:
        verify_editor_contents(actual, code)
        # 给 React 的内容变更回调一次更新机会，再次核对，防止加载中的旧状态覆盖。
        page.wait_for_timeout(250)
        verify_editor_contents(monaco_model_contents(page), code)
        return "Monaco 完整文件接口"

    page.keyboard.press("ControlOrMeta+A")
    pasted = page.evaluate("""code => {
        const target = document.activeElement;
        if (!target?.closest?.('.monaco-editor, .cm-editor')) return false;
        const data = new DataTransfer();
        data.setData('text/plain', code);
        const event = new ClipboardEvent('paste', {
            clipboardData: data, bubbles: true, cancelable: true
        });
        target.dispatchEvent(event);
        return event.defaultPrevented;
    }""", code)
    if not pasted:
        raise UnsupportedChallenge("编辑器未接收整段粘贴，停止以避免输入不完整的代码。")

    # 使用页内 copy 事件读回整个选区，不读取或改写用户的系统剪贴板。
    page.wait_for_timeout(150)
    page.keyboard.press("ControlOrMeta+A")
    copied = page.evaluate("""() => {
        const target = document.activeElement;
        if (!target?.closest?.('.monaco-editor, .cm-editor')) return null;
        const data = new DataTransfer();
        const event = new ClipboardEvent('copy', {
            clipboardData: data, bubbles: true, cancelable: true
        });
        target.dispatchEvent(event);
        return event.defaultPrevented ? data.getData('text/plain') : null;
    }""")
    verify_editor_contents(copied, code)
    return "整段粘贴"


def write_code(page, files: dict[str, str]) -> None:
    dismiss_known_modals(page)
    if len(files) > 1:
        print("    等待课程页面和多文件编辑器加载……")
        wait_for_editable_editor(page)
    for language, code in files.items():
        if len(files) > 1 and not choose_file_tab(page, language):
            raise UnsupportedChallenge(
                f"等待后仍找不到 {language} 文件标签；页面可能未加载完成或格式不受支持。"
            )

        editor_type = wait_for_editable_editor(page, language=language if len(files) > 1 else None)
        method = replace_editor_code(page, code)
        print(f"    使用 {editor_type} 定位，通过{method}替换并核对 {language}（{len(code)} 字符）")


def click_visible_button(page, expressions: list[str], timeout_ms: int = 18000) -> str | None:
    """按顺序点击匹配的可见、可用按钮，不点隐藏组件。"""
    until = time.monotonic() + timeout_ms / 1000
    patterns = [re.compile(exp, re.I) for exp in expressions]
    while time.monotonic() < until:
        dismiss_known_modals(page)
        for pat in patterns:
            buttons = page.get_by_role("button", name=pat)
            for i in range(min(buttons.count(), 8)):
                button = buttons.nth(i)
                if button.is_visible() and button.is_enabled():
                    label = button.inner_text(timeout=3000).strip()
                    button.click(timeout=8000)
                    return label
        page.wait_for_timeout(350)
    return None


def save_error_screenshot(page) -> None:
    screenshot = BASE_DIR / "fcc_failed_step.png"
    diagnostic = BASE_DIR / "fcc_editor_diagnostic.txt"
    try:
        page.screenshot(path=str(screenshot), full_page=True, timeout=12000)
        print(f"已保存失败页面截图：{screenshot}")
    except Exception as exc:
        print(f"截图失败：{type(exc).__name__}")
    try:
        diagnostic.write_text(editor_diagnostics(page), encoding="utf-8")
        print(f"已保存页面诊断信息：{diagnostic}")
        print("------ 诊断摘要 ------")
        print(diagnostic.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"保存诊断信息失败：{type(exc).__name__}")


def run(url: str, max_steps: int, skip_login_pause: bool, dry_run: bool) -> None:
    # 先解析本次 Workshop 还剩多少题，再启动浏览器。
    url, is_workshop_url = normalize_start_url(url)
    course, block, step = parse_page_url(url)
    structure = get_structure(block)
    progress = load_progress()
    if is_workshop_url:
        if structure.get("blockLabel") != "workshop":
            raise UnsupportedChallenge("只有 Workshop 支持不含步骤的路径简写；其他编码挑战请提供具体题目网址。")
        total = len(structure["challengeOrder"])
        number = saved_next_step(progress, course, block, total)
        if number == total + 1:
            print(f"本地记录显示 {block} 的 {total} 步已全部确认完成，无需重复提交。")
            print(f"如需重新运行，请指定：{url}")
            return
        step = f"step-{number}"
        url = f"https://www.freecodecamp.org/learn/{course}/{block}/{step}"
        if number > 1:
            print(f"自动恢复本地进度：从第 {number} 步继续。")
    initial_solution, number, total = get_solution(block, step)
    remaining = total - number + 1
    # max_steps=0 表示当前 Workshop 全部剩余步骤，避免固定 10/15 导致漏掉最后一题。
    target = remaining if max_steps == 0 else min(max_steps, remaining)
    print(f"课程：{block} | 当前第 {number}/{total} 步 | 剩余 {remaining} 题")
    print(f"本次计划处理 {target} 题（{'直到本 Workshop 结束' if max_steps == 0 else '按 --max-steps 限制'}）")
    print("参考答案文件：" + ", ".join(initial_solution))
    if dry_run:
        print("\n=== 当前题参考代码预览（未提交） ===")
        for lang, code in initial_solution.items():
            print(f"--- {lang} ---\n{code}")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("未安装 Playwright：请运行 python -m pip install playwright") from exc

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        context.set_default_timeout(15000)
        page = context.pages[0] if context.pages else context.new_page()
        completed = 0
        try:
            # 显式 step-N 覆盖旧的本地起点；首题失败或 Ctrl+C 时也能恢复该起点。
            save_progress(progress, course, block, number, total)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if not skip_login_pause:
                print("\n请在弹出的浏览器中登录 freeCodeCamp（如果已登录可跳过）。")
                input("确认登录后，回到终端按 Enter 开始自动填写：")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

            for offset in range(target):
                current_course, current_block, step_slug = parse_page_url(page.url)
                if current_course != course or current_block != block:
                    raise UnsupportedChallenge("意外离开当前 Workshop，停止操作。")
                code_files, step_num, total_steps = get_solution(block, step_slug)
                if step_num != number + offset:
                    raise UnsupportedChallenge(f"当前页面不是预期的第 {number + offset} 步，停止操作。")
                print(f"\n[{step_num}/{total_steps}] {page.url}")
                if step_num == total_steps:
                    print("    这是最后一步：读取当前题官方 --solutions-- 参考代码。")
                write_code(page, code_files)

                test_btn = click_visible_button(
                    page,
                    [r"^Check Your Code(?:\s*\(|$)", r"^Run the Tests(?:\s*\(|$)"],
                )
                if not test_btn:
                    raise UnsupportedChallenge("没有找到 Check Your Code / Run the Tests 按钮。")
                print(f"    已执行：{test_btn}")

                submit_btn = click_visible_button(
                    page,
                    [
                        r"^Submit and continue(?:\s*\(|$)",
                        r"^Submit and go to next challenge(?:\s*\(|$)",
                        r"^Submit(?:\s*\(|$)",
                        r"^Go to next challenge(?:\s*\(|$)",
                    ],
                    timeout_ms=25000,
                )
                if not submit_btn:
                    raise UnsupportedChallenge("检查代码后没有出现可提交按钮。请查看页面测试结果和诊断文件。")
                print(f"    已点击：{submit_btn}；正在核实完成状态……")
                confirmation = wait_for_submission_confirmation(
                    page, block, step_slug, is_final=(step_num == total_steps), course=course
                )
                completed += 1
                save_progress(progress, course, block, step_num + 1, total_steps)
                print(f"    {confirmation}（本次已确认 {completed} 题；进度已保存）")
                if step_num == total_steps:
                    print("本 Workshop 最后一步已提交并跳转完成。")
                    break
            print(f"\n任务结束：本次已确认完成 {completed}/{target} 题。")
        except Exception as exc:
            save_error_screenshot(page)
            raise RuntimeError(
                f"本次已确认完成 {completed}/{target} 题，自动化已停止：{exc}\n"
                "可用当前待做的 step-N 题目链接重试；路径简写模式可自动读取本地保存的步骤。"
            ) from exc
        finally:
            context.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从指定的 step-N 题目连续完成当前 freeCodeCamp Workshop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='示例：python fcc_workshop_auto.py --url "https://www.freecodecamp.org/learn/javascript-v9/workshop-calculator/step-1" --no-login-pause',
    )
    parser.add_argument("--url", default=START_URL, help="完整的 step-N 题目 URL，指定起点；兼容不含步骤的路径简写（自动续跑）")
    parser.add_argument("--max-steps", type=int, default=0, help="本次最多处理的题数；0（默认）表示完成当前 Workshop 全部剩余题目")
    parser.add_argument("--no-login-pause", action="store_true", help="使用已保存的浏览器登录状态直接执行")
    parser.add_argument("--dry-run", action="store_true", help="只打印参考代码，不打开浏览器、不提交")
    args = parser.parse_args()
    if args.max_steps < 0:
        parser.error("--max-steps 不可为负数；0 表示直到当前 Workshop 结束")
    try:
        run(args.url, args.max_steps, args.no_login_pause, args.dry_run)
    except KeyboardInterrupt:
        print("\n已中断。可用当前待做的 step-N 题目链接重试；路径简写模式可读取本地进度续跑。", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
