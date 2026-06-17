"""Dialogue orchestrator — wires pipeline parts and routes events.

Owns the event bus and one instance of each part per session. The only
module that imports every part. Nothing imports the orchestrator except
the API layer.

LLM + TTS are wired through the bus but, matching the prior code, the
session loop currently emits a stub response for ASR-only latency
measurement. Re-enabling the full path is a one-line change in
on_turn_ended, not a structural one.
"""

import asyncio
import json
import os
import random
import re
import time
import uuid

from app.core.config import settings

from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.contracts import (
    AudioChunk,
    FinalTranscript,
    PartialTranscript,
    ResponseText,
    SpeechStarted,
    TurnEnded,
)
from app.bus import EventBus
from app.dialogue import DialogueService
from app.ingestion import IngestionService
from app.speech_input import SpeechInputService
from app.synthesis import SynthesisService, postprocess_for_speech
from app import _turn_text as txt

# How often the background partial-transcribe loop runs. 0.25s keeps
# partials snappy; Parakeet decodes a window in ~150-500ms on the Apple
# GPU so the loop stays ahead. (Whisper fallback is slower but still
# tractable since the window is capped below.)
_PARTIAL_POLL_SECS = 0.25
# Below this many bytes of buffered audio, skip a partial transcribe.
# 4000 bytes = ~0.125s — surfaces first text sooner than the old 0.25s.
_MIN_PARTIAL_BYTES = 4000
# Cap partial-transcribe input to the last N bytes (~6s @ 16kHz int16).
# Decode time grows with audio length; bounding it keeps partials
# tractable on long turns. Final pass still sees the full buffer.
_PARTIAL_WINDOW_BYTES = 192000
# When the live (uncommitted) audio grows past window + slide_step, we
# transcribe the oldest slide_step bytes once, append to committed, and
# advance the commit offset. Non-overlapping → no duplicate words.
_PARTIAL_SLIDE_STEP_BYTES = 96000  # ~3s
# If a fresh partial landed within this window before vad_end, reuse it
# as final instead of re-transcribing the whole turn audio.
_FINAL_REUSE_PARTIAL_SECS = 0.8
# VAD reads the most recent slice of this many bytes.
_VAD_WINDOW_BYTES = 4000
# When idle, trim the buffer back to this many trailing bytes.
_IDLE_BUFFER_KEEP = 8000
_IDLE_BUFFER_MAX = 32000
# Fake processing + speaking windows. Both barge-in-testable.
_FAKE_PROCESSING_SECS = 2.0
_FAKE_SPEAKING_SECS = 3.0
# Echo-LLM delay range: simulates LLM latency without an API call.
_ECHO_LLM_MIN_SECS = 1.0
_ECHO_LLM_MAX_SECS = 2.5
# Max time the reply path waits on a Cognee search before giving up and
# answering ungrounded. The search is on the critical path (the LLM can't
# start until context resolves). The filler ("give me a second…") plays
# while we wait, so the budget is the filler's cover, not dead air — set it
# high enough for the slow GRAPH_COMPLETION/session path (4-8s in logs),
# which is the whole point of a knowledge assistant. Past the budget we drop
# context rather than hang forever. Override with NOA_CONTEXT_BUDGET_SECS.
_CONTEXT_BUDGET_SECS = float(os.environ.get("NOA_CONTEXT_BUDGET_SECS", "12.0"))
# Reply mode:
#   'fake' — timed stub, no LLM, no TTS (offline plumbing test)
#   'echo' — mock LLM (1.0–2.5s delay, echoes input), real TTS
#   'real' — real LLM + real TTS
_REPLY_MODE = os.environ.get("NOA_REPLY_MODE", "fake").lower()


def _is_open(ws) -> bool:
    return ws.client_state == WebSocketState.CONNECTED


async def _safe_send_text(ws, payload: str) -> None:
    if _is_open(ws):
        try:
            await ws.send_text(payload)
        except Exception as e:  # noqa: BLE001
            print(f"ws send_text dropped: {e}")


async def _safe_send_bytes(ws, payload: bytes) -> None:
    if _is_open(ws):
        try:
            await ws.send_bytes(payload)
        except Exception as e:  # noqa: BLE001
            print(f"ws send_bytes dropped: {e}")


