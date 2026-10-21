import json
import stat
from unittest.mock import patch

from label_studio_mcp import mcp_server


class FakeAnnotation:
    def __init__(self, annotation_id, result):
        self.annotation_id = annotation_id
        self.result = result
        self.completed_by = 7
        self.created_at = "2026-10-21T10:00:00Z"
        self.updated_at = "2026-10-21T10:05:00Z"
        self.was_cancelled = False

    def model_dump(self):
        return {
            "id": self.annotation_id,
            "completed_by": self.completed_by,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "was_cancelled": self.was_cancelled,
        }


class FakeTask:
    def __init__(self, task_id, data, annotations):
        self.id = task_id
        self.data = data
        self._annotations = annotations

    def get_annotations(self):
        return self._annotations


class FakeTasks:
    def __init__(self, tasks):
        self._tasks = tasks

    def list(self, project):
        return self._tasks


class FakeProject:
    id = 1
    title = "Generative UI review"
    task_number = 2


class FakeProjects:
    def get(self, id):
        return FakeProject()


class FakeLabelStudio:
    def __init__(self):
        self.projects = FakeProjects()
        self.tasks = FakeTasks([
            FakeTask(
                101,
                {
                    "eval_case_id": "invoice-overdue",
                    "trace_id": "trace-1",
                    "prompt": "Show overdue invoices.",
                },
                [
                    FakeAnnotation(
                        1,
                        [
                            {
                                "from_name": "open_coding",
                                "to_name": "prompt",
                                "type": "textarea",
                                "value": {"text": ["The plan is correct."]},
                            },
                            {
                                "from_name": "pass_fail",
                                "to_name": "prompt",
                                "type": "choices",
                                "value": {"choices": ["Pass"]},
                            },
                        ],
                    )
                ],
            ),
            FakeTask(
                102,
                {
                    "eval_case_id": "invoice-detail",
                    "trace_id": "trace-2",
                    "prompt": "Show invoice INV-1001.",
                },
                [
                    FakeAnnotation(
                        2,
                        [
                            {
                                "from_name": "reasoning_quality",
                                "to_name": "prompt",
                                "type": "rating",
                                "value": {"rating": 4},
                            }
                        ],
                    )
                ],
            ),
        ])


def test_exports_tasks_and_annotations(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.EXPORT_DIR_ENV, str(tmp_path))
    output = tmp_path / "feedback.json"

    with patch.object(mcp_server, "ls", FakeLabelStudio()):
        result = mcp_server.export_label_studio_project_annotations_tool(
            project_id=1,
            output_path="feedback.json",
        )

    summary = json.loads(result)
    assert summary["task_count"] == 2
    assert summary["annotation_count"] == 2
    assert summary["truncated"] is False
    assert summary["path"] == str(output.resolve())
    assert summary["file_name"] == "feedback.json"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["project_id"] == 1
    assert payload["project_title"] == "Generative UI review"
    assert payload["task_count"] == 2
    assert payload["annotation_count"] == 2
    assert payload["tasks"][0]["eval_case_id"] == "invoice-overdue"
    assert payload["tasks"][0]["data"]["trace_id"] == "trace-1"
    assert payload["tasks"][0]["annotations"][0]["result"][0]["from_name"] == "open_coding"
    assert payload["tasks"][1]["eval_case_id"] == "invoice-detail"
    assert payload["tasks"][1]["annotations"][0]["result"][0]["from_name"] == "reasoning_quality"


def test_rejects_invalid_max_tasks():
    with patch.object(mcp_server, "ls", FakeLabelStudio()):
        result = mcp_server.export_label_studio_project_annotations_tool(
            project_id=1,
            max_tasks=0,
        )

    assert "error" in json.loads(result)


def test_rejects_paths_outside_the_export_directory(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.EXPORT_DIR_ENV, str(tmp_path / "exports"))

    with patch.object(mcp_server, "ls", FakeLabelStudio()):
        for value in ("../escape.json", "/tmp/escape.json", "sub/escape.json", "..", ""):
            result = mcp_server.export_label_studio_project_annotations_tool(
                project_id=1,
                output_path=value,
            )
            assert "error" in json.loads(result), value

    assert not (tmp_path / "escape.json").exists()


def test_does_not_overwrite_an_existing_file(tmp_path, monkeypatch):
    base = tmp_path / "exports"
    base.mkdir()
    target = base / "feedback.json"
    target.write_text("keep", encoding="utf-8")
    monkeypatch.setenv(mcp_server.EXPORT_DIR_ENV, str(base))

    with patch.object(mcp_server, "ls", FakeLabelStudio()):
        result = mcp_server.export_label_studio_project_annotations_tool(
            project_id=1,
            output_path="feedback.json",
        )

    assert "already exists" in json.loads(result)["error"]
    assert target.read_text(encoding="utf-8") == "keep"


def test_stops_at_the_byte_budget(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.EXPORT_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(mcp_server, "MAX_EXPORT_BYTES", 10)

    with patch.object(mcp_server, "ls", FakeLabelStudio()):
        result = mcp_server.export_label_studio_project_annotations_tool(
            project_id=1,
            output_path="feedback.json",
        )

    summary = json.loads(result)
    assert summary["task_count"] == 0
    assert summary["truncated"] is True


def test_stops_at_the_annotation_budget(tmp_path, monkeypatch):
    monkeypatch.setenv(mcp_server.EXPORT_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(mcp_server, "MAX_EXPORT_ANNOTATIONS", 1)

    with patch.object(mcp_server, "ls", FakeLabelStudio()):
        result = mcp_server.export_label_studio_project_annotations_tool(
            project_id=1,
            output_path="feedback.json",
        )

    summary = json.loads(result)
    assert summary["task_count"] == 1
    assert summary["annotation_count"] == 1
    assert summary["truncated"] is True
