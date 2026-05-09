from typing import Optional
from .google_auth import build_google_service


class GoogleTasks:
    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("tasks", "v1")
        return self._service

    def _get_default_list_id(self) -> str:
        result = self._svc().tasklists().list(maxResults=1).execute()
        items = result.get("items", [])
        return items[0]["id"] if items else "@default"

    def list_tasks(self, max_results: int = 20, show_completed: bool = False) -> list[dict]:
        list_id = self._get_default_list_id()
        result = self._svc().tasks().list(
            tasklist=list_id,
            maxResults=max_results,
            showCompleted=show_completed,
            showHidden=False,
        ).execute()
        return [
            {
                "id": t.get("id"),
                "title": t.get("title", ""),
                "notes": t.get("notes", ""),
                "status": t.get("status"),
                "due": t.get("due"),
            }
            for t in result.get("items", [])
        ]

    def create_task(
        self, title: str, notes: str = "", due: Optional[str] = None
    ) -> dict:
        list_id = self._get_default_list_id()
        body: dict = {"title": title, "notes": notes}
        if due:
            body["due"] = due
        return self._svc().tasks().insert(tasklist=list_id, body=body).execute()

    def complete_task(self, task_id: str) -> dict:
        list_id = self._get_default_list_id()
        task = self._svc().tasks().get(tasklist=list_id, task=task_id).execute()
        task["status"] = "completed"
        return self._svc().tasks().update(
            tasklist=list_id, task=task_id, body=task
        ).execute()

    def delete_task(self, task_id: str):
        list_id = self._get_default_list_id()
        self._svc().tasks().delete(tasklist=list_id, task=task_id).execute()


gtasks = GoogleTasks()
