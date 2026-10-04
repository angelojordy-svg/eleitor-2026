from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

USER_AGENT = "eleitor-cli/0.1 (consulta local; projeto de estudo)"
DEFAULT_MIN_INTERVAL = 0.15


class TTSError(RuntimeError):
    pass


class NotFound(TTSError):
    pass


class RateLimited(TTSError):
    pass


def default_cache_dir() -> Path:
    override = os.environ.get("ELEITOR_CACHE_DIR")
    if override:
        return Path(override)
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if root:
        return Path(root) / "eleitor" / "cache"
    return Path.home() / ".cache" / "eleitor"


class CachedClient:
    def __init__(
        self,
        cache_dir: Path | str | None = None,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        timeout: float = 20.0,
        workers: int = 4,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.workers = workers
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CachedClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _entry_path(self, url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _load_entry(self, url: str) -> dict[str, Any] | None:
        path = self._entry_path(url)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if entry.get("url") != url:
            return None
        return entry

    def _save_entry(self, entry: dict[str, Any]) -> None:
        path = self._entry_path(entry["url"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._last_request + self.min_interval - now
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def get_json(self, url: str, ttl: float = 0.0, allow_404: bool = False) -> Any | None:
        entry = self._load_entry(url)
        now = time.time()
        if entry is not None:
            age = now - float(entry.get("fetched_at", 0.0))
            if ttl > 0 and age < ttl:
                if entry.get("status") == 404:
                    if allow_404:
                        return None
                    raise NotFound(url)
                return entry.get("body")

        headers: dict[str, str] = {}
        if entry is not None:
            etag = entry.get("etag")
            last_modified = entry.get("last_modified")
            if etag:
                headers["If-None-Match"] = str(etag)
            if last_modified:
                headers["If-Modified-Since"] = str(last_modified)

        self._throttle()
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(1.0 * (attempt + 1))
                continue

            if response.status_code == 304 and entry is not None:
                entry["fetched_at"] = now
                self._save_entry(entry)
                return entry.get("body")

            if response.status_code == 404:
                self._save_entry({"url": url, "status": 404, "fetched_at": now})
                if allow_404:
                    return None
                raise NotFound(f"404: {url}")

            if response.status_code in (403, 429):
                raise RateLimited(
                    f"HTTP {response.status_code} em {url}. "
                    "Possível bloqueio temporário por excesso de requisições ou 404s. Aguarde alguns minutos."
                )

            if response.status_code >= 500:
                last_exc = TTSError(f"HTTP {response.status_code} em {url}")
                time.sleep(1.0 * (attempt + 1))
                continue

            response.raise_for_status()
            body = response.json()
            self._save_entry(
                {
                    "url": url,
                    "status": 200,
                    "fetched_at": now,
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "body": body,
                }
            )
            return body

        raise TTSError(f"falha ao acessar {url}: {last_exc}")

    def get_bytes(self, url: str, ttl: float = 0.0, allow_404: bool = False) -> bytes | None:
        entry = self._load_entry(url)
        now = time.time()
        if entry is not None and ttl > 0:
            age = now - float(entry.get("fetched_at", 0.0))
            if age < ttl:
                if entry.get("status") == 404:
                    if allow_404:
                        return None
                    raise NotFound(url)
                if entry.get("body_b64") is not None:
                    import base64

                    return base64.b64decode(entry["body_b64"])

        self._throttle()
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise TTSError(f"falha de rede ao acessar {url}: {exc}") from exc

        if response.status_code == 404:
            self._save_entry({"url": url, "status": 404, "fetched_at": now})
            if allow_404:
                return None
            raise NotFound(f"404: {url}")
        if response.status_code in (403, 429):
            raise RateLimited(
                f"HTTP {response.status_code} em {url}. "
                "Possível bloqueio temporário por excesso de requisições ou 404s. Aguarde alguns minutos."
            )
        response.raise_for_status()
        import base64

        body = response.content
        self._save_entry(
            {
                "url": url,
                "status": 200,
                "fetched_at": now,
                "body_b64": base64.b64encode(body).decode("ascii"),
            }
        )
        return body

    def get_urls(self, urls: list[str], ttl: float = 0.0, allow_404: bool = True) -> dict[str, Any | None]:
        results: dict[str, Any | None] = {}

        def fetch(url: str) -> tuple[str, Any | None, Exception | None]:
            try:
                return url, self.get_json(url, ttl=ttl, allow_404=allow_404), None
            except Exception as exc:
                return url, None, exc

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for url, body, error in pool.map(fetch, urls):
                if error is not None:
                    raise error
                results[url] = body
        return results

    def get_urls_bytes(self, urls: list[str], allow_404: bool = True, workers: int = 6) -> dict[str, bytes | None]:
        results: dict[str, bytes | None] = {}

        def fetch(url: str) -> tuple[str, bytes | None, Exception | None]:
            try:
                return url, self.get_bytes(url, allow_404=allow_404), None
            except Exception as exc:
                return url, None, exc

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for url, body, error in pool.map(fetch, urls):
                if error is not None:
                    raise error
                results[url] = body
        return results

    def clear_cache(self) -> int:
        count = 0
        for path in self.cache_dir.glob("*.json"):
            try:
                path.unlink()
                count += 1
            except OSError:
                pass
        return count
