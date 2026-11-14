import json, uuid, base64
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
import httpx
from app.config import settings
from app.db import init_db, create_session, get_session, delete_session, add_message, history, save_pending_action, pop_pending_action
from app.college import CollegeClient, CollegeAPIError
from app.agent import run_agent
from app.rag import refresh_documents, search_documents
from io import BytesIO

app = FastAPI(title="KIT Voice Assistant", version="2.0.0",
              description="Role-aware voice assistant for KIT challenge API.")
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.on_event("startup")
def startup(): init_db()

@app.get("/", response_class=HTMLResponse)
async def home(): return Path("frontend/index.html").read_text(encoding="utf-8")

@app.get("/login", response_class=HTMLResponse)
async def login_page(): return Path("frontend/login.html").read_text(encoding="utf-8")

@app.get("/history", response_class=HTMLResponse)
async def history_page(): return Path("frontend/history.html").read_text(encoding="utf-8")

def current_user(request: Request):
    return get_session(request.cookies.get("kit_session"))

def require_user(request, roles=None):
    user=current_user(request)
    if not user: raise HTTPException(401,"Please sign in first.")
    if roles and user["role"] not in roles: raise HTTPException(403,"Your account role cannot perform this action.")
    return user

def api_error(exc):
    raise HTTPException(exc.status_code, str(exc))

class LoginBody(BaseModel):
    login_id: str
    password: str

