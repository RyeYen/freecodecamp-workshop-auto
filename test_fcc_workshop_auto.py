"""离线回归测试：模拟导航，不连接账号、不提交真实课程。"""

import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch

import fcc_workshop_auto as fcc


ROOT = "https://www.freecodecamp.org/learn/javascript-v9/workshop-greeting-bot"
COURSE = "javascript-v9"
BLOCK = "workshop-greeting-bot"


class FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.visited = []

    def goto(self, url, **kwargs):
        self.url = url
        self.visited.append(url)

    def wait_for_timeout(self, milliseconds):
        pass


class FakeBrowser:
    def __init__(self):
        self.chromium = self
        self.pages = [FakePage()]
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def launch_persistent_context(self, **kwargs):
        return self

    def set_default_timeout(self, milliseconds):
        pass

    def close(self):
        self.closed = True


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.progress_file = Path(folder) / ".fcc_progress.json"
        self.stack.enter_context(patch.object(fcc, "PROGRESS_FILE", self.progress_file))
        self.output = self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.browser = FakeBrowser()
        self.page = self.browser.pages[0]
        self.launch = Mock(return_value=self.browser)
        parent = types.ModuleType("playwright")
        parent.__path__ = []
        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.sync_playwright = self.launch
        self.stack.enter_context(patch.dict(sys.modules, {
            "playwright": parent, "playwright.sync_api": sync_api,
        }))
        self.stack.enter_context(patch.object(fcc, "get_structure", return_value={
            "blockLabel": "workshop", "challengeOrder": [{"id": str(i)} for i in range(3)],
        }))
        self.solution = self.stack.enter_context(patch.object(
            fcc, "get_solution",
            side_effect=lambda block, step: ({"js": "console.log('test');\n"}, int(step[5:]), 3),
        ))
        self.write = self.stack.enter_context(patch.object(fcc, "write_code"))
        self.stack.enter_context(patch.object(fcc, "dismiss_donation_modal", return_value=False))
        self.diagnostic = self.stack.enter_context(patch.object(fcc, "save_error_screenshot"))
        self.click = self.stack.enter_context(patch.object(
            fcc, "click_visible_button", side_effect=self.click_button,
        ))

    def click_button(self, page, expressions, **kwargs):
        if expressions[0].startswith("^Check"):
            return "Check Your Code"
        number = int(fcc.parse_page_url(page.url)[2][5:])
        page.url = f"{ROOT}/step-{number + 1}" if number < 3 else ROOT.rsplit("/", 1)[0]
        return "Submit and continue"

    def saved_step(self):
        return fcc.load_progress()["workshops"][f"{COURSE}/{BLOCK}"]["next_step"]

    def test_directory_and_explicit_step_urls(self):
        for value in (ROOT, ROOT + "/", ROOT + "/?test=1#code"):
            self.assertEqual(fcc.normalize_start_url(value), (ROOT + "/step-1", True))
        self.assertEqual(fcc.normalize_start_url(ROOT + "/step-2?test=1"), (ROOT + "/step-2", False))
        for invalid in (ROOT.replace("https:", "file:"), ROOT.replace("freecodecamp.org", "example.org"), ROOT + "/../step-1"):
            with self.subTest(invalid=invalid), self.assertRaises(fcc.UnsupportedChallenge):
                fcc.normalize_start_url(invalid)

    def test_one_command_finishes_and_completed_directory_does_not_repeat(self):
        fcc.run(ROOT, 0, True, False)
        self.assertEqual(self.write.call_count, 3)
        self.assertEqual(self.saved_step(), 4)
        self.assertTrue(self.browser.closed)
        fcc.run(ROOT, 0, True, False)
        self.assertEqual(self.launch.call_count, 1)
        self.assertEqual(self.write.call_count, 3)

    def test_max_steps_then_same_directory_resumes(self):
        fcc.run(ROOT, 1, True, False)
        self.assertEqual(self.saved_step(), 2)
        fcc.run(ROOT, 0, True, False)
        self.assertEqual(self.page.visited, [ROOT + "/step-1", ROOT + "/step-2"])
        self.assertEqual(self.write.call_count, 3)
        self.assertEqual(self.saved_step(), 4)

    def test_failure_preserves_unconfirmed_step_then_resumes(self):
        self.write.side_effect = [None, RuntimeError("simulated failure")]
        with self.assertRaisesRegex(RuntimeError, "simulated failure"):
            fcc.run(ROOT, 0, True, False)
        self.assertEqual(self.saved_step(), 2)
        self.diagnostic.assert_called_once()
        self.assertTrue(self.browser.closed)
        self.write.side_effect = None
        fcc.run(ROOT, 0, True, False)
        self.assertEqual(self.page.visited[-1], ROOT + "/step-2")
        self.assertEqual(self.saved_step(), 4)

    def test_explicit_step_overrides_saved_progress(self):
        fcc.run(ROOT, 0, True, False)
        fcc.run(ROOT + "/step-1", 1, True, False)
        self.assertEqual(self.page.visited[-1], ROOT + "/step-1")
        self.assertEqual(self.saved_step(), 2)

    def test_dry_run_does_not_write_progress_or_launch_browser(self):
        fcc.run(ROOT, 0, True, True)
        self.assertFalse(self.progress_file.exists())
        self.launch.assert_not_called()
        fcc.run(ROOT, 1, True, False)
        saved = self.progress_file.read_bytes()
        self.launch.reset_mock()
        fcc.run(ROOT, 0, True, True)
        self.assertEqual(self.progress_file.read_bytes(), saved)
        self.launch.assert_not_called()
        self.assertIn("2/3", self.output.getvalue())

    def test_unconfirmed_final_submission_is_not_saved_as_complete(self):
        self.click.side_effect = lambda *args, **kwargs: "Submit"
        with patch.object(fcc.time, "monotonic", side_effect=[0, 86]):
            with self.assertRaisesRegex(RuntimeError, "无法核实完成状态"):
                fcc.run(ROOT + "/step-3", 0, True, False)
        self.assertEqual(self.saved_step(), 3)

    def test_unexpected_navigation_is_not_counted(self):
        destinations = [ROOT + "/step-3", ROOT + "/step-1", ROOT + "/../other/step-1",
                        ROOT.rsplit("/", 1)[0], "https://www.freecodecamp.org/signin",
                        "https://example.org/learn/other/step-2"]
        for destination in destinations:
            with self.subTest(destination=destination):
                self.page.url = destination
                with self.assertRaises(fcc.UnsupportedChallenge):
                    fcc.wait_for_submission_confirmation(self.page, BLOCK, "step-1", is_final=False, course=COURSE, timeout_ms=1)

    def test_corrupt_or_outdated_progress(self):
        self.progress_file.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "无法读取进度文件"):
            fcc.load_progress()
        self.progress_file.unlink()
        data = fcc.load_progress()
        fcc.save_progress(data, COURSE, BLOCK, 2, 3)
        self.assertEqual(fcc.saved_next_step(fcc.load_progress(), COURSE, BLOCK, 3), 2)
        self.assertEqual(fcc.saved_next_step(fcc.load_progress(), "different-course", BLOCK, 3), 1)
        self.assertEqual(fcc.saved_next_step(fcc.load_progress(), COURSE, BLOCK, 4), 1)
        data["workshops"][f"{COURSE}/{BLOCK}"]["next_step"] = 99
        with self.assertRaisesRegex(RuntimeError, "进度记录损坏"):
            fcc.saved_next_step(data, COURSE, BLOCK, 3)

    def test_cli_reports_failure_and_interrupt_exit_codes(self):
        with patch.object(sys, "argv", ["fcc_workshop_auto.py"]), redirect_stderr(io.StringIO()):
            for error, code in ((RuntimeError("failure"), 1), (KeyboardInterrupt(), 130)):
                with patch.object(fcc, "run", side_effect=error), self.assertRaises(SystemExit) as result:
                    fcc.main()
                self.assertEqual(result.exception.code, code)


