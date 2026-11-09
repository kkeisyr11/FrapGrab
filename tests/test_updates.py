import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.updater import AutoUpdater, repository_name, CURRENT_VERSION, release_notes_for_language


class UpdateTests(unittest.TestCase):
    def release(self,payload=b"installer"):
        return {"tag_name":"v99.0.0","assets":[{"name":"Frap_Grab_Setup_99.0.0.exe","size":len(payload),
            "browser_download_url":"https://github.com/owner/app/releases/download/v99.0.0/setup.exe",
            "digest":"sha256:"+hashlib.sha256(payload).hexdigest()}]}
    def test_repository_url_normalization_rejects_unrelated_hosts(self):
        self.assertEqual(repository_name("https://github.com/owner/app.git"),"owner/app")
        with self.assertRaises(ValueError):repository_name("https://other.test/owner/app")
    def test_release_requires_the_matching_installer_and_checksum(self):
        updater=AutoUpdater("owner/app");release=self.release()
        self.assertTrue(updater.release_info(release)["has_update"])
        release["assets"][0]["name"]="unrelated.exe"
        with self.assertRaises(ValueError):updater.release_info(release)
        release=self.release();release["assets"][0]["digest"]=""
        with self.assertRaises(ValueError):updater.release_info(release)
    def test_preview_and_cross_repo_downloads_are_rejected(self):
        updater=AutoUpdater("owner/app");release=self.release();release["prerelease"]=True
        with self.assertRaises(ValueError):updater.release_info(release)
        release=self.release();release["assets"][0]["browser_download_url"]="https://github.com/other/app/releases/download/v99.0.0/setup.exe"
        with self.assertRaises(ValueError):updater.release_info(release)
    def test_download_is_atomic_and_corrupt_payload_cannot_be_installed(self):
        updater=AutoUpdater("owner/app");info=updater.release_info(self.release())
        with tempfile.TemporaryDirectory() as temp,patch("core.updater.CONFIG_DIR",temp):
            with patch.object(updater,"_request",return_value=io.BytesIO(b"installer")):
                out=updater.download(info)
            self.assertEqual(out.read_bytes(),b"installer");out.unlink()
            with patch.object(updater,"_request",return_value=io.BytesIO(b"corrupted")):
                with self.assertRaises(ValueError):updater.download(info)
            self.assertEqual(list((Path(temp)/"updates").iterdir()),[])
    def test_current_release_does_not_require_an_update_asset(self):
        self.assertFalse(AutoUpdater("owner/app").release_info({"tag_name":CURRENT_VERSION})["has_update"])

    def test_changelog_selects_the_interface_language_and_keeps_legacy_notes(self):
        notes = "## English\r\n- New clips\r\n## Polski\r\n- Nowe klipy"
        self.assertEqual(release_notes_for_language(notes, "en"), "- New clips")
        self.assertEqual(release_notes_for_language(notes, "pl"), "- Nowe klipy")
        self.assertEqual(release_notes_for_language("## EN\n- Legacy", "pl"), "- Legacy")
        self.assertEqual(release_notes_for_language("- Legacy", "pl"), "- Legacy")
