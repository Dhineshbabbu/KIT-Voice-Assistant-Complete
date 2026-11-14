
import json
from datetime import date

from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.config import settings
from app.college import CollegeClient


SYSTEM = """
You are the voice assistant for Knotopian Institute of Technology (KIT).

CORE RULES:
1. Always use tools for live KIT information.
2. Never invent attendance, marks, grades, dates, events,
   timetable, placement eligibility, or request status.
3. Only access the currently authenticated user's data.
4. Public visitors must never access student or teacher data.
5. Students must never use teacher tools.
6. Teachers must never use student-specific tools.
7. Never claim that an action succeeded unless the KIT API confirms it.
8. All write actions require explicit user confirmation.
9. Explain when information is unavailable from the KIT API.
10. Keep spoken answers concise and natural.

TOOL USAGE:
- Use attendance_sessions for detailed attendance questions.
- Use calendar tools for holidays and examination dates.
- Use class_attendance for teacher class attendance.
- Check placement drives before preparing a registration.
- Retrieve a request before preparing its cancellation.
- Retrieve pending teacher requests before preparing approval/rejection.
- Do not assume that a student is eligible for a placement drive.
- Do not execute write operations directly.
"""


def encode(data):
    return json.dumps(data, ensure_ascii=False, default=str)


def normalize_list(data, *keys):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value

    return []


