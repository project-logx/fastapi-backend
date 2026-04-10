from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from nicegui import ui


DEFAULT_API_BASE = "http://127.0.0.1:8000/api/v1"
LOCAL_BACKEND_HOSTS = {"127.0.0.1", "localhost"}


@dataclass
class PendingUpload:
    name: str
    content: bytes
    content_type: str


@dataclass
class AppState:
    api_base: str = DEFAULT_API_BASE
    backend_process_pid: int | None = None
    capture_trade_id: int | None = None
    capture_type: str | None = None
    capture_uploads: list[PendingUpload] = field(default_factory=list)
    capture_config: dict[str, Any] = field(default_factory=dict)
    custom_tags: list[dict[str, Any]] = field(default_factory=list)
    expanded_journey_ids: set[int] = field(default_factory=set)


state = AppState()
ui_refs: dict[str, Any] = {}


def _set_label_text(ref_name: str, value: str) -> None:
    label = ui_refs.get(ref_name)
    if label is not None:
        label.set_text(value)


def _health_ok(api_base: str, timeout: float = 1.5) -> bool:
    try:
        response = requests.get(f"{api_base}/health", timeout=timeout)
        return response.status_code == 200
    except requests.RequestException:
        return False


def _is_local_api_base(api_base: str) -> tuple[bool, str, int]:
    parsed = urlparse(api_base)
    host = (parsed.hostname or "").lower()
    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80
    return host in LOCAL_BACKEND_HOSTS, host, port


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ensure_backend_running(api_base: str) -> tuple[bool, str]:
    if _health_ok(api_base):
        return True, ""

    is_local, host, port = _is_local_api_base(api_base)
    if not is_local:
        return False, "Backend unreachable. Auto-start is only supported for localhost/127.0.0.1 API URLs."

    if _pid_alive(state.backend_process_pid):
        for _ in range(20):
            if _health_ok(api_base):
                return True, "Local backend connected."
            time.sleep(0.25)
        return False, "Local backend process is running but health endpoint is not ready yet."

    project_root = Path(__file__).resolve().parents[1]
    backend_dir = project_root / "backend"
    backend_host = "127.0.0.1" if host == "localhost" else host
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        str(backend_dir),
        "--host",
        backend_host,
        "--port",
        str(port),
    ]

    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    except OSError as exc:
        return False, f"Failed to auto-start backend: {exc}"

    state.backend_process_pid = process.pid

    for _ in range(32):
        if _health_ok(api_base):
            return True, f"Backend auto-started (PID {process.pid})"
        time.sleep(0.25)

    return False, "Backend process started but did not become healthy in time."


def api_request(method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any] | str]:
    url = f"{state.api_base}{path}"
    try:
        response = requests.request(method=method, url=url, timeout=20, **kwargs)
    except requests.RequestException as exc:
        return 0, str(exc)

    try:
        body: dict[str, Any] | str = response.json()
    except ValueError:
        body = response.text

    return response.status_code, body


def show_api_error(status: int, body: dict[str, Any] | str) -> None:
    if status == 0:
        ui.notify(f"Cannot reach backend: {body}", type="negative")
        return
    if isinstance(body, dict):
        ui.notify(str(body.get("detail") or body.get("message") or body), type="negative")
    else:
        ui.notify(str(body), type="negative")


def load_capture_config() -> None:
    status, body = api_request("GET", "/metadata/capture-config")
    if status == 200 and isinstance(body, dict):
        state.capture_config = body.get("data", {})
        return
    state.capture_config = {
        "sliders": ["Confidence", "Stress", "Focus", "Market Clarity", "Patience"],
        "fixed_tags_by_category": {},
        "tag_categories_by_node_type": {"entry": [], "mid": [], "exit": []},
        "fixed_tag_options_by_node_type": {"entry": {}, "mid": {}, "exit": {}},
    }


def load_custom_tags() -> None:
    status, body = api_request("GET", "/tags/custom")
    if status == 200 and isinstance(body, dict):
        state.custom_tags = body.get("data", [])
    else:
        state.custom_tags = []


