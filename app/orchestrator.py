"""Dialogue orchestrator — wires pipeline parts and routes events.

Owns the event bus and one instance of each part per session. The only
module that imports every part. Nothing imports the orchestrator except
the API layer.
"""

import asyncio
import contextlib
import io
import json
import os
import random
import time
import wave

from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState

from app import _turn_text as turn_text
from app.bus import EventBus
from app.contracts import AudioChunk, PartialTranscript, SpeechStarted, TurnEnded
from app.dialogue import DialogueService
from app.speech_input import SpeechInputService
from app.synthesis import SynthesisService, postprocess_for_speech

# How often the background partial-transcribe loop runs. 0.25s keeps
# partials snappy; Parakeet decodes a window in ~150-500ms on the Apple
# GPU so the loop stays ahead.
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
# When idle, trim the buffer back to this many trailing bytes.
_IDLE_BUFFER_KEEP = 8000
_IDLE_BUFFER_MAX = 32000
# Fake processing + speaking windows. Both barge-in-testable.
_FAKE_PROCESSING_SECS = 2.0
_FAKE_SPEAKING_SECS = 3.0
# Echo-LLM delay range: simulates LLM latency without an API call.
_ECHO_LLM_MIN_SECS = 1.0
_ECHO_LLM_MAX_SECS = 2.5
# Reply mode:
#   'fake' — timed stub, no LLM, no TTS (offline plumbing test)
#   'echo' — mock LLM (1.0–2.5s delay, echoes input), real TTS
#   'real' — real LLM + real TTS
_REPLY_MODE = os.environ.get("NOA_REPLY_MODE", "real").lower()


def _is_open(ws) -> bool:
    return ws.client_state == WebSocketState.CONNECTED


async def _send(ws, message: dict) -> None:
    """Send a JSON control message; drop it silently if the socket is closed."""
    if _is_open(ws):
        try:
            await ws.send_text(json.dumps(message))
        except Exception as e:  # noqa: BLE001
            print(f"ws send dropped: {e}")


async def _send_audio(ws, wav: bytes) -> None:
    if _is_open(ws):
        try:
            await ws.send_bytes(wav)
        except Exception as e:  # noqa: BLE001
            print(f"ws send_bytes dropped: {e}")


def _wav_seconds(wav: bytes) -> float:
    """Playback length of one WAV chunk; 0 if the header is unreadable."""
    try:
        with wave.open(io.BytesIO(wav)) as w:
            return w.getnframes() / w.getframerate()
    except Exception:  # noqa: BLE001
        return 0.0


