import os
import unittest


class BrowserExtensionDefaultsTests(unittest.TestCase):
    def _read_file(self, rel_path: str) -> str:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, rel_path)
        self.assertTrue(os.path.isfile(path), f"missing file: {rel_path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_background_defaults_include_pairing_state(self):
        background = self._read_file("browser_extension/background.js")
        self.assertIn('const DEFAULT_TOKEN = "";', background)
        self.assertIn("paired: false", background)
        self.assertIn('extension_id: ""', background)
        self.assertIn("archive_root: \"\"", background)
        self.assertIn('archive_label: "本地知识库"', background)

    def test_background_has_pairing_and_config_endpoints(self):
        background = self._read_file("browser_extension/background.js")
        self.assertIn("/v1/pairing/info", background)
        self.assertIn("/v1/pairing/claim", background)
        self.assertIn("/v1/config", background)
        self.assertIn("/v1/window/show", background)
        self.assertIn('message.type === "pairing_scan"', background)
        self.assertIn('message.type === "pairing_claim"', background)
        self.assertIn('message.type === "runtime_config_get"', background)
        self.assertIn('message.type === "runtime_config_patch"', background)

    def test_dashboard_defaults_include_paired_flag(self):
        dashboard = self._read_file("browser_extension/dashboard.js")
        self.assertIn("paired: false", dashboard)
        self.assertIn("let wizardStep = 1;", dashboard)
        self.assertIn("async function showWizard", dashboard)
        self.assertIn('type: "pairing_scan"', dashboard)
        self.assertIn('type: "pairing_claim"', dashboard)
        self.assertIn('type: "runtime_config_patch"', dashboard)
        self.assertIn("function applyArchiveLabel", dashboard)

    def test_dashboard_html_contains_wizard_and_offline_panels(self):
        dashboard_html = self._read_file("browser_extension/dashboard.html")
        self.assertIn('id="wizardPanel"', dashboard_html)
        self.assertIn('id="wizardArchiveRoot"', dashboard_html)
        self.assertIn('id="offlinePanel"', dashboard_html)
        self.assertIn("保存到本地资料库", dashboard_html)

    def test_dashboard_add_task_forwards_source_and_options(self):
        background = self._read_file("browser_extension/background.js")
        self.assertIn("sendBulk(items, {", background)
        self.assertIn("source_type: p.source_type", background)
        self.assertIn("import_mode: p.import_mode", background)
        self.assertIn("limit: p.limit", background)
        self.assertIn("order: p.order", background)

    def test_dashboard_current_add_passes_tab_id(self):
        dashboard = self._read_file("browser_extension/dashboard.js")
        self.assertIn("const tabId = tab && Number.isFinite(tab.id) ? tab.id : null;", dashboard)
        self.assertIn("tab_id: tabId,", dashboard)

    def test_dashboard_table_actions_use_event_delegation(self):
        dashboard = self._read_file("browser_extension/dashboard.js")
        self.assertIn('ui.taskTableBody.addEventListener("click", onTaskTableClick)', dashboard)
        self.assertIn('ui.taskTableBody.addEventListener("change", onTaskTableChange)', dashboard)
        self.assertIn('data-action="delete-task"', dashboard)
        self.assertIn('data-action="toggle-shape"', dashboard)

    def test_manifest_contains_scripting_permission(self):
        manifest = self._read_file("browser_extension/manifest.json")
        self.assertIn('"permissions": ["storage", "alarms", "activeTab", "tabs", "clipboardWrite", "sidePanel", "scripting"]', manifest)

    def test_background_prefetch_path_present(self):
        background = self._read_file("browser_extension/background.js")
        self.assertIn('"/v1/tasks/add_prefetched"', background)
        self.assertIn("chrome.scripting.executeScript", background)
        self.assertIn("resolveTabIdForSend", background)
        self.assertIn("shouldUseAddTaskSinglePrefetch", background)
        self.assertIn("message.tab_id", background)
        self.assertIn("sender.tab.id", background)
        self.assertIn('sendSingle(message.url || "", tabId)', background)
        self.assertIn('sendSingle(String(urls[0] || "").trim(), tabId, {', background)

    def test_popup_is_reduced_to_dashboard_entry(self):
        popup = self._read_file("browser_extension/popup.js")
        popup_html = self._read_file("browser_extension/popup.html")
        self.assertIn('chrome.tabs.create({ url: chrome.runtime.getURL("dashboard.html") });', popup)
        self.assertIn('type: "show_diagnostic_window"', popup)
        self.assertIn('id="openDashboardBtn"', popup_html)
        self.assertIn('id="showWindowBtn"', popup_html)


if __name__ == "__main__":
    unittest.main()