class CachedCurriculumTests(unittest.TestCase):
    def test_every_cached_workshop_step_has_solution_including_last(self):
        # 测试缓存存在时才核查；禁止测试通过网络补齐缺失的课程数据。
        structure_dir = fcc.CACHE_DIR / "curriculum/structure/blocks"
        structures = sorted(structure_dir.glob("*.json"))
        if not structures:
            self.skipTest("没有本地课程缓存")
        read_cached = lambda relative: (fcc.CACHE_DIR / relative).read_text(encoding="utf-8")
        with patch.object(fcc, "get_text", side_effect=read_cached):
            for path in structures:
                structure = json.loads(path.read_text(encoding="utf-8"))
                if structure.get("blockLabel") != "workshop":
                    continue
                order = structure["challengeOrder"]
                for number in range(1, len(order) + 1):
                    # 用户可能只运行过前几题；只核查缓存足够的步骤，绝不联网补齐。
                    current = fcc.CACHE_DIR / f"curriculum/challenges/english/blocks/{path.stem}/{order[number - 1]['id']}.md"
                    if not current.exists():
                        continue
                    if not fcc.parse_code(current.read_text(encoding="utf-8"), "solutions"):
                        if number == len(order):
                            continue
                        following = current.with_name(f"{order[number]['id']}.md")
                        if not following.exists():
                            continue
                    with self.subTest(block=path.stem, step=number):
                        files, actual, total = fcc.get_solution(path.stem, f"step-{number}")
                        self.assertEqual(actual, number)
                        self.assertEqual(total, len(structure["challengeOrder"]))
                        self.assertTrue(files)
                        self.assertTrue(all("--fcc-editable-region--" not in code for code in files.values()))


class MultiFileEditorTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock()
        self.modals = patch.object(fcc, "dismiss_known_modals")
        self.modals.start()
        self.addCleanup(self.modals.stop)

    def file_buttons(self, count=1):
        buttons = Mock()
        buttons.count.return_value = count
        button = buttons.nth.return_value
        button.is_visible.return_value = True
        button.is_enabled.return_value = True
        button.get_attribute.return_value = None
        self.page.get_by_role.return_value = buttons
        return buttons, button

    def test_waits_for_file_tabs_instead_of_failing_on_empty_page(self):
        buttons, button = self.file_buttons()
        buttons.count.side_effect = [0, 0, 0, 1]
        with patch.object(fcc.time, "monotonic", side_effect=[0, 0, 0.3]):
            self.assertTrue(fcc.choose_file_tab(self.page, "html"))
        self.page.wait_for_timeout.assert_called_once_with(300)
        button.click.assert_called_once()

    def test_already_expanded_file_is_not_toggled_closed(self):
        for attributes in ({"aria-expanded": "true"}, {"aria-selected": "true"}):
            with self.subTest(attributes=attributes):
                _, button = self.file_buttons()
                button.get_attribute.side_effect = attributes.get
                self.assertTrue(fcc.choose_file_tab(self.page, "css"))
                button.click.assert_not_called()

    def test_ambiguous_file_tabs_stop_without_clicking(self):
        _, button = self.file_buttons(count=2)
        with self.assertRaisesRegex(fcc.UnsupportedChallenge, "多个可见的 html 文件标签"):
            fcc.choose_file_tab(self.page, "html")
        button.click.assert_not_called()

    def test_each_file_gets_its_own_editor(self):
        files = {"html": "<h1>Todo</h1>\n", "css": "h1 {color: red}\n", "js": "const taskForm = {};\n"}
        with patch.object(fcc, "wait_for_editable_editor", return_value="test editor") as focus, \
                patch.object(fcc, "choose_file_tab", return_value=True), \
                patch.object(fcc, "replace_editor_code", return_value="test API") as replace, \
                redirect_stdout(io.StringIO()):
            fcc.write_code(self.page, files)
        self.assertEqual(focus.call_args_list, [unittest.mock.call(self.page)] + [
            unittest.mock.call(self.page, language=language) for language in files
        ])
        self.assertEqual(replace.call_args_list, [
            unittest.mock.call(self.page, code, language=language) for language, code in files.items()
        ])

    def test_missing_file_stops_before_writing_to_another_editor(self):
        with patch.object(fcc, "wait_for_editable_editor"), \
                patch.object(fcc, "choose_file_tab", return_value=False), \
                patch.object(fcc, "replace_editor_code") as replace, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(fcc.UnsupportedChallenge, "找不到 html 文件标签"):
                fcc.write_code(self.page, {"html": "<h1/>\n", "js": "let x;\n"})
        replace.assert_not_called()

    def test_project_preview_uses_start_coding_inside_its_dialog(self):
        dialogs = self.page.get_by_role.return_value.filter.return_value
        dialogs.count.return_value = 1
        dialog = dialogs.nth.return_value
        dialog.is_visible.return_value = True
        start = dialog.get_by_role.return_value
        start.count.return_value = 1
        with redirect_stdout(io.StringIO()):
            self.assertTrue(fcc.dismiss_project_preview_modal(self.page))
        start.click.assert_called_once()
        dialog.wait_for.assert_called_once_with(state="hidden", timeout=10000)


class EditorReplacementTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock()
        self.code = "function addTwoAndSeven() {  \n  \n}\n"
        self.handle = self.page.evaluate_handle.return_value
        self.root = self.handle.as_element.return_value

    def test_paste_and_readback_preserve_code_with_crlf(self):
        self.handle.as_element.return_value = None
        self.page.evaluate.side_effect = [True, self.code.replace("\n", "\r\n")]
        fcc.replace_editor_code(self.page, self.code)
        self.page.keyboard.insert_text.assert_not_called()
        self.assertEqual(self.page.keyboard.press.call_args_list, [
            unittest.mock.call("ControlOrMeta+A"), unittest.mock.call("ControlOrMeta+A"),
        ])
        self.assertIn("ClipboardEvent('paste'", self.page.evaluate.call_args_list[0].args[0])
        self.assertEqual(self.page.evaluate.call_args_list[0].args[1], self.code)
        self.assertIn("ClipboardEvent('copy'", self.page.evaluate.call_args_list[1].args[0])

    def test_monaco_model_replaces_entire_file_without_keyboard_or_clipboard(self):
        self.root.evaluate.side_effect = [self.code, self.code]
        self.assertEqual(fcc.replace_editor_code(self.page, self.code), "Monaco 完整文件接口")
        self.page.keyboard.press.assert_not_called()
        self.page.keyboard.insert_text.assert_not_called()
        self.assertEqual(self.root.evaluate.call_args_list[0].args[1], self.code)
        self.assertIsNone(self.root.evaluate.call_args_list[1].args[1])
        self.handle.dispose.assert_called_once()

    def test_focus_switch_to_js_does_not_change_html_verification_target(self):
        expected = "<h1>Todo</h1>\n"
        self.root.evaluate.side_effect = [expected, expected]
        self.page.evaluate.return_value = "const taskForm = {};\n"
        self.assertEqual(fcc.replace_editor_code(self.page, expected), "Monaco 完整文件接口")
        self.page.evaluate.assert_not_called()
        self.handle.dispose.assert_called_once()

    def test_named_file_is_bound_before_writing_even_if_focus_is_elsewhere(self):
        roots = Mock()
        roots.count.return_value = 1
        roots.nth.return_value.is_visible.return_value = True
        handle = roots.nth.return_value.element_handle.return_value
        root = handle.as_element.return_value
        root.evaluate.side_effect = [self.code, self.code]
        with patch.object(fcc, "monaco_roots_for_language", return_value=roots):
            self.assertTrue(fcc.replace_monaco_code(self.page, self.code, language="html"))
        self.page.evaluate_handle.assert_not_called()
        self.page.evaluate.assert_not_called()
        handle.dispose.assert_called_once()

    def test_monaco_model_rejects_late_overwrite_by_old_code(self):
        self.root.evaluate.side_effect = [self.code, self.code + "    \n}\n"]
        with self.assertRaisesRegex(fcc.UnsupportedChallenge, "内容与参考代码不一致"):
            fcc.replace_editor_code(self.page, self.code)
        self.page.keyboard.insert_text.assert_not_called()
        self.handle.dispose.assert_called_once()

    def test_extra_brace_or_changed_whitespace_stops_before_testing(self):
        for actual in (self.code + "}", self.code.replace("  \n", "    \n"), self.code[:-2]):
            with self.subTest(actual=actual):
                self.handle.as_element.return_value = None
                self.page.evaluate.side_effect = [True, actual]
                with self.assertRaisesRegex(fcc.UnsupportedChallenge, "内容与参考代码不一致"):
                    fcc.replace_editor_code(self.page, self.code)

    def test_unhandled_paste_or_copy_is_rejected(self):
        self.handle.as_element.return_value = None
        for responses, message in (([False], "未接收整段粘贴"), ([True, None], "无法读回编辑器内容")):
            with self.subTest(responses=responses):
                self.page.evaluate.side_effect = responses
                with self.assertRaisesRegex(fcc.UnsupportedChallenge, message):
                    fcc.replace_editor_code(self.page, self.code)


if __name__ == "__main__":
    unittest.main()
