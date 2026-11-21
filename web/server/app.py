"""GIS 多智能体 Web 控制台 · 零依赖本地服务。

启动：
    python web/server/app.py --open
    python web/server/app.py --port 8010

只使用 Python 标准库（http.server / json / socket），不需要安装任何依赖。
前端静态资源位于 web/，API 前缀 /api/。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR.parent
PROJECT_ROOT = WEB_DIR.parent
sys.path.insert(0, str(BASE_DIR))

try:
    import data_source as ds
    import demo_engine
except Exception as exc:  # pragma: no cover - 启动期错误直接打印
    print(f"[fatal] 无法加载数据层: {exc}", file=sys.stderr)
    raise

_LOCK = threading.Lock()
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


def _json_response(handler: BaseHTTPRequestHandler, payload, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: BaseHTTPRequestHandler, status: int, message: str, **extra) -> None:
    _json_response(handler, {"error": message, **extra}, status)


class Handler(BaseHTTPRequestHandler):
    server_version = "GISAgentWeb/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ 基础
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if os.getenv("GIS_WEB_VERBOSE"):
            sys.stderr.write("[web] " + (fmt % args) + "\n")

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > 512 * 1024:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"JSON 解析失败: {exc}") from exc
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ 路由
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                self._api_get(path, query)
                return
            if path == "/artifact/capability-chart.html":
                self._serve_project_chart()
                return
            if path == "/artifact/radar.png":
                self._serve_file(ds.DATA_DIR / "capability_vector_chart.png")
                return
            if path == "/artifact/report.md":
                self._serve_file(ds.REPORTS_DIR / "dev20" / "dev20_test_report.md", "text/markdown; charset=utf-8")
                return
            self._serve_static(path)
        except BrokenPipeError:
            pass
        except Exception as exc:  # pragma: no cover - 保底
            _error(self, 500, f"服务端异常: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        try:
            if not path.startswith("/api/"):
                _error(self, 404, "未知接口")
                return
            payload = self._read_json()
            self._api_post(path, payload)
        except ValueError as exc:
            _error(self, 400, str(exc))
        except BrokenPipeError:
            pass
        except Exception as exc:  # pragma: no cover
            _error(self, 500, f"服务端异常: {exc}")

    def do_DELETE(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path == "/api/runs":
            with _LOCK:
                ds.clear_runs()
            _json_response(self, {"ok": True})
            return
        _error(self, 404, "未知接口")

    # ------------------------------------------------------------------ API
    def _api_get(self, path: str, query: dict) -> None:
        if path == "/api/health":
            _json_response(self, ds.health())
            return
        if path == "/api/bootstrap":
            _json_response(self, ds.bootstrap())
            return
        if path == "/api/capability":
            source = (query.get("source") or ["demo"])[0]
            if source == "real":
                payload = ds.capability_payload(ds.real_capability(), source="real")
            else:
                payload = ds.capability_payload(ds.demo_capability(), source="demo")
            payload["runs"] = ds.load_runs()[:6]
            _json_response(self, payload)
            return
        if path == "/api/runs":
            runs = ds.load_runs()
            slim = [
                {
                    "run_id": r.get("run_id"),
                    "created_at": r.get("created_at"),
                    "question": r.get("question"),
                    "domain": r.get("domain"),
                    "domain_label": r.get("domain_label"),
                    "task_type": r.get("task_type"),
                    "metrics": r.get("metrics"),
                    "evaluation": (r.get("flow") or {}).get("evaluate", {}).get("evaluation"),
                    "agent_names": [
                        s.get("agent_name") for s in (r.get("subtasks") or [])
                    ],
                }
                for r in runs
            ]
            _json_response(self, {"runs": slim})
            return
        if path.startswith("/api/runs/"):
            run_id = path.split("/api/runs/", 1)[1]
            run = ds.get_run(run_id)
            if not run:
                _error(self, 404, "运行记录不存在")
            else:
                _json_response(self, run)
            return
        if path == "/api/memory":
            _json_response(
                self,
                {
                    "memory": ds.load_memory(),
                    "experience": ds.load_experience(),
                    "agents": ds.demo_capability()["agents"],
                },
            )
            return
        if path == "/api/admin":
            _json_response(self, ds.admin_payload())
            return
        if path == "/api/skills":
            _json_response(self, {"skills": ds.SKILLS, "tools": ds.TOOL_CATALOG})
            return
        if path == "/api/reports":
            _json_response(self, {"reports": ds.report_index()})
            return
        if path.startswith("/api/reports/"):
            name = path.split("/api/reports/", 1)[1]
            report = ds.load_report(name)
            if not report:
                _error(self, 404, "报告不存在")
            else:
                _json_response(self, report)
            return
        if path == "/api/export/snapshot":
            target = ds.write_snapshot()
            _json_response(self, {"ok": True, "path": str(target)})
            return
        _error(self, 404, "未知接口")

    def _api_post(self, path: str, payload: dict) -> None:
        if path == "/api/run":
            question = str(payload.get("question") or "").strip()
            truth = str(payload.get("truth") or "").strip()
            verdict = str(payload.get("verdict") or "auto")
            if not question:
                _error(self, 400, "请先输入问题")
                return
            if len(question) > 2000:
                _error(self, 400, "问题过长（最多 2000 字）")
                return
            with _LOCK:
                run = demo_engine.run_demo(question, truth=truth, verdict=verdict)
            _json_response(self, run)
            return
        if path == "/api/admin/capability/reset":
            if payload.get("confirm") is not True:
                _error(self, 400, "危险操作需要 confirm=true")
                return
            with _LOCK:
                before = ds.real_capability()
                state = ds.reset_real_capability()
            _json_response(
                self,
                {
                    "ok": True,
                    "path": ds._path_label(ds.CAPABILITY_PATH),
                    "initial_capability": state.get("initial_capability"),
                    "agent_count": len(state.get("agents") or {}),
                    "agents_reset": sorted(state.get("agents") or {}),
                    "cleared_history": len(before.get("history") or []),
                    "before": {
                        aid: (item or {}).get("capabilities") or {}
                        for aid, item in (before.get("agents") or {}).items()
                    },
                    "capability": ds.capability_payload(state, source="real"),
                },
            )
            return
        if path == "/api/admin/routing":
            if payload.get("confirm") is not True:
                _error(self, 400, "修改路由参数需要 confirm=true")
                return
            if "tie_epsilon" not in payload:
                _error(self, 400, "缺少 tie_epsilon")
                return
            with _LOCK:
                result = ds.update_tie_epsilon(payload.get("tie_epsilon"))
            _json_response(self, result)
            return
        if path == "/api/admin/memory":
            if payload.get("confirm") is not True:
                _error(self, 400, "危险操作需要 confirm=true")
                return
            agent_id = str(payload.get("agent_id") or "").strip()
            if not agent_id:
                _error(self, 400, "缺少 agent_id")
                return
            scope = str(payload.get("scope") or "all").strip()
            mode = str(payload.get("mode") or "clear").strip()
            with _LOCK:
                result = ds.mutate_agent_memory(agent_id, scope=scope, mode=mode)
            _json_response(self, result)
            return
        if path == "/api/retrieve":
            query = str(payload.get("query") or "").strip()
            kind = str(payload.get("kind") or "skills")
            agent = str(payload.get("agent") or "agent_02")
            if not query:
                _error(self, 400, "请输入检索文本")
                return
            _json_response(self, ds.retrieval_playground(query, kind, agent=agent))
            return
        if path == "/api/capability/reset":
            seed = str(payload.get("seed") or "initial")
            if payload.get("confirm") is not True:
                _error(self, 400, "需要 confirm=true 才能重置演示能力")
                return
            with _LOCK:
                before = ds.demo_capability()
                state = ds.reset_demo_capability(seed=seed)
                cleared_runs = bool(payload.get("clear_runs"))
                if cleared_runs:
                    ds.clear_runs()
            _json_response(
                self,
                {
                    "ok": True,
                    "seed": seed,
                    "agents_reset": sorted(state.get("agents") or {}),
                    "agent_count": len(state.get("agents") or {}),
                    "initial_capability": state.get("initial_capability"),
                    "cleared_runs": cleared_runs,
                    "before": {
                        aid: (item or {}).get("capabilities") or {}
                        for aid, item in (before.get("agents") or {}).items()
                    },
                    "capability": ds.capability_payload(state, source="demo"),
                },
            )
            return
        _error(self, 404, "未知接口")

    # ------------------------------------------------------------------ 静态文件
    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            target = WEB_DIR / "index.html"
        else:
            rel = path.lstrip("/")
            target = (WEB_DIR / rel).resolve()
            try:
                target.relative_to(WEB_DIR.resolve())
            except ValueError:
                _error(self, 403, "禁止访问")
                return
        if not target.exists():
            # SPA 兜底：未知路径返回首页，前端基于 hash 路由
            if "." not in Path(path).name:
                target = WEB_DIR / "index.html"
            else:
                _error(self, 404, "文件不存在")
                return
        if target.is_dir():
            target = target / "index.html"
        self._serve_file(target)

    def _serve_file(self, target: Path, content_type: str | None = None) -> None:
        if not target.exists() or not target.is_file():
            _error(self, 404, "文件不存在")
            return
        data = target.read_bytes()
        ctype = content_type or _MIME.get(target.suffix.lower()) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if target.suffix in (".html", ".js", ".css") else "public, max-age=60")
        self.end_headers()
        self.wfile.write(data)

    def _serve_project_chart(self) -> None:
        path = ds.DATA_DIR / "capability_vector_chart.html"
        if not path.exists():
            _error(self, 404, "项目尚未生成能力向量图，请先运行 main.py")
            return
        self._serve_file(path, "text/html; charset=utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="GIS 多智能体 Web 控制台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--no-snapshot", action="store_true", help="不生成静态快照")
    args = parser.parse_args()

    if not args.no_snapshot:
        try:
            ds.write_snapshot()
        except Exception as exc:  # 快照失败不影响服务
            print(f"[warn] 生成前端快照失败: {exc}", file=sys.stderr)

    ds.WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print(f"[error] 无法监听 {args.host}:{args.port} —— {exc}", file=sys.stderr)
        print(f"        端口可能已被占用，请换一个端口：python web/server/app.py --port {args.port + 1} --open", file=sys.stderr)
        return 1
    httpd.daemon_threads = True
    url = f"http://{args.host}:{args.port}"
    print("=" * 62)
    print("  GIS 多智能体任务架构 · Web 控制台")
    print(f"  服务地址: {url}")
    print(f"  项目目录: {PROJECT_ROOT}")
    print("  演示会话：不调用 LLM / 数据库；能力进化写入 web/data/")
    print("  按 Ctrl+C 停止服务")
    print("=" * 62)
    if args.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[stopped] 服务已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
