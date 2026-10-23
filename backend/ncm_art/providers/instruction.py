"""A configured local chat endpoint. No model is pinned, and no key is stored in a project."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ncm_art.storage.errors import ProjectError

ENDPOINT_KIND = "openai-chat-completions"
UNAVAILABLE = "No instruction provider is configured. Import, transfer, and returning a name still work."


class _RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProjectError(
            "CAPABILITY_UNAVAILABLE",
            "The instruction provider redirected the request. The passage was not sent onward.",
            status=503,
        )


def load_profile(library_root: Path) -> dict | None:
    """Environment settings override the library file. A key in either place is refused."""
    path = Path(library_root) / "instruction.json"
    file_profile = None
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ProjectError(
                "CAPABILITY_UNAVAILABLE",
                "The instruction provider settings could not be read.",
                {"reason": str(error)},
                status=503,
            ) from error
        if not isinstance(loaded, dict):
            raise ProjectError("CAPABILITY_UNAVAILABLE", "The instruction provider settings could not be read.", status=503)
        _refuse_secret(loaded)
        file_profile = loaded
    url = os.environ.get("NCM_ART_INSTRUCTION_URL", "").strip()
    model = os.environ.get("NCM_ART_INSTRUCTION_MODEL", "").strip()
    if url or model:
        if not url or not model:
            raise ProjectError(
                "CAPABILITY_UNAVAILABLE",
                "Set both NCM_ART_INSTRUCTION_URL and NCM_ART_INSTRUCTION_MODEL.",
                status=503,
            )
        return _profile(ENDPOINT_KIND, url, model)
    if file_profile is None:
        return None
    return _profile(
        str(file_profile.get("endpoint_kind") or ""),
        str(file_profile.get("base_url") or ""),
        str(file_profile.get("model") or ""),
    )


def capability(library_root: Path) -> dict:
    try:
        profile = load_profile(library_root)
    except ProjectError as error:
        return {"profile": ENDPOINT_KIND, "state": "unavailable", "message": error.message, "model": None}
    if profile is None:
        return {"profile": ENDPOINT_KIND, "state": "unavailable", "message": UNAVAILABLE, "model": None}
    return {"profile": profile["endpoint_kind"], "state": "configured", "message": None, "model": profile["model"]}


def chat_completion(profile: dict, body: dict) -> dict:
    payload = json.dumps(body).encode("utf-8")
    request = Request(
        f"{profile['base_url']}/chat/completions",
        data=payload,
        headers=_headers(),
        method="POST",
    )
    opener = build_opener(_RefuseRedirect)
    try:
        with opener.open(request, timeout=60) as response:
            raw = response.read(1_000_000)
    except ProjectError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise ProjectError(
            "CAPABILITY_UNAVAILABLE",
            "The instruction provider did not answer. The work was not changed.",
            {"reason": str(error)},
            status=503,
        ) from error
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProjectError(
            "INVALID_PROVIDER_OUTPUT",
            "The response was not the requested JSON object.",
            {"reason": "malformed"},
            status=422,
        ) from error
    if not isinstance(parsed, dict):
        raise ProjectError(
            "INVALID_PROVIDER_OUTPUT",
            "The response was not the requested JSON object.",
            {"reason": "malformed"},
            status=422,
        )
    return parsed


def _profile(kind: str, base_url: str, model: str) -> dict:
    if kind != ENDPOINT_KIND:
        raise ProjectError(
            "CAPABILITY_UNAVAILABLE",
            "The instruction provider has to be an OpenAI-compatible chat endpoint.",
            status=503,
        )
    if not model.strip():
        raise ProjectError("CAPABILITY_UNAVAILABLE", "The instruction provider settings need a model name.", status=503)
    url = base_url.strip().rstrip("/")
    if not (url.startswith("http://") or url.startswith("https://")) or "://" not in url:
        raise ProjectError("CAPABILITY_UNAVAILABLE", "The instruction provider URL has to be an http or https address.", status=503)
    host = url.split("://", 1)[1]
    if not host or host.startswith("/") or "@" in host.split("/")[0]:
        raise ProjectError(
            "CAPABILITY_UNAVAILABLE",
            "The instruction provider URL cannot carry a username or password.",
            status=503,
        )
    return {"endpoint_kind": kind, "base_url": url, "model": model.strip()}


def _refuse_secret(payload: dict) -> None:
    lowered = {str(key).lower() for key in payload}
    if lowered & {"api_key", "apikey", "authorization", "token", "password"}:
        raise ProjectError(
            "CAPABILITY_UNAVAILABLE",
            "Put the instruction provider key in NCM_ART_INSTRUCTION_API_KEY. It is not stored in the library file.",
            status=503,
        )


def _headers() -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = os.environ.get("NCM_ART_INSTRUCTION_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers
