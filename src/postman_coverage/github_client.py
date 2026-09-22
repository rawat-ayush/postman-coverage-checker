"""Minimal GitHub API client for listing YAML files in a repo folder."""
from __future__ import annotations

from dataclasses import dataclass

import requests

_API = "https://api.github.com"


@dataclass
class RepoFile:
    name: str
    path: str
    sha: str


@dataclass
class RepoEntry:
    name: str
    path: str
    type: str  # "file" or "dir"


class GithubClient:
    def __init__(self, token: str, timeout: int = 30) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        self._timeout = timeout

    def list_yaml_files(
        self, owner: str, repo: str, path: str, branch: str
    ) -> list[RepoFile]:
        """Recursively list *.yaml / *.yml files under `path` on `branch`."""
        tree = self._get_tree(owner, repo, branch)
        prefix = path.strip("/") + "/" if path.strip("/") else ""
        files: list[RepoFile] = []
        for node in tree:
            if node.get("type") != "blob":
                continue
            p: str = node["path"]
            if prefix and not p.startswith(prefix):
                continue
            lower = p.lower()
            if not (lower.endswith(".yaml") or lower.endswith(".yml")):
                continue
            files.append(RepoFile(name=p.rsplit("/", 1)[-1], path=p, sha=node["sha"]))
        return files

    def list_dir(
        self, owner: str, repo: str, path: str, branch: str
    ) -> list[RepoEntry]:
        """List immediate contents (files and folders) at `path` on `branch`."""
        url = f"{_API}/repos/{owner}/{repo}/contents/{path.strip('/')}"
        r = self._session.get(url, params={"ref": branch}, timeout=self._timeout)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        return [
            RepoEntry(name=item["name"], path=item["path"], type=item["type"])
            for item in data
        ]

    def _get_tree(self, owner: str, repo: str, branch: str) -> list[dict]:
        url = f"{_API}/repos/{owner}/{repo}/git/trees/{branch}"
        r = self._session.get(url, params={"recursive": "1"}, timeout=self._timeout)
        r.raise_for_status()
        data = r.json()
        if data.get("truncated"):
            # Tree API caps at 100k entries / 7 MB. Fall back to contents API
            # scoped at the folder if this ever fires in practice.
            raise RuntimeError(
                "GitHub tree response was truncated; folder is too large for the "
                "single-call listing. Narrow the `path` in cores.yaml."
            )
        return data.get("tree", [])