@app.post("/api/login")
async def login(body: LoginBody, response: Response):
    try: data=await CollegeClient().login(body.login_id,body.password)
    except CollegeAPIError as e: api_error(e)
    token=data.get("access_token")
    if not token: raise HTTPException(502,"Login response did not include access_token.")
    user=data.get("user") or {}
    role=str(user.get("role","")).lower()
    if role not in {"student","teacher"}:
        # Do not infer privileges from login IDs. Unknown roles are denied.
        raise HTTPException(403,f"Unsupported account role returned by KIT API: {role or 'missing'}")
    sid=create_session(token,body.login_id,role,user,hours=int(data.get("expires_in",28800)//3600 or 8))
    response.set_cookie("kit_session",sid,httponly=True,secure=settings.session_cookie_secure,
                        samesite="lax",max_age=28800)
    return {"ok":True,"user":user,"role":role}

@app.post("/api/logout")
async def logout(request: Request,response: Response):
    delete_session(request.cookies.get("kit_session"))
    response.delete_cookie("kit_session")
    return {"ok":True}

@app.get("/api/me")
async def me(request: Request):
    u=current_user(request)
    return {"authenticated":bool(u),"user":u.get("user") if u else None,
            "login_id":u.get("login_id") if u else None,"role":u.get("role","public") if u else "public"}

class ChatBody(BaseModel):
    message: str = Field(min_length=1,max_length=5000)

@app.post("/api/chat")
async def chat(body: ChatBody, request: Request):
    u=current_user(request)
    sid=request.cookies.get("kit_session") or "public"
    add_message(sid,"user",body.message)
    try:
        hist=history(sid,limit=30)
        answer=await run_agent(body.message,{"college_token":u["college_token"] if u else None,
                                             "role":u["role"] if u else "public","history":hist[:-1]})
        # Optional document retrieval; context is only included when local PDF chunks match.
        docs=search_documents(body.message)
        if docs:
            answer += "\n\nFrom KIT documents: " + " ".join(d["text"][:500] for d in docs[:2])
    except Exception as e:
        answer=f"I couldn't complete that request: {str(e)[:500]}"
    add_message(sid,"assistant",answer)
    return {"answer":answer}

@app.get("/api/history")
async def get_history(request: Request):
    u=require_user(request)
    return {"messages":history(request.cookies.get("kit_session"))}

# Public information endpoints, proxy through backend so participant key stays secret.
@app.get("/api/public/{resource}")
async def public_resource(resource: str):
    mapping={"health":"health","today":"today","college":"college","courses":"courses",
             "documents":"documents","placements":"placement_drives"}
    if resource not in mapping: raise HTTPException(404,"Unknown public resource")
    try: return await getattr(CollegeClient(),mapping[resource])()
    except CollegeAPIError as e: api_error(e)

@app.get("/api/public/documents/{doc_id}/file")
async def document_file(doc_id: str):
    try: content,mime=await CollegeClient().document_file(doc_id)
    except CollegeAPIError as e: api_error(e)
    return StreamingResponse(BytesIO(content),media_type=mime,
                             headers={"Content-Disposition":f'attachment; filename="KIT-document-{doc_id}.pdf"'})

# Authenticated read APIs
@app.get("/api/student/profile")
async def student_profile(request: Request):
    u=require_user(request,["student"])
    try:
        c=CollegeClient(u["college_token"])
        a,b=await c.me(),await c.academics()
        return {"profile":a,"academics":b}
    except CollegeAPIError as e: api_error(e)

@app.get("/api/student/subjects")
async def student_subjects(request: Request):
    u=require_user(request,["student"])
    try: return await CollegeClient(u["college_token"]).subjects()
    except CollegeAPIError as e: api_error(e)

@app.get("/api/student/timetable")
async def student_timetable(request: Request):
    u=require_user(request,["student"])
    try: return await CollegeClient(u["college_token"]).timetable()
    except CollegeAPIError as e: api_error(e)

@app.get("/api/student/calendar")
async def student_calendar(request: Request, from_date: str|None=None, to_date: str|None=None):
    u=require_user(request)
    try: return await CollegeClient(u["college_token"]).calendar(from_date,to_date)
    except CollegeAPIError as e: api_error(e)

@app.get("/api/student/attendance")
async def student_attendance(request: Request):
    u=require_user(request,["student"])
    try: return await CollegeClient(u["college_token"]).attendance()
    except CollegeAPIError as e: api_error(e)

@app.get("/api/student/attendance/sessions")
async def student_attendance_sessions(request: Request, subject: str|None=None, from_date: str|None=None, to_date: str|None=None):
    u=require_user(request,["student"])
    try: return await CollegeClient(u["college_token"]).attendance_sessions(subject,from_date,to_date)
    except CollegeAPIError as e: api_error(e)

@app.get("/api/student/requests")
async def student_requests(request: Request):
    u=require_user(request,["student"])
    try: return await CollegeClient(u["college_token"]).student_requests()
    except CollegeAPIError as e: api_error(e)

@app.get("/api/student/requests/{request_id}")
async def student_request_detail(request_id: str,request: Request):
    u=require_user(request,["student"])
    try: return await CollegeClient(u["college_token"]).request_detail(request_id)
    except CollegeAPIError as e: api_error(e)

@app.get("/api/student/placements")
async def student_placements(request: Request):
    u=require_user(request,["student"])
    try: return await CollegeClient(u["college_token"]).my_placements()
    except CollegeAPIError as e: api_error(e)

@app.get("/api/teacher/classes")
async def teacher_classes(request: Request):
    u=require_user(request,["teacher"])
    try: return await CollegeClient(u["college_token"]).teacher_classes()
    except CollegeAPIError as e: api_error(e)

@app.get("/api/teacher/requests")
async def teacher_requests(request: Request,status: str|None=None):
    u=require_user(request,["teacher"])
    try: return await CollegeClient(u["college_token"]).teacher_requests(status)
    except CollegeAPIError as e: api_error(e)

@app.get("/api/teacher/classes/{class_id}/attendance")
async def teacher_class_attendance(class_id: str,request: Request):
    u=require_user(request,["teacher"])
    try: return await CollegeClient(u["college_token"]).class_attendance(class_id)
    except CollegeAPIError as e: api_error(e)

# Writes are staged first. The caller receives an action_id and must explicitly confirm it.
class ActionPrepare(BaseModel):
    action_type: str
    payload: dict
class ActionConfirm(BaseModel):
    action_id: str
    confirmed: bool

def validate_action(role, action_type, payload):
    allowed={
      "student": {"leave_od_request","cancel_student_request","placement_register"},
      "teacher": {"teacher_approve","teacher_reject"},
      "public": {"admission_application"}
    }
    if action_type not in allowed.get(role,set()):
        raise HTTPException(403,"This role cannot perform that action.")
    if action_type=="admission_application":
        required=["full_name","phone","email","course_code","twelfth_percent"]
        if any(k not in payload for k in required): raise HTTPException(422,f"Required fields: {required}")
    elif action_type=="leave_od_request":
        required=["type","from_date","to_date","reason"]
        if any(k not in payload for k in required): raise HTTPException(422,f"Required fields: {required}")
        if payload["type"] not in {"personal_leave","medical_leave","on_duty"}: raise HTTPException(422,"Invalid request type.")
        if payload["type"]=="on_duty" and not payload.get("event_name"): raise HTTPException(422,"event_name is required for on_duty.")
    elif action_type=="teacher_reject" and not payload.get("reason"):
        raise HTTPException(422,"reason is required for rejection.")
    elif action_type in {"cancel_student_request","placement_register","teacher_approve","teacher_reject"} and not payload.get("id"):
        raise HTTPException(422,"id is required.")

@app.post("/api/actions/prepare")
async def prepare_action(body: ActionPrepare,request: Request):
    if body.action_type=="admission_application": role="public"; u=current_user(request)
    else:
        u=require_user(request); role=u["role"]
    validate_action(role,body.action_type,body.payload)
    sid=request.cookies.get("kit_session") or "public"
    action_id=uuid.uuid4().hex
    save_pending_action(action_id,sid,body.action_type,body.payload)
    summary={"action_type":body.action_type,"payload":body.payload,
             "message":"Review the details. Nothing has been submitted yet. Confirm to continue."}
    return {"action_id":action_id,"confirmation":summary}

@app.post("/api/actions/confirm")
async def confirm_action(body: ActionConfirm,request: Request):
    if not body.confirmed: raise HTTPException(400,"Action was not confirmed.")
    sid=request.cookies.get("kit_session") or "public"
    pending=pop_pending_action(body.action_id,sid)
    if not pending: raise HTTPException(404,"Confirmation expired or action not found.")
    kind,payload=pending["action_type"],pending["payload"]
    u=current_user(request)
    if kind=="admission_application":
        client=CollegeClient()
    else:
        if not u: raise HTTPException(401,"Session expired. Sign in again.")
        client=CollegeClient(u["college_token"])
    try:
        if kind=="admission_application": result=await client.admission(payload)
        elif kind=="leave_od_request": result=await client.create_request(payload)
        elif kind=="cancel_student_request": result=await client.cancel_request(payload["id"])
        elif kind=="placement_register": result=await client.register_placement(payload["id"])
        elif kind=="teacher_approve": result=await client.approve_request(payload["id"],payload.get("comment"))
        elif kind=="teacher_reject": result=await client.reject_request(payload["id"],payload["reason"])
        else: raise HTTPException(400,"Unknown action.")
    except CollegeAPIError as e: api_error(e)
    return {"ok":True,"result":result}

# External speech-to-text: Deepgram; no browser Web Speech API.
@app.post("/api/transcribe")
async def transcribe(audio: UploadFile=File(...)):
    if not settings.deepgram_api_key: raise HTTPException(503,"DEEPGRAM_API_KEY is not configured.")
    raw=await audio.read()
    if not raw: raise HTTPException(400,"No audio was received.")
    mime=audio.content_type or "audio/webm"
    async with httpx.AsyncClient(timeout=60) as client:
        r=await client.post("https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true",
            headers={"Authorization":f"Token {settings.deepgram_api_key}","Content-Type":mime},content=raw)
    if r.is_error: raise HTTPException(r.status_code,r.text[:500])
    data=r.json()
    return {"transcript":data["results"]["channels"][0]["alternatives"][0]["transcript"]}

class SpeakBody(BaseModel):
    text: str=Field(min_length=1,max_length=4000)

@app.post("/api/speak")
async def speak(body: SpeakBody):
    """Convert assistant text to speech using the external ElevenLabs API."""
    if not settings.elevenlabs_api_key:
        raise HTTPException(503, "ELEVENLABS_API_KEY is not configured.")

    url = (
        "https://api.elevenlabs.io/v1/text-to-speech/"
        f"{settings.elevenlabs_voice_id}"
    )
    params = {"output_format": settings.elevenlabs_output_format}
    payload = {
        "text": body.text,
        "model_id": settings.elevenlabs_model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            result = await client.post(
                url,
                params=params,
                headers={
                    "xi-api-key": settings.elevenlabs_api_key,
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.TimeoutException:
        raise HTTPException(504, "ElevenLabs TTS request timed out.")
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not connect to ElevenLabs: {str(exc)[:250]}")

    if result.is_error:
        # Avoid exposing request headers or secrets in error responses.
        detail = result.text[:500] if result.text else "ElevenLabs request failed."
        raise HTTPException(result.status_code, f"ElevenLabs TTS error: {detail}")

    return Response(
        content=result.content,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )

@app.post("/api/documents/refresh")
async def documents_refresh(request: Request):
    require_user(request,["teacher"])
    try: return await refresh_documents()
    except CollegeAPIError as e: api_error(e)

@app.get("/healthz")
async def healthz(): return {"status":"ok","service":"KIT Voice Assistant"}
