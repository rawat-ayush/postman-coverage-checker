"""Minimal Postman API client. Fetches a collection and flattens its requests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

_API = "https://api.getpostman.com"


@dataclass
class PostmanRequest:
    name: str
    folder_path: list[str] = field(default_factory=list)  # ancestor folder names, root first

    @property
    def full_path(self) -> str:
        return " / ".join(self.folder_path + [self.name])


@dataclass
class PostmanCollection:
    id: str
    name: str
    requests: list[PostmanRequest]

    def requests_in_folder(self, folder_name_lower_variants: set[str]) -> list[PostmanRequest]:
        """Return requests whose folder path contains any of the given names."""
        out: list[PostmanRequest] = []
        for req in self.requests:
            path_lower = {p.lower() for p in req.folder_path}
            if path_lower & folder_name_lower_variants:
                out.append(req)
        return out


class PostmanClient:
    def __init__(self, api_key: str, timeout: int = 30) -> None:
        self._session = requests.Session()
        self._session.headers.update({"X-Api-Key": api_key})
        self._timeout = timeout

    def get_collection(self, collection_id: str) -> PostmanCollection:
        r = self._session.get(f"{_API}/collections/{collection_id}", timeout=self._timeout)
        r.raise_for_status()
        payload = r.json().get("collection") or {}
        info = payload.get("info") or {}
        requests_list: list[PostmanRequest] = []
        _walk_items(payload.get("item") or [], [], requests_list)
        return PostmanCollection(
            id=collection_id,
            name=info.get("name", collection_id),
            requests=requests_list,
        )


def _walk_items(items: list[dict[str, Any]], path: list[str], out: list[PostmanRequest]) -> None:
    for item in items:
        name = item.get("name") or ""
        if "item" in item and isinstance(item["item"], list):
            _walk_items(item["item"], path + [name], out)
        else:
            out.append(PostmanRequest(name=name, folder_path=list(path)))
