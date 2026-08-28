"""Where tenant-uploaded media lives on disk.

Kept in its own module because the correct answer differs between a laptop and
a container. On Render only the mounted disk survives a deploy, and that disk
mounts over ``DATA_FOLDER`` (``/app/data``). Media written anywhere else is
deleted the next time we ship, while the database rows and campaign records
that reference it survive - so the app keeps serving URLs to files that no
longer exist.
"""

import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Media uploaded before this moved onto the disk is baked into the image here
# and is still referenced by live bots. Reads fall back to it so those
# attachments keep resolving; nothing new is ever written here.
LEGACY_MEDIA_FOLDER = os.path.join(_ROOT, "media_uploads")

# Default deliberately sits *inside* the data folder: Render allows exactly one
# disk per service, so media has to share the volume that knowledge PDFs use.
MEDIA_FOLDER = os.path.abspath(
    os.getenv("MEDIA_FOLDER") or os.path.join(_ROOT, "data", "media_uploads")
)
