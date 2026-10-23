"""A directory of project folders and the one project currently open."""

import json
import uuid
from pathlib import Path

from ncm_art.storage.errors import ProjectError
from ncm_art.storage.project import Project


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "library.json"
        if not self._index_path.exists():
            self._write_index({"active_project_id": None})

    def _read_index(self) -> dict:
        return json.loads(self._index_path.read_text(encoding="utf-8"))

    def _write_index(self, index: dict) -> None:
        self._index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    def create_project(self, title: str) -> Project:
        title = title.strip() or "Untitled"
        temporary = self.root / f".new-{uuid.uuid4()}"
        project = Project.create(temporary, title)
        project_id = project.manifest()["id"]
        destination = self.root / project_id
        temporary.rename(destination)
        return Project(destination)

    def list_projects(self) -> list[dict]:
        projects = []
        for path in sorted(self.root.iterdir()):
            manifest_path = path / "project.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                projects.append(
                    {
                        "id": manifest["id"],
                        "title": manifest["title"],
                        "created_at": manifest["created_at"],
                        "format_version": manifest["format_version"],
                    }
                )
        return projects

    def project(self, project_id: str) -> Project:
        path = self.root / project_id
        if not (path / "project.json").is_file():
            raise ProjectError("NOT_FOUND", "That project is not in this library.", status=404)
        project = Project(path)
        project.ensure_current()
        return project

    def active_project_id(self) -> str | None:
        return self._read_index().get("active_project_id")

    def active_project(self) -> Project | None:
        project_id = self.active_project_id()
        if not project_id:
            return None
        return self.project(project_id)

    def open_project(self, project_id: str) -> Project:
        current = self.active_project()
        if current is not None and current.manifest()["id"] != project_id:
            if current.active_job() is not None:
                raise ProjectError(
                    "JOB_ACTIVE",
                    "Finish or cancel the current job before opening another project.",
                    status=409,
                )
        project = self.project(project_id)
        index = self._read_index()
        index["active_project_id"] = project.manifest()["id"]
        self._write_index(index)
        return project

    def require_active(self) -> Project:
        project = self.active_project()
        if project is None:
            raise ProjectError("PROJECT_NOT_OPEN", "Open a project first.", status=409)
        return project