class DialogueOrchestrator:
    """Builds the pipeline for one WebSocket session and runs it.

    `shared_tts` lets the API layer pass in a process-wide, pre-warmed
    SynthesisService so each new session skips Kokoro cold-load. Falls
    back to a fresh per-session instance if none is provided."""

    def __init__(self, shared_tts: SynthesisService | None = None) -> None:
        self._shared_tts = shared_tts

    async def run_session(
        self,
        websocket,
        language: str = "en",
        user_id: str = "anonymous",
        dataset_name: str = "default",
        role: str = "customer",
    ) -> None:
        bus = EventBus()
        speech = SpeechInputService(language=language)
        dialogue = DialogueService(language=language)
        ingestion = IngestionService()  # cognee loads lazily on first query
        # The shared, pre-warmed TTS is English-only. Reuse it for English
        # sessions (warm start); build a fresh per-session instance for
        # other languages so we never mutate the shared instance's
        # language out from under a concurrent English session.
        if self._shared_tts is not None and language == "en":
            synthesis = self._shared_tts
            using_shared = True
        else:
            synthesis = SynthesisService(language=language)
            using_shared = False
        print(f"session: reply_mode={_REPLY_MODE} language={language} "
              f"user_id={user_id} role={role} dataset={dataset_name} "
              f"shared_tts={using_shared}")
        # session language is mutable via set_language; capture in a holder
        # the closures read so a mid-session switch reaches fact confirm/deny.
        session_lang = language

        # Last filler phrase spoken this session — so txt.pick_filler never
        # repeats the same line twice in a row.
        last_filler: str | None = None

        # cognee-sessions experiment: one session id per WebSocket connection,
        # scoped to the tenant so threads never cross users. None when the
        # toggle is off → retrieval keeps its default (lexical) path.
        cognee_session_id = (
            f"noa_{user_id}_{uuid.uuid4().hex[:8]}"
            if settings.COGNEE_SESSIONS else None
        )

        # --- event handlers: parts never call each other directly ---
        async def on_partial(event: PartialTranscript) -> None:
            # event.text is the tail (last window). committed_text is
            # the frozen prefix from prior windows that fell out of the
            # sliding window — sent so the client renders the whole
            # turn, not only the last 6s.
            await _safe_send_text(websocket, json.dumps({
                "type": "user_transcript_chunk",
                "committed": committed_text,
                "tail": event.text,
            }))

        async def on_speech_started(event: SpeechStarted) -> None:
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Listening..."}))
            await _safe_send_text(websocket, json.dumps({"type": "stop_audio"}))

        async def on_turn_ended(event: TurnEnded) -> None:
            # Fire-and-forget the reply task so on_turn_ended returns
            # quickly and the receive loop stays free to read barge_in.
            nonlocal pending_reply, turn_end_t0
            text = event.transcript
            if not (text and len(text) > 1):
                await _safe_send_text(websocket, json.dumps(
                    {"type": "response", "text": "(no speech recognized)"}))
                return
            await _safe_send_text(websocket, json.dumps(
                {"type": "transcript", "text": text}))
            if turn_end_t0 is not None:
                dt = (time.perf_counter() - turn_end_t0) * 1000
                print(f"[turn ] vad_end -> transcript_sent: {dt:6.0f}ms")
                turn_end_t0 = None
            # Cancel any prior in-flight reply (shouldn't happen, but safe).
            if pending_reply is not None and not pending_reply.done():
                pending_reply.cancel()
            pending_reply = asyncio.create_task(_delayed_reply(text))

        async def _fake_reply(text: str) -> None:
            """Debug path: two timed phases, no LLM, no TTS.
              1) Processing... for _FAKE_PROCESSING_SECS
              2) response='ok' + Speaking... for _FAKE_SPEAKING_SECS
              3) Waiting
            Useful for testing barge-in plumbing offline."""
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Processing..."}))
            await asyncio.sleep(_FAKE_PROCESSING_SECS)
            await _safe_send_text(websocket, json.dumps(
                {"type": "response", "text": "ok"}))
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Speaking..."}))
            await asyncio.sleep(_FAKE_SPEAKING_SECS)
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Waiting..."}))

        async def _echo_llm(text: str, context: str | None = None) -> str:
            """Mock LLM: wait 1.0–2.5s, return input verbatim. Ignores
            context (no retrieval in echo mode).
            Lets us exercise the full Processing/Speaking + TTS path
            without an OpenAI call. Same await semantics as the real
            LLM, so barge-in cancels cleanly."""
            delay = random.uniform(_ECHO_LLM_MIN_SECS, _ECHO_LLM_MAX_SECS)
            t0 = time.perf_counter()
            await asyncio.sleep(delay)
            print(f"[llm echo] {(time.perf_counter()-t0)*1000:.0f}ms "
                  f"(target={delay*1000:.0f}ms) chars={len(text)}")
            return text

        async def _reply_with_tts(text: str, llm_stream_call) -> None:
            """Shared path: status=Processing → [retrieve] → llm_stream_call
            → status=Speaking → streamed TTS chunks → status=Waiting.
            `llm_stream_call` is an async generator callable (user_text,
            context) → chunks.
            
            This version implements 'streaming-to-streaming' with a producer-consumer
            queue to overlap LLM generation and TTS synthesis, minimizing TTFA."""
            t_turn_start = time.perf_counter()
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Processing..."}))
            
            # In session mode every turn goes to cognee so the conversational
            # session threads context across short follow-ups ("Yes.",
            # "Mr. Rebel") that the question heuristic would otherwise skip —
            # exactly the turns where a knowledge lookup is wanted. Without
            # session mode, keep the cheap question gate so we don't pay the
            # lexical search on every utterance.
            is_question = txt.looks_like_question(text)
            should_search = is_question or cognee_session_id is not None
            context = None

            async def _get_context():
                nonlocal context
                if should_search:
                    result = await ingestion.query_with_meta(
                        text, user_id, dataset_name,
                        session_id=cognee_session_id,
                    )
                    context = result.context or None
                    print(f"[trace] cognee search: {result.elapsed_ms}ms "
                          f"source={result.source} hit_count={result.hit_count}")
                else:
                    print("[trace] cognee skip: 0ms (not a question)")
            
            # Start Cognee search in parallel with filler preparation
            ctx_task = asyncio.create_task(_get_context())

            # Say a filler immediately to mask Cognee + LLM latency whenever
            # we're about to hit the graph (any searched turn, not just ones
            # that parse as questions) — otherwise a slow session lookup on a
            # short follow-up is dead air. Only if not in fake mode.
            filler_task = None
            if should_search and _REPLY_MODE != "fake":
                nonlocal last_filler
                pool = txt.FILLERS.get(session_lang, txt.FILLERS["en"])
                filler_phrase = txt.pick_filler(pool, last_filler)
                last_filler = filler_phrase
                async def _say_filler():
                    print(f"[trace] speaking filler: {filler_phrase!r}")
                    await _safe_send_text(websocket, json.dumps(
                        {"type": "status", "text": "Speaking..."}))
                    await _safe_send_text(websocket, json.dumps(
                        {"type": "response", "text": filler_phrase}))
                    async for chunk in synthesis.synthesize_stream(filler_phrase):
                        await _safe_send_bytes(websocket, chunk)
                filler_task = asyncio.create_task(_say_filler())

            # Wait for Cognee but cap the time so we don't hang forever
            done, _ = await asyncio.wait({ctx_task}, timeout=_CONTEXT_BUDGET_SECS)
            if ctx_task not in done:
                ctx_task.cancel()
                ctx_task.add_done_callback(lambda t: t.cancelled() or t.exception())
                print(f"[trace] cognee search: TIMEOUT >"
                      f"{_CONTEXT_BUDGET_SECS*1000:.0f}ms -> answering ungrounded")

            t_llm_start = time.perf_counter()
            
            # Sentence queue for the producer-consumer pipeline
            sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()
            
            # Sentence boundaries for natural chunking
            _SENTENCE_END = re.compile(r"([.!?])\s+")

            async def sentence_producer():
                """Consumes the LLM token stream, chunks into sentences, and pushes to queue."""
                buffer = ""
                async for chunk in llm_stream_call(text, context):
                    buffer += chunk
                    # Look for sentence boundaries
                    while True:
                        match = _SENTENCE_END.search(buffer)
                        if not match:
                            break
                        sentence = buffer[:match.end()].strip()
                        buffer = buffer[match.end():]
                        if sentence:
                            await sentence_queue.put(sentence)
                
                # Final flush
                remaining = buffer.strip()
                if remaining:
                    await sentence_queue.put(remaining)
                await sentence_queue.put(None)  # Sentinel

            async def sentence_consumer():
                """Pulls sentences from the queue and synthesizes them immediately."""
                nonlocal chunks, total_bytes
                first_sentence = True
                while True:
                    sentence = await sentence_queue.get()
                    if sentence is None:
                        sentence_queue.task_done()
                        break
                    
                    clean = postprocess_for_speech(sentence)
                    if not clean:
                        sentence_queue.task_done()
                        continue

                    # If the filler is still going, we let it finish. 
                    # BUT: if the first sentence is ready, we want to ensure the 
                    # status is Speaking... (filler might have already set it).
                    if first_sentence:
                        t_first_sentence_ready = time.perf_counter()
                        print(f"[trace] llm first sentence ready: {(t_first_sentence_ready - t_llm_start)*1000:.0f}ms")
                        await _safe_send_text(websocket, json.dumps(
                            {"type": "status", "text": "Speaking..."}))
                    
                    # Append this segment's text to the chat bubble.
                    await _safe_send_text(websocket, json.dumps(
                        {"type": "response_chunk", "text": sentence + " "}))
                    
                    tts_text = txt.apply_tts_pronunciation(clean)
                    async for audio_chunk in synthesis.synthesize_stream(tts_text):
                        if first_sentence and chunks == 0:
                            t_first_audio = time.perf_counter()
                            print(f"[trace] tts first_chunk: {(t_first_audio - t_first_sentence_ready)*1000:.0f}ms")
                            print(f"[trace] TOTAL TO REAL AUDIO: {(t_first_audio - t_turn_start)*1000:.0f}ms")
                        chunks += 1
                        total_bytes += len(audio_chunk)
                        await _safe_send_bytes(websocket, audio_chunk)
                    
                    first_sentence = False
                    sentence_queue.task_done()

            chunks = 0
            total_bytes = 0
            
            # Start the pipeline
            producer_task = asyncio.create_task(sentence_producer())
            consumer_task = asyncio.create_task(sentence_consumer())
            
            # Wait for the whole pipeline to finish
            await asyncio.gather(producer_task, consumer_task)
            
            # Ensure filler is finished if it was long (unlikely with RAG)
            if filler_task:
                await filler_task
            
            t_turn_end = time.perf_counter()
            print(f"[trace] tts total: {(t_turn_end - t_turn_start)*1000:.0f}ms chunks={chunks}")
            print(f"[trace] FULL TURN: {(t_turn_end - t_turn_start)*1000:.0f}ms")
            
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Waiting..."}))

        async def _speak(message: str) -> None:
            """Send a fixed assistant `message` as text + streamed TTS.
            Used for fact confirm/deny — no LLM, just voice feedback.
            In fake mode (no TTS) just sends the text + status."""
            await _safe_send_text(websocket, json.dumps(
                {"type": "response", "text": message}))
            if _REPLY_MODE == "fake":
                await _safe_send_text(websocket, json.dumps(
                    {"type": "status", "text": "Waiting..."}))
                return
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Speaking..."}))
            tts_text = txt.apply_tts_pronunciation(message)
            async for chunk in synthesis.synthesize_stream(tts_text):
                await _safe_send_bytes(websocket, chunk)
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Waiting..."}))

        async def _handle_fact(fact: str) -> None:
            """Ingest a spoken fact into the user's cognee graph (admin
            only). Confirms or refuses by voice."""
            if role != "admin":
                print(f"[fact ] denied role={role}")
                await _speak(txt.FACT_DENIED.get(session_lang, txt.FACT_DENIED["en"]))
                return
            # cognify takes seconds; don't block the turn on it. Confirm by
            # voice now and ingest in the background. ingest_fact merges the
            # fact into existing entities (see IngestionService.ingest_fact).
            async def _bg_ingest() -> None:
                t0 = time.perf_counter()
                try:
                    await ingestion.ingest_fact(fact, user_id, dataset_name)
                    print(f"[fact ] ingested chars={len(fact)} "
                          f"{(time.perf_counter()-t0)*1000:.0f}ms")
                except Exception as e:  # noqa: BLE001
                    print(f"[fact ] ingest failed: {e}")

            task = asyncio.create_task(_bg_ingest())
            _bg_ingest_tasks.add(task)
            task.add_done_callback(_bg_ingest_tasks.discard)
            await _speak(txt.FACT_CONFIRM.get(session_lang, txt.FACT_CONFIRM["en"]))

        async def _delayed_reply(text: str) -> None:
            """Mode-switching wrapper. NOA_REPLY_MODE picks fake/echo/real.
            A fact wake-phrase ('Remember that ...') routes to ingestion
            instead of the LLM. Cancellation is handled here so all modes
            share the same barge-in cleanup (stop_audio + status=Listening)."""
            try:
                fact = txt.extract_fact(text)
                if fact is not None:
                    print(f"[route] fact=True role={role} chars={len(fact)}")
                    await _handle_fact(fact)
                    return
                if _REPLY_MODE == "real":
                    await _reply_with_tts(text, dialogue.respond_stream)
                elif _REPLY_MODE == "echo":
                    # Mock echo doesn't support streaming yet, but we'll use 
                    # the old _reply_with_tts logic for it or just wrap it.
                    # For now, let's just wrap it in a dummy generator.
                    async def _echo_stream(t, c):
                        yield await _echo_llm(t, c)
                    await _reply_with_tts(text, _echo_stream)
                else:
                    await _fake_reply(text)
            except asyncio.CancelledError:
                # Barge-in: drop assistant audio on the client and go
                # back to listening. stop_audio clears the WebAudio queue
                # in voice.html's onmessage handler.
                await _safe_send_text(websocket, json.dumps({"type": "stop_audio"}))
                await _safe_send_text(websocket, json.dumps(
                    {"type": "status", "text": "Listening..."}))
                raise

        async def on_response_text(event: ResponseText) -> None:
            audio = await asyncio.to_thread(synthesis.synthesize, event.text)
            if audio:
                await _safe_send_bytes(websocket, audio)

        bus.subscribe(PartialTranscript, on_partial)
        bus.subscribe(SpeechStarted, on_speech_started)
        bus.subscribe(TurnEnded, on_turn_ended)
        bus.subscribe(ResponseText, on_response_text)

        # --- session state ---
        audio_buffer = bytearray()
        last_partial = ""
        last_partial_at: float = 0.0
        last_partial_buflen: int = 0
        # Frozen text from audio that has scrolled off the live window.
        # commit_offset is the byte index in audio_buffer where the live
        # window starts; committed_text is the transcription of
        # audio_buffer[:commit_offset]. Each live partial transcribes
        # audio_buffer[commit_offset:] only, so committed + tail never
        # share audio — no duplicate words.
        committed_text = ""
        commit_offset = 0
        partial_task: asyncio.Task | None = None
        pending_reply: asyncio.Task | None = None
        turn_start_t0: float | None = None
        turn_end_t0: float | None = None

        async def partial_loop() -> None:
            """Transcribe the whole growing buffer each poll. Whisper
            re-sees earlier audio with later context, so partials self-
            correct ("I scream" -> "ice cream") on each pass. Cost grows
            with turn length; vad_filter=True inside ASR strips internal
            silence to keep it tractable for typical short turns."""
            nonlocal last_partial, last_partial_at, last_partial_buflen
            nonlocal committed_text, commit_offset
            try:
                while True:
                    await asyncio.sleep(_PARTIAL_POLL_SECS)
                    buflen = len(audio_buffer)
                    if buflen < _MIN_PARTIAL_BYTES:
                        continue
                    if buflen == last_partial_buflen:
                        # No new audio since last partial — skip decode.
                        continue
                    # Slide check: if live segment is longer than window +
                    # slide_step, freeze the oldest slide_step bytes as a
                    # committed transcript and advance commit_offset.
                    live_len = buflen - commit_offset
                    if live_len > _PARTIAL_WINDOW_BYTES + _PARTIAL_SLIDE_STEP_BYTES:
                        freeze_end = commit_offset + _PARTIAL_SLIDE_STEP_BYTES
                        freeze_audio = bytes(audio_buffer[commit_offset:freeze_end])
                        t_f = time.perf_counter()
                        frozen_txt = (await asyncio.to_thread(
                            speech.transcribe, freeze_audio, True)).strip()
                        dt_f = (time.perf_counter() - t_f) * 1000
                        if frozen_txt:
                            committed_text = (
                                (committed_text + " " + frozen_txt).strip()
                                if committed_text
                                else frozen_txt
                            )
                        commit_offset = freeze_end
                        print(f"[part ] freeze {dt_f:5.0f}ms "
                              f"frozen_chars={len(frozen_txt)} "
                              f"committed_chars={len(committed_text)} "
                              f"commit_offset={commit_offset}")
                    # Live snapshot: only the uncommitted segment, capped
                    # at window so decode time stays bounded.
                    live_start = max(commit_offset, buflen - _PARTIAL_WINDOW_BYTES)
                    snapshot = bytes(audio_buffer[live_start:])
                    t_p = time.perf_counter()
                    txt = (await asyncio.to_thread(
                        speech.transcribe, snapshot, True)).strip()
                    dt_p = (time.perf_counter() - t_p) * 1000
                    audio_ms = len(snapshot) / 32  # int16@16kHz -> ms
                    changed = bool(txt) and txt != last_partial
                    print(f"[part ] {dt_p:5.0f}ms audio={audio_ms:.0f}ms "
                          f"changed={changed} chars={len(txt)} "
                          f"committed_chars={len(committed_text)}")
                    last_partial_buflen = buflen
                    if changed:
                        last_partial = txt
                        last_partial_at = time.perf_counter()
                        await bus.publish(PartialTranscript(text=txt))
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001
                print(f"partial loop error: {e}")

        # --- receive loop ---
        # Greet the user once on session start so they know the
        # pipeline is hot. Uses the pre-rendered WAV from app boot
        # when available so the audio arrives instantly.
        async def _greet() -> None:
            # Random greeting per session, in the session language —
            # synthesized on demand (no fixed cached phrase).
            pool = txt.GREETINGS.get(session_lang, txt.GREETINGS["en"])
            phrase = random.choice(pool)
            print(f"[greet] mode={_REPLY_MODE} lang={session_lang} "
                  f"phrase={phrase!r}")
            if _REPLY_MODE == "fake":
                await _safe_send_text(websocket, json.dumps(
                    {"type": "response", "text": phrase}))
                await _safe_send_text(websocket, json.dumps(
                    {"type": "status", "text": "Waiting..."}))
                return
            await _safe_send_text(websocket, json.dumps(
                {"type": "response", "text": phrase}))
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Speaking..."}))
            t0 = time.perf_counter()
            chunks = 0
            async for chunk in synthesis.synthesize_stream(phrase):
                if chunks == 0:
                    print(f"[greet] first_chunk {(time.perf_counter()-t0)*1000:.0f}ms")
                chunks += 1
                await _safe_send_bytes(websocket, chunk)
            print(f"[greet] stream_done {(time.perf_counter()-t0)*1000:.0f}ms "
                  f"chunks={chunks}")
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Waiting..."}))

        try:
            await _greet()
        except Exception as e:  # noqa: BLE001
            print(f"greet failed: {e}")

        # Accepts both binary frames (PCM audio) and text frames (JSON
        # control messages). Only set_language is handled today; other
        # control types are ignored so the receive path stays simple.
        while True:
            try:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect()
                text_payload = message.get("text")
                if text_payload is not None:
                    try:
                        ctrl = json.loads(text_payload)
                    except Exception:
                        ctrl = None
                    if isinstance(ctrl, dict):
                        ctype = ctrl.get("type")
                        if ctype == "set_language":
                            lang = str(ctrl.get("language", "")).lower()
                            if lang:
                                session_lang = lang
                                speech.set_language(lang)
                                dialogue.set_language(lang)
                                # TTS: never mutate the shared (English)
                                # instance. If this session is on the shared
                                # one and switches away from English, swap to
                                # a fresh per-session synthesizer.
                                if using_shared and lang != "en":
                                    synthesis = SynthesisService(language=lang)
                                    using_shared = False
                                else:
                                    synthesis.set_language(lang)
                                print(f"language switched to {lang}")
                        elif ctype == "barge_in":
                            # Cancel a pending fake-LLM reply so the user
                            # can speak again immediately.
                            if pending_reply is not None and not pending_reply.done():
                                pending_reply.cancel()
                                pending_reply = None
                                print("barge_in: cancelled pending reply")
                        elif ctype == "text_input":
                            # Typed message: skip ASR/VAD entirely and drive
                            # the same reply path as a finished spoken turn.
                            # Lets us test retrieval + LLM without the mic.
                            typed = str(ctrl.get("text", "")).strip()
                            if typed:
                                print(f"[text_input] {typed!r}")
                                await on_turn_ended(TurnEnded(transcript=typed))
                    continue
                chunk = message.get("bytes")
                if not chunk:
                    continue
                audio_buffer.extend(chunk)
                if len(audio_buffer) < _VAD_WINDOW_BYTES:
                    continue

                t_vad = time.perf_counter()
                window = AudioChunk(data=bytes(audio_buffer[-_VAD_WINDOW_BYTES:]))
                transition = speech.detect(window)
                dt_vad = (time.perf_counter() - t_vad) * 1000
                if dt_vad > 5.0:
                    print(f"[vad  ] slow: {dt_vad:.1f}ms (window={_VAD_WINDOW_BYTES}B)")

                if transition == "start":
                    last_partial = ""
                    committed_text = ""
                    commit_offset = 0
                    turn_start_t0 = time.perf_counter()
                    turn_end_t0 = None
                    partial_task = asyncio.create_task(partial_loop())
                    await bus.publish(SpeechStarted())
                    print("[turn ] vad_start")

                elif transition == "end":
                    turn_end_t0 = time.perf_counter()
                    if turn_start_t0 is not None:
                        dur = (turn_end_t0 - turn_start_t0) * 1000
                        print(f"[turn ] vad_end (turn_dur={dur:.0f}ms)")
                    if partial_task is not None:
                        partial_task.cancel()
                        partial_task = None
                    # Show last partial to user immediately — UI feels
                    # instant even when final decode takes ~1s. Reply
                    # still triggers from the (more accurate) final.
                    # Combine committed prefix + live tail so the
                    # provisional render matches the growing partial
                    # bubble (not just the last window).
                    provisional_text = (
                        (committed_text + " " + last_partial).strip()
                        if committed_text
                        else last_partial
                    )
                    if provisional_text:
                        await _safe_send_text(websocket, json.dumps(
                            {"type": "transcript", "text": provisional_text,
                             "provisional": True}))
                        print(f"[turn ] vad_end -> partial_shown: "
                              f"{(time.perf_counter()-turn_end_t0)*1000:.0f}ms "
                              f"chars={len(provisional_text)} "
                              f"(committed={len(committed_text)} "
                              f"tail={len(last_partial)})")
                    final_audio = bytes(audio_buffer)
                    # Reuse last partial as final if:
                    #   - turn audio fits inside the partial sliding window
                    #     (partial saw it all), AND
                    #   - partial was decoded recently (text fresh), AND
                    #   - partial covered ~all buffered audio at that time.
                    age = time.perf_counter() - last_partial_at
                    covered = last_partial_buflen >= len(final_audio) - 8000
                    fits_window = len(final_audio) <= _PARTIAL_WINDOW_BYTES
                    # Reuse only on short turns where partial saw the
                    # whole audio. Once we've committed an offset the
                    # last_partial only covers the live segment, so
                    # reusing it would drop committed_text.
                    reuse = (
                        bool(last_partial)
                        and age < _FINAL_REUSE_PARTIAL_SECS
                        and covered
                        and fits_window
                        and commit_offset == 0
                    )
                    if reuse:
                        text = last_partial
                        print(f"[turn ] final_reuse_partial: skipped decode "
                              f"(partial age={age*1000:.0f}ms chars={len(text)})")
                    else:
                        t_final = time.perf_counter()
                        text = (await asyncio.to_thread(
                            speech.transcribe, final_audio, False)).strip()
                        print(f"[turn ] final_transcribe: "
                              f"{(time.perf_counter()-t_final)*1000:.0f}ms "
                              f"audio={len(final_audio)/32000:.2f}s "
                              f"(reuse=no fits={fits_window} "
                              f"covered={covered} age={age*1000:.0f}ms)")
                    await bus.publish(FinalTranscript(text=text))
                    await bus.publish(TurnEnded(transcript=text))
                    audio_buffer.clear()
                    last_partial = ""
                    last_partial_buflen = 0
                    last_partial_at = 0.0
                    committed_text = ""
                    commit_offset = 0
                    turn_start_t0 = None

                if not speech.is_speaking and len(audio_buffer) > _IDLE_BUFFER_MAX:
                    audio_buffer = bytearray(audio_buffer[-_IDLE_BUFFER_KEEP:])

            except WebSocketDisconnect:
                raise
            except Exception as e:  # noqa: BLE001
                print(f"Session error: {e}")
                import traceback
                traceback.print_exc()
                break


orchestrator = DialogueOrchestrator()
