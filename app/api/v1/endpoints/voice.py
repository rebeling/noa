from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.security import decode_token
from app.orchestrator import DialogueOrchestrator

router = APIRouter()


@router.websocket("/ws")
async def voice_websocket(
    websocket: WebSocket,
    token: str | None = None,
    lang: str = "en",
):
    # Authenticate before accepting — browsers cannot set Authorization
    # headers on WebSocket handshakes, so the JWT arrives as ?token=.
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        payload = decode_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    state = websocket.app.state
    shared_tts = getattr(state, "shared_tts", None)
    # No fixed greeting: the orchestrator picks a random greeting per
    # session in the session language.
    orchestrator = DialogueOrchestrator(shared_tts=shared_tts)
    # sub identifies the user for logging. Falls back to "anonymous" only
    # if the token somehow lacks a subject (decode already rejects
    # sub=None, so this is belt-and-suspenders).
    user_id = payload.sub or "anonymous"
    # role is carried for future RBAC; nothing in the voice path is
    # role-gated today (the memory layer that was is gone).
    role = payload.role or "customer"
    try:
        await orchestrator.run_session(
            websocket, language=lang, user_id=user_id, role=role)
    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
