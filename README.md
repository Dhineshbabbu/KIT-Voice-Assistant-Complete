# KIT Voice Assistant — Complete Python Project

FastAPI backend + HTML/CSS/JavaScript frontend for the Knotopian Institute of Technology (KIT) challenge API.

## Included
- Public: health, current date, college profile, courses, documents/PDF download, placement drives, admission application.
- Student: profile, academics, subjects, timetable, calendar, attendance summary/session details, leave/OD requests, request details/cancellation, placement registrations.
- Teacher: assigned classes, class attendance, student requests, approve/reject.
- Role is read from the API login response. No username-based role guessing.
- `X-Participant-Key` is attached server-side to every KIT API request; bearer token is attached only for authenticated API calls.
- Conversation history, secure HttpOnly session cookie, external Deepgram speech-to-text and ElevenLabs text-to-speech.
- Optional PDF extraction/search from KIT documents.
- Mutating operations are staged via `/api/actions/prepare` and require a separate `/api/actions/confirm` call. The college API is not called at preparation time.

## Run locally (Windows PowerShell)
1. Install Python 3.11.
2. Extract the ZIP and open the project folder.
3. Create environment:
   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```
4. Add your rotated participant key, Groq key, Deepgram key, and ElevenLabs key to `.env`.
5. Start:
   ```powershell
   uvicorn app.main:app --reload
   ```
6. Open `http://127.0.0.1:8000`.

## Demo credentials
Use the challenge-provided test accounts and password. The server determines role from the `user.role` returned by `/v1/auth/login`; it does not trust hard-coded login IDs.

## API write confirmation
The frontend currently exposes chat and voice interactions. For write workflows, call the following backend routes from a form or confirmation UI:

1. Prepare:
   ```http
   POST /api/actions/prepare
   Content-Type: application/json
   ```
   Admission:
   ```json
   {"action_type":"admission_application","payload":{"full_name":"Rohan Sharma","phone":"+91 9876543210","email":"rohan@example.com","course_code":"BTECH-CSE","twelfth_percent":88.5}}
   ```
   Student leave/OD:
   ```json
   {"action_type":"leave_od_request","payload":{"type":"on_duty","from_date":"2026-11-20","to_date":"2026-11-20","half_day":false,"reason":"Attending an external event","event_name":"AI Conference"}}
   ```
   Cancel request:
   ```json
   {"action_type":"cancel_student_request","payload":{"id":"REQUEST_ID"}}
   ```
   Placement registration:
   ```json
   {"action_type":"placement_register","payload":{"id":"DRIVE_ID"}}
   ```
   Teacher approve:
   ```json
   {"action_type":"teacher_approve","payload":{"id":"REQUEST_ID","comment":"Approved"}}
   ```
   Teacher reject:
   ```json
   {"action_type":"teacher_reject","payload":{"id":"REQUEST_ID","reason":"Please attach supporting documents"}}
   ```
2. Display the returned `confirmation` object to the user.
3. Only after the user explicitly confirms, call:
   ```json
   {"action_id":"ACTION_ID_FROM_PREPARE","confirmed":true}
   ```
   to `POST /api/actions/confirm`. The action expires after 10 minutes and is bound to the same browser session.

## API route reference (app backend)
- `GET /api/public/{health|today|college|courses|documents|placements}`
- `GET /api/public/documents/{doc_id}/file`
- `GET /api/student/profile|subjects|timetable|calendar|attendance|attendance/sessions|requests|placements`
- `GET /api/student/requests/{request_id}`
- `GET /api/teacher/classes|requests`
- `GET /api/teacher/classes/{class_id}/attendance`
- `POST /api/actions/prepare`, `POST /api/actions/confirm`
- `POST /api/login`, `POST /api/logout`, `POST /api/chat`
- `POST /api/transcribe` (Deepgram STT), `POST /api/speak` (ElevenLabs TTS)
- `GET /api/history`, `GET /api/me`

## Document knowledge base
Teacher session can call `POST /api/documents/refresh` to download the files returned by `/v1/documents`, extract PDF text, and cache chunks locally. Chat searches those cached chunks. This uses simple keyword-overlap retrieval, not a hosted vector database. If the API returns non-PDFs, inaccessible files, or an unexpected list shape, those documents are skipped; verify `/v1/documents` in Swagger.

## Voice provider configuration

- **Speech-to-text:** Deepgram Nova-2. The browser only records audio with `MediaRecorder`; it does not use the Web Speech API.
- **Text-to-speech:** ElevenLabs via its REST API. The default model is `eleven_flash_v2_5`, with MP3 output.
- Set `DEEPGRAM_API_KEY` and `ELEVENLABS_API_KEY` in `.env` locally and as secrets in Render.
- `ELEVENLABS_VOICE_ID` selects the voice. The example ID is a configurable starter voice; choose a voice available in your ElevenLabs account if needed.
- `ELEVENLABS_MODEL_ID` and `ELEVENLABS_OUTPUT_FORMAT` can also be changed without editing Python code.
- TTS is generated server-side, so the ElevenLabs API key is never exposed to browser JavaScript.
- ElevenLabs usage is subject to your account's plan, credits, and terms. Check your current dashboard before the live demo.

## Render deployment
- Push this project to GitHub.
- Create a Render Blueprint from `render.yaml`.
- Set `COLLEGE_PARTICIPANT_KEY`, `GROQ_API_KEY`, `DEEPGRAM_API_KEY`, and `ELEVENLABS_API_KEY`. Optionally override `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`, and `ELEVENLABS_OUTPUT_FORMAT`.
- The blueprint provisions a persistent disk for SQLite. Keep `SESSION_COOKIE_SECURE=true` on HTTPS.
- Do not commit `.env`, API keys, bearer tokens, or test passwords.

## Important
- This code follows the provided OpenAPI contract. The challenge requires the participant key on every request even where OpenAPI marks it optional.
- Test with the challenge sandbox before demoing. API data, permissions, seeded accounts, and availability are controlled by the challenge backend.
- This is a hackathon starter, not a production-grade college information system. Add CSRF protection, rate limiting, audit logs, secret rotation, and stronger session controls before production.