def refresh_custom_tags_panel() -> None:
    container = ui_refs["custom_tags_container"]
    container.clear()
    with container:
        if not state.custom_tags:
            ui.label("No custom tags yet").classes("text-gray-500")
            return
        for tag in state.custom_tags:
            ui.label(f"- {tag['name']}").classes("text-sm")


def start_capture(trade_id: int, node_type: str) -> None:
    state.capture_trade_id = trade_id
    state.capture_type = node_type
    state.capture_uploads.clear()
    refresh_capture_panel()
    ui.notify(f"Capture form opened for Trade #{trade_id} ({node_type})", type="info")


def refresh_queue_panel() -> None:
    entry_container = ui_refs["pending_entry_container"]
    exit_container = ui_refs["pending_exit_container"]
    entry_container.clear()
    exit_container.clear()

    status, body = api_request("GET", "/queue/pending")
    if status != 200 or not isinstance(body, dict):
        with entry_container:
            ui.label("Failed to load pending queue").classes("text-negative")
        show_api_error(status, body)
        return

    queue_data = body.get("data", {})
    pending_entry = queue_data.get("pending_entry", [])
    pending_exit = queue_data.get("pending_exit", [])

    with entry_container:
        if not pending_entry:
            ui.label("No pending entry captures").classes("text-gray-500")
        for trade in pending_entry:
            with ui.card().classes("w-full"):
                ui.label(f"Trade #{trade['id']} | {trade['symbol']} | Qty {trade['quantity']}")
                ui.label(f"Waiting: {trade.get('waiting_seconds')} sec").classes("text-xs text-gray-500")
                ui.button("Capture Entry", on_click=lambda trade_id=trade["id"]: start_capture(trade_id, "entry"))

    with exit_container:
        if not pending_exit:
            ui.label("No pending exit captures").classes("text-gray-500")
        for trade in pending_exit:
            with ui.card().classes("w-full"):
                ui.label(f"Trade #{trade['id']} | {trade['symbol']} | Qty {trade['quantity']}")
                ui.label(f"Waiting: {trade.get('waiting_seconds')} sec").classes("text-xs text-gray-500")
                ui.button("Capture Exit", on_click=lambda trade_id=trade["id"]: start_capture(trade_id, "exit"))


def _format_node_timestamp(raw_value: Any) -> str:
    if not raw_value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return str(raw_value)


def _build_journey_timeline(nodes: list[dict[str, Any]]) -> str:
    if not nodes:
        return "No nodes captured"

    parts: list[str] = []
    mid_index = 0
    for node in nodes:
        node_type = str(node.get("type") or "").lower()
        if node_type == "entry":
            node_label = "Start"
        elif node_type == "mid":
            mid_index += 1
            node_label = f"Mid {mid_index}"
        elif node_type == "exit":
            node_label = "End"
        else:
            node_label = node_type.title() or "Node"

        parts.append(f"{node_label} ({_format_node_timestamp(node.get('captured_at'))})")

    return " -> ".join(parts)


def _format_map_for_display(raw_value: Any) -> str:
    if not isinstance(raw_value, dict) or not raw_value:
        return "None"
    return ", ".join(f"{key}: {value}" for key, value in raw_value.items())


def _set_journey_expanded(journey_id: int, is_expanded: bool) -> None:
    if is_expanded:
        state.expanded_journey_ids.add(journey_id)
        return
    state.expanded_journey_ids.discard(journey_id)


