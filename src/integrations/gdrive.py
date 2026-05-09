from .google_auth import build_google_service


class GoogleDrive:
    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("drive", "v3")
        return self._service

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        res = self._svc().files().list(
            q=query,
            pageSize=max_results,
            fields="files(id,name,mimeType,webViewLink,modifiedTime)",
        ).execute()
        return [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "type": f.get("mimeType"),
                "link": f.get("webViewLink"),
                "modified": f.get("modifiedTime"),
            }
            for f in res.get("files", [])
        ]

    def list_recent(self, max_results: int = 10) -> list[dict]:
        res = self._svc().files().list(
            q="trashed=false",
            orderBy="modifiedTime desc",
            pageSize=max_results,
            fields="files(id,name,mimeType,webViewLink,modifiedTime)",
        ).execute()
        return [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "type": f.get("mimeType"),
                "link": f.get("webViewLink"),
                "modified": f.get("modifiedTime"),
            }
            for f in res.get("files", [])
        ]

    def get_file_metadata(self, file_id: str) -> dict:
        f = self._svc().files().get(
            fileId=file_id,
            fields="id,name,mimeType,webViewLink,modifiedTime,description",
        ).execute()
        return {
            "id": f.get("id"),
            "name": f.get("name"),
            "type": f.get("mimeType"),
            "link": f.get("webViewLink"),
            "modified": f.get("modifiedTime"),
            "description": f.get("description", ""),
        }


gdrive = GoogleDrive()
