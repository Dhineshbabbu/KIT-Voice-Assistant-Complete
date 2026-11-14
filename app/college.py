import uuid
import httpx
from app.config import settings

class CollegeAPIError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code

class CollegeClient:
    """Thin typed wrapper around the challenge API. Participant key is sent on every call."""
    def __init__(self, token=None):
        self.base = settings.college_api_url.rstrip("/")
        self.token = token

    def headers(self, idempotency=False):
        if not settings.college_participant_key:
            raise CollegeAPIError("COLLEGE_PARTICIPANT_KEY is missing on the server.", 503)
        headers = {"X-Participant-Key": settings.college_participant_key}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if idempotency:
            headers["Idempotency-Key"] = str(uuid.uuid4())
        return headers

    async def request(self, method, path, *, params=None, body=None, idempotency=False, expect_pdf=False):
        url = self.base + (path if path.startswith("/") else "/" + path)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0), follow_redirects=True) as client:
                response = await client.request(method, url, headers=self.headers(idempotency),
                                                params=params, json=body)
        except httpx.HTTPError as exc:
            raise CollegeAPIError(f"Could not reach KIT API: {exc}", 502) from exc
        if response.is_error:
            try: detail = response.json()
            except Exception: detail = response.text[:1500]
            raise CollegeAPIError(f"KIT API returned {response.status_code}: {detail}", response.status_code)
        if expect_pdf:
            return response.content, response.headers.get("content-type", "application/pdf")
        if not response.content:
            return {"ok": True}
        try: return response.json()
        except Exception: return {"raw": response.text[:2000]}

    # Public endpoints
    async def health(self): return await self.request("GET", "/v1/health")
    async def today(self): return await self.request("GET", "/v1/today")
    async def college(self): return await self.request("GET", "/v1/college")
    async def courses(self): return await self.request("GET", "/v1/courses")
    async def documents(self): return await self.request("GET", "/v1/documents")
    async def document_file(self, doc_id): return await self.request("GET", f"/v1/documents/{doc_id}/file", expect_pdf=True)
    async def admission(self, payload): return await self.request("POST", "/v1/admissions/applications", body=payload, idempotency=True)
    async def login(self, login_id, password):
        return await self.request("POST", "/v1/auth/login", body={"login_id": login_id, "password": password})

    # Authenticated student endpoints
    async def me(self): return await self.request("GET", "/v1/me")
    async def academics(self): return await self.request("GET", "/v1/me/academics")
    async def subjects(self): return await self.request("GET", "/v1/me/subjects")
    async def timetable(self): return await self.request("GET", "/v1/me/timetable")
    async def calendar(self, from_date=None, to_date=None):
        return await self.request("GET", "/v1/calendar", params={k:v for k,v in {"from":from_date,"to":to_date}.items() if v})
    async def attendance(self): return await self.request("GET", "/v1/me/attendance")
    async def attendance_sessions(self, subject=None, from_date=None, to_date=None):
        return await self.request("GET", "/v1/me/attendance/sessions",
            params={k:v for k,v in {"subject":subject,"from":from_date,"to":to_date}.items() if v})
    async def student_requests(self): return await self.request("GET", "/v1/me/requests")
    async def create_request(self, payload): return await self.request("POST", "/v1/me/requests", body=payload, idempotency=True)
    async def request_detail(self, request_id): return await self.request("GET", f"/v1/me/requests/{request_id}")
    async def cancel_request(self, request_id): return await self.request("POST", f"/v1/me/requests/{request_id}/cancel")
    async def my_placements(self): return await self.request("GET", "/v1/me/placements")
    async def register_placement(self, drive_id): return await self.request("POST", f"/v1/placements/drives/{drive_id}/register")

    # Placement public endpoint
    async def placement_drives(self): return await self.request("GET", "/v1/placements/drives")

    # Teacher endpoints
    async def teacher_classes(self): return await self.request("GET", "/v1/teacher/classes")
    async def teacher_requests(self, status=None):
        return await self.request("GET", "/v1/teacher/requests", params={"status":status} if status else None)
    async def class_attendance(self, class_id):
        return await self.request("GET", f"/v1/teacher/classes/{class_id}/attendance")
    async def approve_request(self, request_id, comment=None):
        body = {"comment":comment} if comment else None
        return await self.request("POST", f"/v1/teacher/requests/{request_id}/approve", body=body)
    async def reject_request(self, request_id, reason):
        return await self.request("POST", f"/v1/teacher/requests/{request_id}/reject", body={"reason":reason})