def refresh_journeys_panel() -> None:
    container = ui_refs["journeys_container"]
    container.clear()

    status, body = api_request("GET", "/journeys")
    if status != 200 or not isinstance(body, dict):
        with container:
            ui.label("Failed to load journeys").classes("text-negative")
        show_api_error(status, body)
        return

    rows = body.get("data", [])
    row_ids = {int(item.get("id")) for item in rows if item.get("id") is not None}
    state.expanded_journey_ids.intersection_update(row_ids)

    with container:
        if not rows:
            ui.label("No completed journeys yet").classes("text-gray-500")
            return

        for journey in rows:
            detail_status, detail_body = api_request("GET", f"/journeys/{journey['id']}")
            if detail_status != 200 or not isinstance(detail_body, dict):
                with ui.card().classes("w-full"):
                    ui.label(f"Journey #{journey['id']} | {journey['symbol']}")
                    ui.label("Failed to load journey details").classes("text-negative")
                continue

            nodes = detail_body.get("data", {}).get("nodes", [])
            timeline = _build_journey_timeline(nodes)
            mid_count = sum(1 for node in nodes if str(node.get("type") or "").lower() == "mid")
            journey_id = int(journey["id"])

            title = f"Journey #{journey['id']} | {journey['symbol']} | P&L: {journey.get('pnl')}"
            with ui.expansion(
                title,
                value=journey_id in state.expanded_journey_ids,
                on_value_change=lambda event, current_id=journey_id: _set_journey_expanded(
                    current_id,
                    bool(getattr(event, "value", False)),
                ),
            ).classes("w-full"):
                ui.label(timeline).classes("text-sm")
                ui.label(f"Total nodes: {len(nodes)} | Mid nodes: {mid_count}").classes("text-xs text-gray-500")
                ui.separator()

                if not nodes:
                    ui.label("No nodes captured").classes("text-sm text-gray-500")
                    continue

                mid_index = 0
                for node in nodes:
                    node_type = str(node.get("type") or "").lower()
                    if node_type == "entry":
                        node_label = "Start"
                    elif node_type == "mid":
                        mid_index += 1
                        node_label = f"Mid {mid_index}"
                    elif node_type == "exit":
                        node_label = "End"
                    else:
                        node_label = node_type.title() or "Node"

                    fixed_tags = node.get("fixed_tags_by_type") or node.get("fixed_tags") or {}
                    custom_names = [item.get("name", "") for item in node.get("custom_tags", []) if item.get("name")]
                    attachments = node.get("attachments", [])

                    with ui.card().classes("w-full"):
                        ui.label(f"{node_label} | {node_type.upper() or 'NODE'}").classes("font-semibold")
                        ui.label(f"Captured at: {_format_node_timestamp(node.get('captured_at'))}").classes("text-sm")
                        ui.label(f"Fixed tags: {_format_map_for_display(fixed_tags)}").classes("text-sm")
                        ui.label(f"Custom tags: {', '.join(custom_names) if custom_names else 'None'}").classes("text-sm")
                        ui.label(f"Sliders: {_format_map_for_display(node.get('sliders'))}").classes("text-sm")
                        ui.label(f"Note: {node.get('note') or '-'}").classes("text-sm")
                        ui.label(f"Attachments: {len(attachments)}").classes("text-sm")

                        if attachments:
                            with ui.row().classes("gap-2"):
                                for attachment in attachments:
                                    with ui.column().classes("items-center"):
                                        ui.image(f"{state.api_base}/attachments/{attachment['id']}").classes("w-24 h-24 object-cover")
                                        ui.label(attachment.get("file_name", "attachment")).classes("text-xs")


def refresh_events_panel() -> None:
    container = ui_refs["events_container"]
    container.clear()

    status, body = api_request("GET", "/mock/events/history")
    if status != 200 or not isinstance(body, dict):
        with container:
            ui.label("Failed to load event history").classes("text-negative")
        show_api_error(status, body)
        return

    with container:
        ui.code(json.dumps(body.get("data", []), indent=2), language="json").classes("w-full")


def _uploads_summary() -> str:
    if not state.capture_uploads:
        return "No files selected"
    names = ", ".join(item.name for item in state.capture_uploads)
    return f"Selected files: {names}"


