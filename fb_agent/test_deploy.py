"""배포(Streamlit Community Cloud) 준비 점검: 저장소 루트에서 실행돼도 테마·로고·자료를 찾는지."""
import testenv  # noqa: F401  (FB_MASTER_DIR=testdata/master 고정)
import ast
import unittest
from pathlib import Path

from config import APP_DIR, ASSETS

ROOT = APP_DIR.parent


class DeployReady(unittest.TestCase):
    def test_root_streamlit_config_matches_app_config(self):
        """배포 환경은 저장소 루트에서 실행해 루트의 .streamlit/config.toml 만 읽는다. 앱 폴더의 설정과 같게 유지한다."""
        root, app = ROOT / ".streamlit" / "config.toml", APP_DIR / ".streamlit" / "config.toml"
        self.assertTrue(root.exists(), "루트 .streamlit/config.toml 이 없으면 배포 화면의 테마가 기본값이 된다")
        self.assertEqual(root.read_text(encoding="utf-8"), app.read_text(encoding="utf-8"), "fb_agent/.streamlit/config.toml 을 바꿨다면 루트에도 같은 내용으로 복사하세요")

    def test_assets_exist(self):
        for name in ("logo.svg", "logo-mark.svg", "logo-on-light.svg"):
            self.assertTrue((ASSETS / name).exists(), name)

    def test_no_cwd_relative_asset_paths(self):
        """'assets/…' 같은 현재 폴더 기준 경로는 저장소 루트에서 실행하면 깨진다 (config.ASSETS 를 쓴다)."""
        bad = [p.name for p in APP_DIR.glob("*.py") if not p.name.startswith("test_") and ('"assets/' in p.read_text(encoding="utf-8") or "'assets/" in p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [])

    def test_source_parses_on_python_3_12(self):
        """배포 환경 파이썬이 3.12~3.13 일 수 있어, 3.12 문법으로도 읽히는지 본다."""
        for p in [*APP_DIR.glob("*.py"), *(APP_DIR / "views").glob("*.py")]:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p), feature_version=(3, 12))

    def test_requirements_list_runtime_packages(self):
        req = (APP_DIR / "requirements.txt").read_text(encoding="utf-8").lower()
        for pkg in ("streamlit", "pandas", "openpyxl"):
            self.assertIn(pkg, req)


if __name__ == "__main__":
    unittest.main()
