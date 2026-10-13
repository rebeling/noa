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
    shared_tts = getattr(websocket.app.state, "shared_tts", None)
    orchestrator = DialogueOrchestrator(shared_tts=shared_tts)
    # sub and role are logged only; nothing in the voice path is role-gated.
    try:
        await orchestrator.run_session(
            websocket, language=lang, user_id=payload.sub, role=payload.role
        )
    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