def refresh_capture_panel() -> None:
    container = ui_refs["capture_container"]
    container.clear()

    with container:
        if state.capture_trade_id is None or state.capture_type is None:
            ui.label("Select a trade from Pending Queue to capture node context.").classes("text-gray-500")
            return

        capture_type = state.capture_type
        with ui.card().classes("w-full"):
            ui.label(f"Capture {capture_type.title()} Node for Trade #{state.capture_trade_id}").classes("text-lg font-semibold")
            if capture_type in {"entry", "mid"}:
                ui.label("After entry tags").classes("text-sm text-gray-600")
            elif capture_type == "exit":
                ui.label("After close tags").classes("text-sm text-gray-600")

            selected_fixed_controls: dict[str, Any] = {}
            active_categories = state.capture_config.get("tag_categories_by_node_type", {}).get(capture_type, [])
            active_options_by_category = state.capture_config.get("fixed_tag_options_by_node_type", {}).get(capture_type, {})

            for category in active_categories:
                options = active_options_by_category.get(category, [])
                selected_fixed_controls[category] = ui.select(options=options, label=category, value=None).classes("w-full")

            custom_name_to_id = {item["name"]: item["id"] for item in state.custom_tags if item.get("name")}
            custom_tag_select = ui.select(
                options=list(custom_name_to_id.keys()),
                label="Custom tags",
                multiple=True,
                value=[],
            ).classes("w-full")

            slider_controls: dict[str, Any] = {}
            for slider_name in state.capture_config.get("sliders", []):
                slider_controls[slider_name] = ui.number(
                    slider_name,
                    value=5,
                    min=0,
                    max=10,
                    step=1,
                ).classes("w-full")

            note_input = ui.textarea("Thought/note").classes("w-full")
            uploads_label = ui.label(_uploads_summary()).classes("text-sm text-gray-600")

            def clear_uploads() -> None:
                state.capture_uploads.clear()
                uploads_label.set_text(_uploads_summary())

            def handle_capture_upload(event: Any) -> None:
                content = event.content.read()
                guessed_type = getattr(event, "type", None) or getattr(event, "content_type", None)
                mime_type = guessed_type or mimetypes.guess_type(event.name)[0] or "application/octet-stream"
                state.capture_uploads.append(PendingUpload(name=event.name, content=content, content_type=mime_type))
                uploads_label.set_text(_uploads_summary())

            with ui.row().classes("items-center gap-3"):
                ui.upload(
                    on_upload=handle_capture_upload,
                    multiple=True,
                    auto_upload=True,
                ).props("accept=.png,.jpg,.jpeg,.webp")
                ui.button("Clear selected files", on_click=clear_uploads)

            def submit_capture() -> None:
                missing = [category for category, control in selected_fixed_controls.items() if not control.value]
                if missing:
                    ui.notify(f"Please select one tag for each required category: {', '.join(missing)}", type="negative")
                    return

                selected_custom = custom_tag_select.value or []
                if isinstance(selected_custom, str):
                    selected_custom = [selected_custom]

                fixed_tags_payload = {category: str(control.value) for category, control in selected_fixed_controls.items()}
                slider_values = {
                    slider_name: int((control.value if control.value is not None else 0))
                    for slider_name, control in slider_controls.items()
                }

                data = {
                    "type": capture_type,
                    "captured_at": datetime.now(UTC).isoformat(),
                    "fixed_tags": json.dumps(fixed_tags_payload),
                    "custom_tag_ids": json.dumps([custom_name_to_id[name] for name in selected_custom if name in custom_name_to_id]),
                    "sliders": json.dumps(slider_values),
                    "note": note_input.value or "",
                }
                files = [
                    ("files", (item.name, item.content, item.content_type))
                    for item in state.capture_uploads
                ]

                status, body = api_request(
                    "POST",
                    f"/trades/{state.capture_trade_id}/nodes",
                    data=data,
                    files=files if files else None,
                )
                if status == 200:
                    ui.notify("Node submitted", type="positive")
                    state.capture_trade_id = None
                    state.capture_type = None
                    state.capture_uploads.clear()
                    refresh_all()
                else:
                    show_api_error(status, body)

            with ui.row().classes("gap-3"):
                ui.button("Submit Node", on_click=submit_capture)
                ui.button("Cancel", on_click=lambda: clear_capture_state())


def clear_capture_state() -> None:
    state.capture_trade_id = None
    state.capture_type = None
    state.capture_uploads.clear()
    refresh_capture_panel()


def refresh_all(include_capture: bool = True, include_journeys: bool = True) -> None:
    load_capture_config()
    load_custom_tags()
    refresh_custom_tags_panel()
    refresh_queue_panel()
    if include_journeys:
        refresh_journeys_panel()
    refresh_events_panel()
    if include_capture:
        refresh_capture_panel()


