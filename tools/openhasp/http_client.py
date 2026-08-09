"""OpenHASP HTTP client for config, pages, file download/upload."""

from typing import Any, ClassVar

import requests

from tools.constants import OPENHASP_HTTP_PORT, OPENHASP_TIMEOUT


class OpenHASPHTTPClient:
    """HTTP client for OpenHASP panel communication.

    Handles GET, POST (multipart upload), config.json parsing,
    pages.jsonl counting, and file management.
    """

    CONFIG_FILES: ClassVar[list[str]] = [
        "config.json",
        "pages.jsonl",
        "boot.cmd",
        "online.cmd",
        "offline.cmd",
    ]

    def __init__(
        self,
        host: str,
        port: int = OPENHASP_HTTP_PORT,
        timeout: int = OPENHASP_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{host}:{port}"

    def get_json(self, path: str) -> dict[str, Any] | None:
        """GET a JSON endpoint and return parsed dict.

        Args:
            path: URL path (e.g. "/config.json").

        Returns:
            Parsed JSON dict or None on failure.
        """
        try:
            resp = requests.get(
                f"{self.base_url}{path}",
                timeout=self.timeout,
                allow_redirects=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return None

    def get_text(self, path: str) -> str | None:
        """GET a text endpoint and return raw string.

        Args:
            path: URL path (e.g. "/boot.cmd").

        Returns:
            Response text or None on failure.
        """
        try:
            resp = requests.get(
                f"{self.base_url}{path}",
                timeout=self.timeout,
                allow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return None

    def upload_file(self, remote_path: str, content: str | bytes) -> bool:
        """Upload a file via POST /edit (multipart).

        Args:
            remote_path: Target filename on the panel.
            content: File content as string or bytes.

        Returns:
            True if upload succeeded ("Upload OK" in response).
        """
        try:
            if isinstance(content, str):
                content = content.encode("utf-8")
            resp = requests.post(
                f"{self.base_url}/edit",
                files={"file": (remote_path, content)},
                timeout=30,
            )
            return resp.status_code == 200 and "Upload OK" in resp.text
        except Exception:
            return False

    def count_objects(self) -> int:
        """Count objects in pages.jsonl.

        Returns:
            Number of JSONL lines with "obj" key.
        """
        text = self.get_text("/pages.jsonl")
        if text is None:
            return 0
        count = 0
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if '"obj"' in line:
                count += 1
        return count

    def count_pages(self) -> int:
        """Count unique pages in pages.jsonl.

        Returns:
            Number of unique page IDs.
        """
        text = self.get_text("/pages.jsonl")
        if text is None:
            return 0
        import json

        pages: set[int] = set()
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                obj = json.loads(line)
                if "page" in obj:
                    pages.add(obj["page"])
            except Exception:
                pass
        return len(pages)

    def is_reachable(self) -> bool:
        """Quick connectivity check.

        Returns:
            True if GET /config.json returns HTTP 200.
        """
        try:
            resp = requests.get(
                f"{self.base_url}/config.json",
                timeout=self.timeout,
                allow_redirects=False,
            )
            return resp.status_code == 200
        except Exception:
            return False
