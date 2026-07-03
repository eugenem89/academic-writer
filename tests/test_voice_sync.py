"""Tests for voice-sync.sh utility."""

import subprocess
from pathlib import Path
import os, shutil, tempfile

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "src" / "skills" / "voice" / "voice-sync.sh"


def test_script_exists_and_executable():
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)


def _write_profile_with_author_key(tmp_path, author_key="test-writer"):
    profile_dir = tmp_path / ".academic-helper"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "profile.md").write_text(
        f"# Academic Writer Profile\n\n---\nauthor_key: {author_key}\n---\n"
    )


def test_no_op_when_ck_missing(tmp_path):
    env = os.environ.copy()
    # Force ck-missing without also breaking grep/sed/tr (needed for author_key resolution).
    env["PATH"] = "/usr/bin:/bin"
    env["VOICE_PROJECT_ROOT"] = str(tmp_path)
    (tmp_path / "AUTHOR_VOICE.md").write_text("# stub\n")
    _write_profile_with_author_key(tmp_path)
    r = subprocess.run([str(SCRIPT), "push"], env=env, capture_output=True, text=True)
    assert r.returncode == 0
    assert "ck not available" in (r.stdout + r.stderr).lower()


def test_status_reports_no_id_cache(tmp_path):
    env = os.environ.copy()
    env["VOICE_PROJECT_ROOT"] = str(tmp_path)
    (tmp_path / ".voice").mkdir()
    _write_profile_with_author_key(tmp_path)
    r = subprocess.run([str(SCRIPT), "status"], env=env, capture_output=True, text=True)
    assert "no cached candlekeep id" in (r.stdout + r.stderr).lower()


def test_fails_loudly_when_author_key_missing(tmp_path):
    env = os.environ.copy()
    env["VOICE_PROJECT_ROOT"] = str(tmp_path)
    # No .academic-helper/profile.md, no book.yaml, no VOICE_WRITER_NAME override.
    r = subprocess.run([str(SCRIPT), "status"], env=env, capture_output=True, text=True)
    assert r.returncode == 1
    assert "author_key not found" in (r.stdout + r.stderr).lower()
    assert "<unknown>" not in (r.stdout + r.stderr).lower()
