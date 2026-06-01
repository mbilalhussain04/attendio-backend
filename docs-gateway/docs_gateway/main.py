from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="Attendio Services Docs Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:8000").rstrip("/")
ATTENDANCE_SERVICE_URL = os.getenv("ATTENDANCE_SERVICE_URL", "http://localhost:8001").rstrip("/")
LEAVE_SERVICE_URL = os.getenv("LEAVE_SERVICE_URL", "http://localhost:8004").rstrip("/")
STORAGE_SERVICE_URL = os.getenv("STORAGE_SERVICE_URL", "http://localhost:8002").rstrip("/")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:8003").rstrip("/")
BILLING_SERVICE_URL = os.getenv("BILLING_SERVICE_URL", "http://localhost:8005").rstrip("/")
GATEWAY_PUBLIC_URL = os.getenv("GATEWAY_PUBLIC_URL") or os.getenv("DOCS_GATEWAY_URL", "http://localhost:8090")
GATEWAY_PUBLIC_URL = GATEWAY_PUBLIC_URL.rstrip("/")
PUBLIC_AUTH_API_URL = os.getenv("PUBLIC_AUTH_API_URL", GATEWAY_PUBLIC_URL).rstrip("/")
PUBLIC_ATTENDANCE_API_URL = os.getenv("PUBLIC_ATTENDANCE_API_URL", GATEWAY_PUBLIC_URL).rstrip("/")
PUBLIC_LEAVE_API_URL = os.getenv("PUBLIC_LEAVE_API_URL", GATEWAY_PUBLIC_URL).rstrip("/")
PUBLIC_STORAGE_API_URL = os.getenv("PUBLIC_STORAGE_API_URL", GATEWAY_PUBLIC_URL).rstrip("/")
PUBLIC_NOTIFICATION_API_URL = os.getenv("PUBLIC_NOTIFICATION_API_URL", GATEWAY_PUBLIC_URL).rstrip("/")
PUBLIC_BILLING_API_URL = os.getenv("PUBLIC_BILLING_API_URL", GATEWAY_PUBLIC_URL).rstrip("/")
SWAGGER_URLS = [
    {"url": "/openapi/auth.json", "name": "Auth Service"},
    {"url": "/openapi/attendance.json", "name": "Attendance Service"},
    {"url": "/openapi/leave.json", "name": "Leave Service"},
    {"url": "/openapi/storage.json", "name": "Storage Service"},
    {"url": "/openapi/notification.json", "name": "Notification Service"},
    {"url": "/openapi/billing.json", "name": "Billing Service"},
]


def rewrite_refs(value: Any, renames: dict[str, str]) -> Any:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            for old, new in renames.items():
                old_ref = f"#/components/schemas/{old}"
                if ref == old_ref:
                    value["$ref"] = f"#/components/schemas/{new}"
                    break
        for item in value.values():
            rewrite_refs(item, renames)
    elif isinstance(value, list):
        for item in value:
            rewrite_refs(item, renames)
    return value


def merge_openapi(auth: dict[str, Any], attendance: dict[str, Any], storage: dict[str, Any] | None = None, notification: dict[str, Any] | None = None, leave: dict[str, Any] | None = None, billing: dict[str, Any] | None = None) -> dict[str, Any]:
    storage = storage or {}
    notification = notification or {}
    leave = leave or {}
    billing = billing or {}
    merged: dict[str, Any] = {
        "openapi": auth.get("openapi") or attendance.get("openapi") or storage.get("openapi") or leave.get("openapi") or billing.get("openapi") or "3.1.0",
        "info": {
            "title": "Attendio Platform API",
            "version": "1.0.0",
        "description": "Unified API documentation for Auth, Attendance, Leave, Storage, Notification, and Billing services.",
        },
        "paths": {},
        "components": {},
        "tags": [],
        "servers": [{"url": "http://localhost", "description": "Local gateway"}],
    }

    tag_names: set[str] = set()
    for spec in (auth, attendance, leave, storage, notification, billing):
        for tag in spec.get("tags", []):
            name = tag.get("name") if isinstance(tag, dict) else None
            if name and name not in tag_names:
                merged["tags"].append(tag)
                tag_names.add(name)

    for service_name, spec in (("Auth", auth), ("Attendance", attendance), ("Leave", leave), ("Storage", storage), ("Notification", notification), ("Billing", billing)):
        spec_copy = deepcopy(spec)
        renames: dict[str, str] = {}
        schemas = spec_copy.get("components", {}).get("schemas", {})
        merged_schemas = merged.setdefault("components", {}).setdefault("schemas", {})

        for schema_name, schema in list(schemas.items()):
            target_name = schema_name
            if target_name in merged_schemas and merged_schemas[target_name] != schema:
                target_name = f"{service_name}{schema_name}"
                renames[schema_name] = target_name
            merged_schemas[target_name] = schema

        if renames:
            rewrite_refs(spec_copy, renames)

        merged["paths"].update(spec_copy.get("paths", {}))
        for component_type, values in spec_copy.get("components", {}).items():
            if component_type == "schemas":
                continue
            target = merged["components"].setdefault(component_type, {})
            if isinstance(values, dict):
                target.update(values)

    return merged


