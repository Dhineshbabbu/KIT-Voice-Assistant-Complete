import json
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from app.config import settings
from app.college import CollegeClient

SYSTEM = """You are the concise, helpful voice assistant for Knotopian Institute of Technology (KIT).
Use API tools for live data. Never invent dates, attendance, grades, timetable, request status,
placement eligibility, seats, or approvals. Never claim a write action succeeded unless the API
confirmed it. Public visitors can only use public information. Student and teacher data is limited
to the currently authenticated user and their authorized role. Never ask for another person's
credentials or retrieve another student's private records. For requests that change data, explain
that the user must review and confirm the action in the app's confirmation panel. If a question
cannot be answered by the API, say so clearly. Keep spoken answers natural and brief."""

def build_agent(context):
    client = CollegeClient(context.get("college_token"))
    role = context.get("role", "public")
    authenticated = bool(context.get("college_token"))
    tools = []

    @tool
    async def college_profile() -> str:
        """Fetch the official KIT profile, contact information and description."""
        return json.dumps(await CollegeClient().college(), ensure_ascii=False)

    @tool
    async def list_courses() -> str:
        """Fetch admission courses, fees, eligibility and available seats."""
        return json.dumps(await CollegeClient().courses(), ensure_ascii=False)

    @tool
    async def current_college_date() -> str:
        """Fetch KIT's current date and weekday."""
        return json.dumps(await CollegeClient().today(), ensure_ascii=False)

    @tool
    async def list_calendar_events(from_date: str = "", to_date: str = "") -> str:
        """Fetch holidays, exams and calendar events. Dates use YYYY-MM-DD; leave blank for API defaults."""
        return json.dumps(await client.calendar(from_date or None, to_date or None), ensure_ascii=False)

    @tool
    async def list_placement_drives() -> str:
        """Fetch current placement drives, eligibility, deadlines and seats."""
        return json.dumps(await CollegeClient().placement_drives(), ensure_ascii=False)

    tools += [college_profile, list_courses, current_college_date, list_placement_drives]

    if authenticated and role == "student":
        @tool
        async def my_profile_and_academics() -> str:
            """Fetch the current student's profile and academic summary."""
            a, b = await client.me(), await client.academics()
            return json.dumps({"profile":a,"academics":b}, ensure_ascii=False)

        @tool
        async def my_attendance() -> str:
            """Fetch attendance summary for the currently logged-in student."""
            return json.dumps(await client.attendance(), ensure_ascii=False)

        @tool
        async def my_subjects_and_timetable() -> str:
            """Fetch the student's subjects and weekly timetable."""
            a, b = await client.subjects(), await client.timetable()
            return json.dumps({"subjects":a,"timetable":b}, ensure_ascii=False)

        @tool
        async def my_leave_and_od_requests() -> str:
            """Fetch the current student's leave and on-duty request history."""
            return json.dumps(await client.student_requests(), ensure_ascii=False)

        @tool
        async def my_placement_registrations() -> str:
            """Fetch placement drives the current student has registered for."""
            return json.dumps(await client.my_placements(), ensure_ascii=False)
        
        @tool
        async def prepare_leave_or_od_request(
            request_type: str,
            from_date: str,
            to_date: str,
            reason: str,
            event_name: str = "",
            half_day: bool = False
        ) -> str:
            """
            Prepare a student leave or on-duty request.

            request_type must be personal_leave, medical_leave or on_duty.
            Dates must use YYYY-MM-DD.
            event_name is mandatory for on_duty.
            Prepare the request for user confirmation; do not submit it directly.
            """

            if request_type not in ["personal_leave", "medical_leave", "on_duty"]:
                return "Invalid request type."

            if request_type == "on_duty" and not event_name:
                return "Please provide the event name."

            payload = {
                "type": request_type,
                "from_date": from_date,
                "to_date": to_date,
                "half_day": half_day,
                "reason": reason,
                "event_name": event_name or None
            }

            return json.dumps({
                "action": "prepare_confirmation",
                "endpoint": "POST /v1/me/requests",
                "payload": payload,
                "message": "Request prepared. Please review and confirm in the application."
            })
        
        @tool
        async def prepare_placement_registration(drive_id: int) -> str:
            """
            Prepare registration for a placement drive.

            First verify the drive exists and check the student's
            eligibility. Prepare the registration for user confirmation.
            Do not register directly.
            """

            drives = await client.placement_drives()

            if isinstance(drives, dict):
                drives = drives.get("items", drives.get("drives", []))

            drive = next(
                (d for d in drives if int(d["id"]) == drive_id),
                None
            )

            if not drive:
                return f"Placement drive {drive_id} was not found."

            return json.dumps({
                "action": "prepare_confirmation",
                "endpoint": f"POST /v1/placements/drives/{drive_id}/register",
                "payload": {},
                "drive": drive,
                "message": "Review the placement drive and confirm registration in the application."
            }, ensure_ascii=False)

        tools += [my_profile_and_academics, my_attendance, my_subjects_and_timetable,
                  my_leave_and_od_requests, my_placement_registrations,list_calendar_events,
                  prepare_leave_or_od_request,prepare_placement_registration]

        

    if authenticated and role == "teacher":
        @tool
        async def my_teaching_classes() -> str:
            """Fetch classes assigned to the logged-in teacher."""
            return json.dumps(await client.teacher_classes(), ensure_ascii=False)

        @tool
        async def student_requests_for_review(status: str = "pending") -> str:
            """Fetch student leave/OD requests for the teacher. Optional status filter."""
            return json.dumps(await client.teacher_requests(status or None), ensure_ascii=False)

        @tool
        async def prepare_approve_request(
            request_id: int,
            comment: str = ""
        ) -> str:
            """
            Prepare approval of a student leave or OD request.
            Retrieve the request first and prepare it for confirmation.
            Never approve without explicit teacher confirmation.
            """

            requests = await client.teacher_requests("pending")

            if isinstance(requests, dict):
                requests = requests.get("items", requests.get("requests", []))

            request = next(
                (r for r in requests if int(r["id"]) == request_id),
                None
            )

            if not request:
                return f"Pending request {request_id} was not found."

            return json.dumps({
                "action": "prepare_confirmation",
                "endpoint": f"/v1/teacher/requests/{request_id}/approve",
                "method": "POST",
                "payload": {"comment": comment} if comment else {},
                "request_details": request,
                "message": "Approval prepared. Awaiting teacher confirmation."
            }, ensure_ascii=False)

        @tool
        async def prepare_reject_request(
            request_id: int,
            reason: str
        ) -> str:
            """
            Prepare rejection of a student leave or on-duty request.
            A rejection reason is mandatory.
            Ask for teacher confirmation before submitting.
            """

            if not reason.strip():
                return "A rejection reason is required."

            requests = await client.teacher_requests("pending")

            if isinstance(requests, dict):
                requests = requests.get("items", requests.get("requests", []))

            request = next(
                (r for r in requests if int(r["id"]) == request_id),
                None
            )

            if not request:
                return f"Pending request {request_id} was not found."

            return json.dumps({
                "action": "prepare_confirmation",
                "method": "POST",
                "endpoint": f"/v1/teacher/requests/{request_id}/reject",
                "payload": {
                    "reason": reason
                },
                "request_details": request
            }, ensure_ascii=False)

        tools += [my_teaching_classes, student_requests_for_review, list_calendar_events, prepare_approve_request, prepare_reject_request]

    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")
    llm = ChatGroq(api_key=settings.groq_api_key, model=settings.groq_model, temperature=0)
    return create_react_agent(llm, tools, prompt=SYSTEM)

async def run_agent(message, context):
    agent = build_agent(context)
    prior = context.get("history", [])
    msgs = [{"role": m["role"], "content": m["content"]} for m in prior[-12:] if m["role"] in ("user","assistant")]
    msgs.append({"role":"user","content":message})
    result = await agent.ainvoke({"messages":msgs})
    content = result["messages"][-1].content
    if isinstance(content, list):
        content = " ".join(str(x.get("text","")) for x in content if isinstance(x,dict))
    return str(content)
