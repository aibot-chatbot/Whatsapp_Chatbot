"""Where uploaded media is written decides whether it survives a deploy.

Render attaches exactly one disk, mounted over the data folder. Anything
written outside that mount lives on the container filesystem and is gone on the
next deploy - while the database rows and campaigns holding its /media/ URL
survive, so the app keeps serving links to files that no longer exist. These
are path invariants, not behaviour tests: they fail the moment someone points
media back at a repo-relative directory.
"""

import os

from app.services.knowledge_service import DATA_FOLDER
from app.storage_paths import LEGACY_MEDIA_FOLDER, MEDIA_FOLDER


def test_media_folder_lives_inside_the_mounted_disk():
    assert os.path.commonpath([MEDIA_FOLDER, DATA_FOLDER]) == DATA_FOLDER


def test_the_legacy_folder_is_not_on_the_disk():
    """It is the pre-move location baked into the image. Reads still fall back
    to it so existing attachments resolve, but nothing may be written there."""
    assert os.path.commonpath([LEGACY_MEDIA_FOLDER, DATA_FOLDER]) != DATA_FOLDER


def test_media_folder_is_overridable_for_object_storage_later(monkeypatch):
    monkeypatch.setenv("MEDIA_FOLDER", os.path.join(os.sep, "mnt", "elsewhere"))
    import importlib

    import app.storage_paths as storage_paths

    reloaded = importlib.reload(storage_paths)
    try:
        assert reloaded.MEDIA_FOLDER == os.path.abspath(
            os.path.join(os.sep, "mnt", "elsewhere")
        )
    finally:
        monkeypatch.delenv("MEDIA_FOLDER", raising=False)
        importlib.reload(storage_paths)