async def fetch_openapi(base_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{base_url}/openapi.json")
        response.raise_for_status()
        return response.json()


async def fetch_openapi_for_browser(base_url: str, public_url: str) -> dict[str, Any]:
    spec = await fetch_openapi(base_url)
    spec["servers"] = [{"url": public_url, "description": "Gateway"}]
    return spec


async def proxy_request(request: Request, upstream_base_url: str, upstream_path: str) -> Response:
    target_url = httpx.URL(f"{upstream_base_url}/{upstream_path.lstrip('/')}").copy_with(
        query=request.url.query.encode("utf-8")
    )
    excluded_headers = {"host", "content-length", "connection"}
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded_headers
    }
    headers["x-forwarded-host"] = request.headers.get("host", "")
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-real-ip"] = request.client.host if request.client else ""
    body = await request.body()
    async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
        upstream = await client.request(
            request.method,
            target_url,
            content=body,
            headers=headers,
        )

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in {"content-encoding", "transfer-encoding", "connection", "set-cookie"}
    }
    response = Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )
    for cookie in upstream.headers.get_list("set-cookie"):
        response.headers.append("set-cookie", cookie)
    return response


@app.get("/health", tags=["Gateway"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "docs-gateway"}


@app.api_route("/api/v1/attendance/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_attendance_api(path: str, request: Request) -> Response:
    return await proxy_request(request, ATTENDANCE_SERVICE_URL, f"/api/v1/attendance/{path}")


@app.api_route("/api/v1/leave/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_leave_api(path: str, request: Request) -> Response:
    return await proxy_request(request, LEAVE_SERVICE_URL, f"/api/v1/leave/{path}")

@app.api_route("/api/v1/storage/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_storage_api(path: str, request: Request) -> Response:
    return await proxy_request(request, STORAGE_SERVICE_URL, f"/api/v1/storage/{path}")

@app.api_route("/api/v1/notifications", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_notification_root(request: Request) -> Response:
    return await proxy_request(request, NOTIFICATION_SERVICE_URL, "/api/v1/notifications")

@app.api_route("/api/v1/notifications/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_notification_api(path: str, request: Request) -> Response:
    return await proxy_request(request, NOTIFICATION_SERVICE_URL, f"/api/v1/notifications/{path}")


@app.api_route("/api/v1/billing/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_billing_api(path: str, request: Request) -> Response:
    return await proxy_request(request, BILLING_SERVICE_URL, f"/api/v1/billing/{path}")


@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_auth_api(path: str, request: Request) -> Response:
    return await proxy_request(request, AUTH_SERVICE_URL, f"/api/v1/{path}")


@app.get("/openapi/auth.json", include_in_schema=False)
async def auth_openapi() -> dict[str, Any]:
    return await fetch_openapi_for_browser(AUTH_SERVICE_URL, PUBLIC_AUTH_API_URL)


@app.get("/openapi/attendance.json", include_in_schema=False)
async def attendance_openapi() -> dict[str, Any]:
    return await fetch_openapi_for_browser(ATTENDANCE_SERVICE_URL, PUBLIC_ATTENDANCE_API_URL)


@app.get("/openapi/leave.json", include_in_schema=False)
async def leave_openapi() -> dict[str, Any]:
    return await fetch_openapi_for_browser(LEAVE_SERVICE_URL, PUBLIC_LEAVE_API_URL)


@app.get("/openapi/storage.json", include_in_schema=False)
async def storage_openapi() -> dict[str, Any]:
    return await fetch_openapi_for_browser(STORAGE_SERVICE_URL, PUBLIC_STORAGE_API_URL)


@app.get("/openapi/notification.json", include_in_schema=False)
async def notification_openapi() -> dict[str, Any]:
    return await fetch_openapi_for_browser(NOTIFICATION_SERVICE_URL, PUBLIC_NOTIFICATION_API_URL)


@app.get("/openapi/billing.json", include_in_schema=False)
async def billing_openapi() -> dict[str, Any]:
    return await fetch_openapi_for_browser(BILLING_SERVICE_URL, PUBLIC_BILLING_API_URL)


@app.get("/openapi.json", include_in_schema=False)
async def unified_openapi() -> dict[str, Any]:
    auth = await fetch_openapi_for_browser(AUTH_SERVICE_URL, PUBLIC_AUTH_API_URL)
    attendance = await fetch_openapi_for_browser(ATTENDANCE_SERVICE_URL, PUBLIC_ATTENDANCE_API_URL)
    leave = await fetch_openapi_for_browser(LEAVE_SERVICE_URL, PUBLIC_LEAVE_API_URL)
    storage = await fetch_openapi_for_browser(STORAGE_SERVICE_URL, PUBLIC_STORAGE_API_URL)
    notification = await fetch_openapi_for_browser(NOTIFICATION_SERVICE_URL, PUBLIC_NOTIFICATION_API_URL)
    billing = await fetch_openapi_for_browser(BILLING_SERVICE_URL, PUBLIC_BILLING_API_URL)
    return merge_openapi(auth, attendance, storage, notification, leave, billing)


@app.get("/docs", include_in_schema=False)
async def docs() -> HTMLResponse:
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Attendio Platform API Docs</title>
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  <style>
    html {{
      box-sizing: border-box;
      overflow-y: scroll;
    }}
    *, *:before, *:after {{
      box-sizing: inherit;
    }}
    body {{
      margin: 0;
      background: #fafafa;
    }}
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    window.onload = function() {{
      const ui = SwaggerUIBundle({{
        urls: {json.dumps(SWAGGER_URLS)},
        dom_id: '#swagger-ui',
        deepLinking: true,
        persistAuthorization: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset
        ],
        plugins: [
          SwaggerUIBundle.plugins.DownloadUrl
        ],
        layout: "StandaloneLayout"
      }});
      window.ui = ui;
    }};
  </script>
</body>
</html>
"""
    return HTMLResponse(html)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"message": "Open /docs for the unified Swagger UI"}
