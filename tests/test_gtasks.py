import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_service():
    svc = MagicMock()
    tasklists = MagicMock()
    tasklists.list.return_value.execute.return_value = {
        "items": [{"id": "list1", "title": "My Tasks"}]
    }
    tasks_res = MagicMock()
    tasks_res.list.return_value.execute.return_value = {
        "items": [
            {"id": "t1", "title": "Buy milk", "status": "needsAction", "notes": ""},
        ]
    }
    tasks_res.insert.return_value.execute.return_value = {"id": "t2", "title": "New task"}
    tasks_res.get.return_value.execute.return_value = {
        "id": "t1", "title": "Buy milk", "status": "needsAction"
    }
    tasks_res.update.return_value.execute.return_value = {
        "id": "t1", "title": "Buy milk", "status": "completed"
    }
    svc.tasklists.return_value = tasklists
    svc.tasks.return_value = tasks_res
    return svc


def test_list_tasks(mock_service):
    with patch("src.integrations.gtasks.build_google_service", return_value=mock_service):
        from src.integrations.gtasks import GoogleTasks
        gt = GoogleTasks()
        result = gt.list_tasks()
        assert len(result) == 1
        assert result[0]["title"] == "Buy milk"
        assert result[0]["id"] == "t1"


def test_create_task(mock_service):
    with patch("src.integrations.gtasks.build_google_service", return_value=mock_service):
        from src.integrations.gtasks import GoogleTasks
        gt = GoogleTasks()
        result = gt.create_task("New task", notes="Some notes")
        assert result["id"] == "t2"


def test_complete_task(mock_service):
    with patch("src.integrations.gtasks.build_google_service", return_value=mock_service):
        from src.integrations.gtasks import GoogleTasks
        gt = GoogleTasks()
        result = gt.complete_task("t1")
        assert result["status"] == "completed"