def periodic_refresh() -> None:
    capture_in_progress = state.capture_trade_id is not None and state.capture_type is not None
    journey_expanded = bool(state.expanded_journey_ids)
    # Preserve in-progress capture form selections by skipping capture panel re-render.
    # Keep journeys stable while a journey is expanded to avoid auto-collapse.
    refresh_all(include_capture=not capture_in_progress, include_journeys=not journey_expanded)


def connect_backend(show_notification: bool = True) -> None:
    api_base_input = ui_refs["api_base_input"]
    new_base = str(api_base_input.value or DEFAULT_API_BASE).rstrip("/")
    if not new_base:
        new_base = DEFAULT_API_BASE
        api_base_input.value = new_base

    state.api_base = new_base

    ok, note = ensure_backend_running(state.api_base)
    if not ok:
        _set_label_text("connection_status", note)
        if show_notification:
            ui.notify(note, type="negative")
        return

    if note and show_notification:
        ui.notify(note, type="info")

    status, body = api_request("GET", "/health")
    if status != 200:
        _set_label_text("connection_status", "Backend health check failed")
        show_api_error(status, body)
        return

    _set_label_text("connection_status", "Backend connected")
    if show_notification:
        ui.notify("Backend connected", type="positive")
    refresh_all()


def inject_entry_event() -> None:
    symbol = str(ui_refs["entry_symbol"].value or "").strip().upper()
    product = str(ui_refs["entry_product"].value or "").strip().upper()
    quantity_value = ui_refs["entry_quantity"].value
    price_value = ui_refs["entry_price"].value

    if not symbol or not product or quantity_value is None or price_value is None:
        ui.notify("Entry requires symbol, stock name, quantity, and average price.", type="negative")
        return
    if int(quantity_value) <= 0 or float(price_value) <= 0:
        ui.notify("Entry quantity and average price must be greater than zero.", type="negative")
        return

    payload = {
        "symbol": symbol,
        "product": product,
        "quantity": int(quantity_value),
        "average_price": float(price_value),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    status, body = api_request("POST", "/mock/events/entry", json=payload)
    if status == 200:
        ui.notify("Entry event injected", type="positive")
        refresh_all()
    else:
        show_api_error(status, body)


def inject_exit_event() -> None:
    symbol = str(ui_refs["exit_symbol"].value or "").strip().upper()
    product = str(ui_refs["exit_product"].value or "").strip().upper()
    price_value = ui_refs["exit_price"].value
    pnl_value = ui_refs["exit_pnl"].value

    if not symbol or not product or price_value is None or pnl_value is None:
        ui.notify("Exit requires symbol, stock name, exit average price, and P&L.", type="negative")
        return
    if float(price_value) <= 0:
        ui.notify("Exit average price must be greater than zero.", type="negative")
        return

    payload = {
        "symbol": symbol,
        "product": product,
        "average_price": float(price_value),
        "pnl": float(pnl_value),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    status, body = api_request("POST", "/mock/events/exit", json=payload)
    if status == 200:
        ui.notify("Exit event injected", type="positive")
        refresh_all()
    else:
        show_api_error(status, body)


def reset_mock_state() -> None:
    keep_tags = bool(ui_refs["reset_keep_tags"].value)
    status, body = api_request("POST", f"/mock/events/reset?keep_tags={str(keep_tags).lower()}")
    if status == 200:
        ui.notify("Mock state reset", type="positive")
        clear_capture_state()
        refresh_all()
    else:
        show_api_error(status, body)


def create_custom_tag() -> None:
    tag_name = str(ui_refs["custom_tag_name"].value or "").strip()
    category = str(ui_refs["custom_tag_category"].value or "").strip()
    payload = {"name": tag_name, "category": category or None}
    status, body = api_request("POST", "/tags/custom", json=payload)
    if status in (200, 201):
        ui.notify("Custom tag created", type="positive")
        ui_refs["custom_tag_name"].value = ""
        ui_refs["custom_tag_category"].value = ""
        refresh_all()
    else:
        show_api_error(status, body)


ui.label("LogX Functional POC (NiceGUI)").classes("text-2xl font-bold")

with ui.row().classes("w-full items-start gap-6"):
    with ui.column().classes("w-80"):
        ui.label("Control Panel").classes("text-lg font-semibold")
        ui_refs["api_base_input"] = ui.input("API Base URL", value=state.api_base).classes("w-full")
        ui.button("Connect Backend", on_click=lambda: connect_backend(show_notification=True)).classes("w-full")
        ui_refs["connection_status"] = ui.label("Connecting...").classes("text-sm")
        ui.separator()
        ui.label("Custom Tags").classes("text-md font-semibold")
        ui_refs["custom_tag_name"] = ui.input("Tag name").classes("w-full")
        ui_refs["custom_tag_category"] = ui.input("Category (optional)").classes("w-full")
        ui.button("Create Custom Tag", on_click=create_custom_tag).classes("w-full")
        ui_refs["custom_tags_container"] = ui.column().classes("w-full gap-1")

    with ui.column().classes("flex-1"):
        with ui.tabs().classes("w-full") as tabs:
            tab_sim = ui.tab("Simulator")
            tab_queue = ui.tab("Pending Queue")
            tab_journeys = ui.tab("Journeys")
            tab_events = ui.tab("Event History")

        with ui.tab_panels(tabs, value=tab_sim).classes("w-full"):
            with ui.tab_panel(tab_sim):
                with ui.row().classes("w-full gap-4"):
                    with ui.card().classes("w-full"):
                        ui.label("Inject Mock Entry").classes("text-lg font-semibold")
                        ui_refs["entry_symbol"] = ui.input("Symbol").classes("w-full")
                        ui_refs["entry_product"] = ui.input("Stock name").classes("w-full")
                        ui_refs["entry_quantity"] = ui.number("Net quantity", min=1, step=1).classes("w-full")
                        ui_refs["entry_price"] = ui.number("Average price", min=0.01, step=0.05).classes("w-full")
                        ui.button("Inject Entry Event", on_click=inject_entry_event)

                    with ui.card().classes("w-full"):
                        ui.label("Inject Mock Exit").classes("text-lg font-semibold")
                        ui_refs["exit_symbol"] = ui.input("Symbol").classes("w-full")
                        ui_refs["exit_product"] = ui.input("Stock name").classes("w-full")
                        ui_refs["exit_price"] = ui.number("Exit average price", min=0.01, step=0.05).classes("w-full")
                        ui_refs["exit_pnl"] = ui.number("P&L", step=10.0).classes("w-full")
                        ui.button("Inject Exit Event", on_click=inject_exit_event)

                with ui.card().classes("w-full mt-4"):
                    ui.label("Reset Mock State").classes("text-lg font-semibold")
                    ui_refs["reset_keep_tags"] = ui.checkbox("Keep custom tags during reset", value=True)
                    ui.button("Reset Trades, Nodes, Events", on_click=reset_mock_state)

            with ui.tab_panel(tab_queue):
                with ui.row().classes("w-full gap-4"):
                    with ui.column().classes("w-1/2"):
                        ui.label("Waiting for entry mindset").classes("text-lg font-semibold")
                        ui_refs["pending_entry_container"] = ui.column().classes("w-full gap-2")
                    with ui.column().classes("w-1/2"):
                        ui.label("Waiting for exit mindset").classes("text-lg font-semibold")
                        ui_refs["pending_exit_container"] = ui.column().classes("w-full gap-2")

            with ui.tab_panel(tab_journeys):
                ui.label("Completed Journeys").classes("text-lg font-semibold")
                ui_refs["journeys_container"] = ui.column().classes("w-full gap-2")

            with ui.tab_panel(tab_events):
                ui.label("Mock Event History").classes("text-lg font-semibold")
                ui_refs["events_container"] = ui.column().classes("w-full gap-2")

        ui.separator()
        ui.label("Node Capture").classes("text-xl font-semibold")
        ui_refs["capture_container"] = ui.column().classes("w-full gap-2")


connect_backend(show_notification=False)

# Keep UI synced with backend events and user interactions without manual refresh.
ui.timer(4.0, periodic_refresh)

ui.run(title="LogX NiceGUI", port=8080, reload=False)