class DialogueOrchestrator:
    """Builds the pipeline for one WebSocket session and runs it.

    `shared_tts` lets the API layer pass in a process-wide, pre-warmed
    SynthesisService so each new session skips the TTS cold load. Falls
    back to a fresh per-session instance if none is provided."""

    def __init__(self, shared_tts: SynthesisService | None = None) -> None:
        self._shared_tts = shared_tts

    async def run_session(
        self,
        websocket,
        language: str = "en",
        user_id: str = "anonymous",
        role: str = "customer",
    ) -> None:
        bus = EventBus()
        speech = SpeechInputService(language=language)
        dialogue = DialogueService(language=language)
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
        print(
            f"session: reply_mode={_REPLY_MODE} language={language} "
            f"user_id={user_id} role={role} shared_tts={using_shared}"
        )
        # session language is mutable via set_language; capture in a holder
        # the closures read so a mid-session switch reaches the greeting pool.
        session_lang = language

        # --- event handlers: parts never call each other directly ---
        async def on_partial(event: PartialTranscript) -> None:
            if interrupt_check:
                return
            # event.text is the tail (last window). committed_text is
            # the frozen prefix from prior windows that fell out of the
            # sliding window — sent so the client renders the whole
            # turn, not only the last 6s.
            await _send(
                websocket,
                {
                    "type": "user_transcript_chunk",
                    "committed": committed_text,
                    "tail": event.text,
                },
            )

        def reply_busy() -> bool:
            """A reply is generating, or the client is still playing one."""
            generating = pending_reply is not None and not pending_reply.done()
            return generating or time.perf_counter() < speaking_until

        async def on_speech_started(event: SpeechStarted) -> None:
            # Speech over a running reply: pause playback and wait for the
            # turn to end so the transcript can decide whether it was a
            # real interruption or just noise / a backchannel.
            nonlocal interrupt_check, pause_started
            if reply_busy():
                interrupt_check = True
                pause_started = time.perf_counter()
                await _send(websocket, {"type": "pause_audio"})
                print("[turn ] speech during reply: paused, checking")
                return
            await _send(websocket, {"type": "status", "text": "Listening..."})
            await _send(websocket, {"type": "stop_audio"})

        async def on_turn_ended(event: TurnEnded) -> None:
            # Fire-and-forget the reply task so on_turn_ended returns
            # quickly and the receive loop keeps reading audio.
            nonlocal pending_reply, turn_end_t0, interrupt_check, speaking_until
            text = event.transcript
            if interrupt_check:
                interrupt_check = False
                if not turn_text.is_interruption(text):
                    # Noise or "mhm": resume where Noa left off. Playback
                    # ends later by however long it sat paused.
                    speaking_until += time.perf_counter() - pause_started
                    turn_end_t0 = None
                    await _send(websocket, {"type": "resume_audio"})
                    print(f"[turn ] interrupt rejected {text!r}: resumed")
                    return
                print(f"[turn ] interrupt accepted {text!r}")
                speaking_until = 0.0
                # Finish cancelling the old reply before the new one starts
                # so its cleanup (stop_audio, Listening...) cannot land on
                # top of the new reply's Processing... status.
                if pending_reply is not None and not pending_reply.done():
                    pending_reply.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pending_reply
                await _send(websocket, {"type": "stop_audio"})
            if not (text and len(text) > 1):
                await _send(websocket, {"type": "response", "text": "(no speech recognized)"})
                return
            await _send(websocket, {"type": "transcript", "text": text})
            # t0 = when the user stopped talking (vad_end). Typed input has
            # no vad_end, so it starts the clock now.
            t0 = turn_end_t0 if turn_end_t0 is not None else time.perf_counter()
            if turn_end_t0 is not None:
                dt = (time.perf_counter() - turn_end_t0) * 1000
                print(f"[turn ] vad_end -> transcript_sent: {dt:6.0f}ms")
                turn_end_t0 = None
            # Cancel any prior in-flight reply (shouldn't happen, but safe).
            if pending_reply is not None and not pending_reply.done():
                pending_reply.cancel()
            pending_reply = asyncio.create_task(_delayed_reply(text, t0))

        async def _fake_reply(text: str) -> None:
            """Debug path: two timed phases, no LLM, no TTS.
              1) Processing... for _FAKE_PROCESSING_SECS
              2) response='ok' + Speaking... for _FAKE_SPEAKING_SECS
              3) Waiting
            Useful for testing barge-in plumbing offline."""
            await _send(websocket, {"type": "status", "text": "Processing..."})
            await asyncio.sleep(_FAKE_PROCESSING_SECS)
            await _send(websocket, {"type": "response", "text": "ok"})
            await _send(websocket, {"type": "status", "text": "Speaking..."})
            await asyncio.sleep(_FAKE_SPEAKING_SECS)
            await _send(websocket, {"type": "status", "text": "Waiting..."})

        async def _echo_llm(text: str) -> str:
            """Mock LLM: wait 1.0–2.5s, return input verbatim.
            Lets us exercise the full Processing/Speaking + TTS path
            without an OpenAI call. Same await semantics as the real
            LLM, so barge-in cancels cleanly."""
            delay = random.uniform(_ECHO_LLM_MIN_SECS, _ECHO_LLM_MAX_SECS)
            t0 = time.perf_counter()
            await asyncio.sleep(delay)
            print(
                f"[llm echo] {(time.perf_counter() - t0) * 1000:.0f}ms "
                f"(target={delay * 1000:.0f}ms) chars={len(text)}"
            )
            return text

        async def _reply_with_tts(text: str, llm_stream_call, t0: float) -> None:
            """status=Processing → llm_stream_call → status=Speaking →
            streamed TTS chunks → status=Waiting. `llm_stream_call` is an
            async generator callable (user_text) → text chunks. `t0` is when
            the user stopped talking; first audio is reported relative to it.

            Producer splits the LLM token stream into sentences; consumer
            synthesizes each one the moment it is ready, so TTS for sentence
            N overlaps LLM generation of sentence N+1."""
            await _send(websocket, {"type": "status", "text": "Processing..."})
            t_llm_start = time.perf_counter()

            sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()

            async def sentence_producer():
                """Consume the LLM token stream, cut it into speakable
                segments (clause-short first segment, then full sentences),
                push each one. The finally guarantees the None sentinel even
                if llm_stream_call raises, so the consumer never blocks
                forever. The exception still propagates via gather."""
                buffer = ""
                emitted_first = False
                try:
                    async for chunk in llm_stream_call(text):
                        buffer += chunk
                        while True:
                            segment, buffer = turn_text.split_segment(
                                buffer, first=not emitted_first
                            )
                            if segment is None:
                                break
                            if segment:
                                emitted_first = True
                                await sentence_queue.put(segment)
                    remaining = buffer.strip()
                    if remaining:
                        await sentence_queue.put(remaining)
                finally:
                    await sentence_queue.put(None)

            async def sentence_consumer():
                nonlocal chunks, total_bytes, speaking_until
                first_sentence = True
                while True:
                    sentence = await sentence_queue.get()
                    if sentence is None:
                        break
                    clean = postprocess_for_speech(sentence)
                    if not clean:
                        continue
                    if first_sentence:
                        print(
                            f"[trace] llm first sentence ready: "
                            f"{(time.perf_counter() - t_llm_start) * 1000:.0f}ms"
                        )
                        await _send(websocket, {"type": "status", "text": "Speaking..."})
                    await _send(websocket, {"type": "response_chunk", "text": sentence + " "})
                    async for audio_chunk in synthesis.synthesize_stream(clean):
                        if chunks == 0:
                            now = time.perf_counter()
                            print(
                                f"[trace] tts first_chunk: "
                                f"{(now - t_llm_start) * 1000:.0f}ms after llm start"
                            )
                            print(
                                f"[turn ] stop_talking -> first_audio: {(now - t0) * 1000:6.0f}ms"
                            )
                        chunks += 1
                        total_bytes += len(audio_chunk)
                        await _send_audio(websocket, audio_chunk)
                        speaking_until = max(speaking_until, time.perf_counter()) + _wav_seconds(
                            audio_chunk
                        )
                    first_sentence = False

            chunks = 0
            total_bytes = 0
            producer = asyncio.create_task(sentence_producer())
            consumer = asyncio.create_task(sentence_consumer())
            try:
                await asyncio.gather(producer, consumer)
            finally:
                # If one side failed, gather re-raises but leaves the other
                # running (an orphan LLM stream or TTS loop). Cancel it.
                for task in (producer, consumer):
                    if not task.done():
                        task.cancel()
            print(
                f"[turn ] full reply: {(time.perf_counter() - t0) * 1000:.0f}ms "
                f"chunks={chunks} bytes={total_bytes}"
            )
            await _send(websocket, {"type": "status", "text": "Waiting..."})

        async def _delayed_reply(text: str, t0: float) -> None:
            """Mode-switching wrapper. NOA_REPLY_MODE picks fake/echo/real.
            Cancellation is handled here so all modes share the same
            barge-in cleanup (stop_audio + status=Listening)."""
            try:
                if _REPLY_MODE == "real":

                    async def _real_stream(t):
                        async for chunk in dialogue.respond_stream(t):
                            yield chunk

                    await _reply_with_tts(text, _real_stream, t0)
                elif _REPLY_MODE == "echo":

                    async def _echo_stream(t):
                        yield await _echo_llm(t)

                    await _reply_with_tts(text, _echo_stream, t0)
                else:
                    await _fake_reply(text)
            except asyncio.CancelledError:
                # Barge-in: drop assistant audio on the client and go
                # back to listening. stop_audio clears the WebAudio queue
                # in voice.js's onmessage handler.
                await _send(websocket, {"type": "stop_audio"})
                await _send(websocket, {"type": "status", "text": "Listening..."})
                raise
            except Exception as e:  # noqa: BLE001
                # LLM/TTS failure (bad key, model 404, rate limit, ...):
                # tell the client so it leaves Processing/Speaking instead
                # of hanging, and keep the cause in the server log.
                print(f"[reply] failed: {e!r}")
                await _send(
                    websocket, {"type": "response", "text": "(reply failed — see server log)"}
                )
                await _send(websocket, {"type": "status", "text": "Waiting..."})

        bus.subscribe(PartialTranscript, on_partial)
        bus.subscribe(SpeechStarted, on_speech_started)
        bus.subscribe(TurnEnded, on_turn_ended)

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
        # Estimated moment the client finishes playing what we sent.
        speaking_until = 0.0
        # True from speech onset over a reply until its transcript is judged.
        interrupt_check = False
        pause_started = 0.0
        turn_start_t0: float | None = None
        turn_end_t0: float | None = None

        async def partial_loop() -> None:
            """Transcribe the live window of the buffer each poll. The ASR
            re-sees earlier audio with later context, so partials self-
            correct ("I scream" -> "ice cream") on each pass. The window is
            capped and slid (see constants above) so decode time stays
            bounded on long turns."""
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
                        frozen_txt = (
                            await asyncio.to_thread(speech.transcribe, freeze_audio, True)
                        ).strip()
                        dt_f = (time.perf_counter() - t_f) * 1000
                        if frozen_txt:
                            committed_text = (
                                (committed_text + " " + frozen_txt).strip()
                                if committed_text
                                else frozen_txt
                            )
                        commit_offset = freeze_end
                        print(
                            f"[part ] freeze {dt_f:5.0f}ms "
                            f"frozen_chars={len(frozen_txt)} "
                            f"committed_chars={len(committed_text)} "
                            f"commit_offset={commit_offset}"
                        )
                    # Live snapshot: only the uncommitted segment, capped
                    # at window so decode time stays bounded.
                    live_start = max(commit_offset, buflen - _PARTIAL_WINDOW_BYTES)
                    snapshot = bytes(audio_buffer[live_start:])
                    t_p = time.perf_counter()
                    txt = (await asyncio.to_thread(speech.transcribe, snapshot, True)).strip()
                    dt_p = (time.perf_counter() - t_p) * 1000
                    audio_ms = len(snapshot) / 32  # int16@16kHz -> ms
                    changed = bool(txt) and txt != last_partial
                    print(
                        f"[part ] {dt_p:5.0f}ms audio={audio_ms:.0f}ms "
                        f"changed={changed} chars={len(txt)} "
                        f"committed_chars={len(committed_text)}"
                    )
                    last_partial_buflen = buflen
                    if changed:
                        last_partial = txt
                        last_partial_at = time.perf_counter()
                        await bus.publish(PartialTranscript(text=txt))
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001
                print(f"partial loop error: {e}")

        # Greet once on session start so the user knows the pipeline is hot.
        async def _greet() -> None:
            phrase = turn_text.greeting(session_lang)
            print(f"[greet] mode={_REPLY_MODE} lang={session_lang} phrase={phrase!r}")
            if _REPLY_MODE == "fake":
                await _send(websocket, {"type": "response", "text": phrase})
                await _send(websocket, {"type": "status", "text": "Waiting..."})
                return
            await _send(websocket, {"type": "response", "text": phrase})
            await _send(websocket, {"type": "status", "text": "Speaking..."})
            t0 = time.perf_counter()
            chunks = 0
            async for chunk in synthesis.synthesize_stream(phrase):
                if chunks == 0:
                    print(f"[greet] first_chunk {(time.perf_counter() - t0) * 1000:.0f}ms")
                chunks += 1
                await _send_audio(websocket, chunk)
            print(f"[greet] stream_done {(time.perf_counter() - t0) * 1000:.0f}ms chunks={chunks}")
            await _send(websocket, {"type": "status", "text": "Waiting..."})

        # Warm the LLM connection while the greeting plays (real mode only —
        # fake/echo never call the API). Fire-and-forget; the first turn
        # awaits nothing here, it just finds the pool already open.
        llm_warmup: asyncio.Task | None = None
        if _REPLY_MODE == "real":
            llm_warmup = asyncio.create_task(dialogue.warmup())
            llm_warmup.add_done_callback(lambda t: t.cancelled() or t.exception())
        try:
            await _greet()
        except Exception as e:  # noqa: BLE001
            print(f"greet failed: {e}")

        # Receive loop: binary frames are PCM audio, text frames are JSON
        # control messages (set_language, text_input).
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
                        elif ctype == "text_input":
                            # Typed message: skip VAD/ASR and drive the same
                            # reply path as a finished spoken turn.
                            typed = str(ctrl.get("text", "")).strip()
                            if typed:
                                print(f"[text_input] {typed!r}")
                                await on_turn_ended(TurnEnded(transcript=typed))
                    continue
                chunk = message.get("bytes")
                if not chunk:
                    continue
                audio_buffer.extend(chunk)

                t_vad = time.perf_counter()
                transition = speech.detect(AudioChunk(data=chunk))
                dt_vad = (time.perf_counter() - t_vad) * 1000
                if dt_vad > 5.0:
                    print(f"[vad  ] slow: {dt_vad:.1f}ms (chunk={len(chunk)}B)")

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
                    if provisional_text and not interrupt_check:
                        await _send(
                            websocket,
                            {"type": "transcript", "text": provisional_text, "provisional": True},
                        )
                        print(
                            f"[turn ] vad_end -> partial_shown: "
                            f"{(time.perf_counter() - turn_end_t0) * 1000:.0f}ms "
                            f"chars={len(provisional_text)} "
                            f"(committed={len(committed_text)} "
                            f"tail={len(last_partial)})"
                        )
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
                        print(
                            f"[turn ] final_reuse_partial: skipped decode "
                            f"(partial age={age * 1000:.0f}ms chars={len(text)})"
                        )
                    else:
                        t_final = time.perf_counter()
                        text = (
                            await asyncio.to_thread(speech.transcribe, final_audio, False)
                        ).strip()
                        print(
                            f"[turn ] final_transcribe: "
                            f"{(time.perf_counter() - t_final) * 1000:.0f}ms "
                            f"audio={len(final_audio) / 32000:.2f}s "
                            f"(reuse=no fits={fits_window} "
                            f"covered={covered} age={age * 1000:.0f}ms)"
                        )
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