def build_agent(context):
    token = context.get("college_token")
    role = context.get("role", "public")
    authenticated = bool(token)

    client = CollegeClient(token)
    public_client = CollegeClient()

    tools = []

    # --------------------------------------------------
    # PUBLIC TOOLS
    # --------------------------------------------------

    @tool
    async def college_profile() -> str:
        """Get official KIT college profile and contact information."""
        return encode(await public_client.college())

    @tool
    async def list_courses() -> str:
        """Get admission courses, fees, eligibility and seat information."""
        return encode(await public_client.courses())

    @tool
    async def current_college_date() -> str:
        """Get KIT's current date and weekday."""
        return encode(await public_client.today())

    @tool
    async def list_calendar_events(
        from_date: str = "",
        to_date: str = ""
    ) -> str:
        """Get holidays, examinations and college calendar events.
        Dates should use YYYY-MM-DD.
        """
        return encode(
            await public_client.calendar(
                from_date or None,
                to_date or None
            )
        )

    @tool
    async def list_placement_drives() -> str:
        """Get available placement drives and their eligibility criteria."""
        return encode(await public_client.placement_drives())

    @tool
    async def list_college_documents() -> str:
        """List official KIT documents available through the college API."""
        return encode(await public_client.documents())

    tools.extend([
        college_profile,
        list_courses,
        current_college_date,
        list_calendar_events,
        list_placement_drives,
        list_college_documents,
    ])

    # --------------------------------------------------
    # PUBLIC ADMISSION APPLICATION
    # --------------------------------------------------

    if role == "public":

        @tool
        async def prepare_admission_application(
            full_name: str,
            phone: str,
            email: str,
            course_code: str,
            twelfth_percent: float
        ) -> str:
            """
            Prepare an admission application.
            Never submit directly. Ask the user to review and confirm.
            """
            payload = {
                "full_name": full_name,
                "phone": phone,
                "email": email,
                "course_code": course_code,
                "twelfth_percent": twelfth_percent
            }

            return encode({
                "action": "prepare_confirmation",
                "action_type": "admission_application",
                "payload": payload,
                "message": "Admission application prepared. Review and confirm before submission."
            })

        tools.append(prepare_admission_application)

    # --------------------------------------------------
    # STUDENT TOOLS
    # --------------------------------------------------

    if authenticated and role == "student":

        @tool
        async def my_profile_and_academics() -> str:
            """Get the current student's profile and academic summary."""
            profile, academics = await client.me(), await client.academics()

            return encode({
                "profile": profile,
                "academics": academics
            })

        @tool
        async def my_attendance() -> str:
            """Get the current student's overall attendance summary."""
            return encode(await client.attendance())

        @tool
        async def my_attendance_sessions(
            subject: str = "",
            from_date: str = "",
            to_date: str = ""
        ) -> str:
            """Get detailed attendance sessions, optionally filtered by subject and dates."""
            return encode(
                await client.attendance_sessions(
                    subject or None,
                    from_date or None,
                    to_date or None
                )
            )

        @tool
        async def my_subjects_and_timetable() -> str:
            """Get registered subjects and weekly timetable."""
            subjects = await client.subjects()
            timetable = await client.timetable()

            return encode({
                "subjects": subjects,
                "timetable": timetable
            })

        @tool
        async def my_leave_and_od_requests() -> str:
            """Get the current student's leave and on-duty request history."""
            return encode(await client.student_requests())

        @tool
        async def my_request_details(request_id: int) -> str:
            """Get details of one of the current student's requests."""
            return encode(await client.request_detail(request_id))

        @tool
        async def my_placement_registrations() -> str:
            """Get placement drives registered by the current student."""
            return encode(await client.my_placements())

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
            Prepare a personal leave, medical leave or on-duty request.
            Do not submit directly. Ask for confirmation.
            """
            if request_type not in {
                "personal_leave",
                "medical_leave",
                "on_duty"
            }:
                return "Invalid request type."

            if not reason.strip():
                return "A reason is required."

            if request_type == "on_duty" and not event_name.strip():
                return "An event name is required for on-duty requests."

            try:
                start = date.fromisoformat(from_date)
                end = date.fromisoformat(to_date)
                if end < start:
                    return "The end date cannot be before the start date."
            except ValueError:
                return "Please provide dates in YYYY-MM-DD format."

            payload = {
                "type": request_type,
                "from_date": from_date,
                "to_date": to_date,
                "half_day": half_day,
                "reason": reason,
                "event_name": event_name or None
            }

            return encode({
                "action": "prepare_confirmation",
                "action_type": "leave_od_request",
                "payload": payload,
                "message": "Review the leave/OD request and confirm before submission."
            })

        @tool
        async def prepare_cancel_request(request_id: int) -> str:
            """Retrieve a student's request and prepare its cancellation for confirmation."""
            request = await client.request_detail(request_id)

            return encode({
                "action": "prepare_confirmation",
                "action_type": "cancel_student_request",
                "payload": {"id": request_id},
                "request_details": request,
                "message": "Review this request and confirm cancellation."
            })

        @tool
        async def prepare_placement_registration(drive_id: int) -> str:
            """
            Check that a placement drive exists and prepare registration.
            Do not claim eligibility unless the API provides sufficient information.
            Ask for confirmation before registration.
            """
            drives = normalize_list(
                await client.placement_drives(),
                "items",
                "drives"
            )

            drive = next(
                (
                    item for item in drives
                    if str(item.get("id")) == str(drive_id)
                ),
                None
            )

            if not drive:
                return f"Placement drive {drive_id} was not found."

            return encode({
                "action": "prepare_confirmation",
                "action_type": "placement_register",
                "payload": {"id": drive_id},
                "drive": drive,
                "message": "Review the placement drive and confirm registration."
            })

        tools.extend([
            my_profile_and_academics,
            my_attendance,
            my_attendance_sessions,
            my_subjects_and_timetable,
            my_leave_and_od_requests,
            my_request_details,
            my_placement_registrations,
            prepare_leave_or_od_request,
            prepare_cancel_request,
            prepare_placement_registration,
        ])

    # --------------------------------------------------
    # TEACHER TOOLS
    # --------------------------------------------------

    if authenticated and role == "teacher":

        @tool
        async def my_teaching_classes() -> str:
            """Get all classes assigned to the authenticated teacher."""
            return encode(await client.teacher_classes())

        @tool
        async def class_attendance(class_id: str) -> str:
            """Get attendance records for a class assigned to this teacher."""
            return encode(await client.class_attendance(class_id))

        @tool
        async def student_requests_for_review(
            status: str = "pending"
        ) -> str:
            """Get student leave and OD requests for teacher review."""
            return encode(
                await client.teacher_requests(status or None)
            )

        @tool
        async def prepare_approve_request(
            request_id: int,
            comment: str = ""
        ) -> str:
            """Retrieve a pending request and prepare approval for teacher confirmation."""
            requests = normalize_list(
                await client.teacher_requests("pending"),
                "items",
                "requests"
            )

            request = next(
                (
                    item for item in requests
                    if str(item.get("id")) == str(request_id)
                ),
                None
            )

            if not request:
                return f"Pending request {request_id} was not found."

            return encode({
                "action": "prepare_confirmation",
                "action_type": "teacher_approve",
                "payload": {
                    "id": request_id,
                    "comment": comment
                },
                "request_details": request,
                "message": "Review the request and confirm approval."
            })

        @tool
        async def prepare_reject_request(
            request_id: int,
            reason: str
        ) -> str:
            """Retrieve a pending request and prepare rejection for confirmation."""
            if not reason.strip():
                return "A rejection reason is required."

            requests = normalize_list(
                await client.teacher_requests("pending"),
                "items",
                "requests"
            )

            request = next(
                (
                    item for item in requests
                    if str(item.get("id")) == str(request_id)
                ),
                None
            )

            if not request:
                return f"Pending request {request_id} was not found."

            return encode({
                "action": "prepare_confirmation",
                "action_type": "teacher_reject",
                "payload": {
                    "id": request_id,
                    "reason": reason
                },
                "request_details": request,
                "message": "Review the request and confirm rejection."
            })

        tools.extend([
            my_teaching_classes,
            class_attendance,
            student_requests_for_review,
            prepare_approve_request,
            prepare_reject_request,
        ])

    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0
    )

    return create_react_agent(
        llm,
        tools,
        prompt=SYSTEM
    )


async def run_agent(message, context):
    agent = build_agent(context)

    prior = context.get("history", [])

    messages = [
        {
            "role": item["role"],
            "content": item["content"]
        }
        for item in prior[-12:]
        if item.get("role") in ("user", "assistant")
    ]

    messages.append({
        "role": "user",
        "content": message
    })

    result = await agent.ainvoke({
        "messages": messages
    })

    content = result["messages"][-1].content

    if isinstance(content, list):
        content = " ".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict)
        )

    return str(content)

