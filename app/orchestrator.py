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
import time

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
from app.speech_input import SpeechInputService
from app.synthesis import SynthesisService

# How often the background partial-transcribe loop runs.
_PARTIAL_POLL_SECS = 0.4
# Below this many bytes of buffered audio, skip a partial transcribe.
_MIN_PARTIAL_BYTES = 8000
# Cap partial-transcribe input to the last N bytes (~6s @ 16kHz int16).
# Whisper decode time grows with audio length; bounding it keeps partials
# tractable on long turns. Final pass still sees the full buffer.
_PARTIAL_WINDOW_BYTES = 192000
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
# Split reply text into fragments before TTS so the first audio lands
# fast. Fragments shorter than _TTS_FRAGMENT_MIN_CHARS get merged with
# the next one to avoid sub-word chunks that sound choppy.
_TTS_FRAGMENT_MIN_CHARS = 12
_TTS_SENTENCE_PUNCT = ".!?,;:"
# Pronunciation overrides for the TTS path only. UI keeps original
# spelling; only the audio sees the phonetic form. Word-boundary
# matched so "Noah" / "Noach" / etc. won't be touched.
_TTS_PRONUNCIATION = {
    "Noa": "Noah",
    "noa": "Noah",
}


def _apply_tts_pronunciation(text: str) -> str:
    import re
    for src, dst in _TTS_PRONUNCIATION.items():
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
    return text


def _split_for_tts(text: str) -> list[str]:
    """Break `text` at sentence/clause punctuation. First fragment is
    deliberately the head of the reply so Kokoro starts on a short
    string and first audio chunk lands sooner. Merges runts < min chars
    into the following fragment so the synth never sees a stub."""
    if not text:
        return []
    fragments: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in _TTS_SENTENCE_PUNCT and len(buf.strip()) >= _TTS_FRAGMENT_MIN_CHARS:
            fragments.append(buf.strip())
            buf = ""
    tail = buf.strip()
    if tail:
        if fragments and len(tail) < _TTS_FRAGMENT_MIN_CHARS:
            fragments[-1] = fragments[-1] + " " + tail
        else:
            fragments.append(tail)
    return fragments
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

    def __init__(
        self,
        shared_tts: SynthesisService | None = None,
        greeting_text: str | None = None,
        greeting_wav: bytes | None = None,
    ) -> None:
        self._shared_tts = shared_tts
        self._greeting_text = greeting_text
        self._greeting_wav = greeting_wav

    async def run_session(self, websocket, language: str = "en") -> None:
        bus = EventBus()
        speech = SpeechInputService(language=language)
        dialogue = DialogueService()
        synthesis = self._shared_tts or SynthesisService()
        print(f"session: reply_mode={_REPLY_MODE} language={language} "
              f"shared_tts={self._shared_tts is not None}")

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

        async def _echo_llm(text: str) -> str:
            """Mock LLM: wait 1.0–2.5s, return input verbatim.
            Lets us exercise the full Processing/Speaking + TTS path
            without an OpenAI call. Same await semantics as the real
            LLM, so barge-in cancels cleanly."""
            delay = random.uniform(_ECHO_LLM_MIN_SECS, _ECHO_LLM_MAX_SECS)
            t0 = time.perf_counter()
            await asyncio.sleep(delay)
            print(f"[llm echo] {(time.perf_counter()-t0)*1000:.0f}ms "
                  f"(target={delay*1000:.0f}ms) chars={len(text)}")
            return text

        async def _reply_with_tts(text: str, llm_call) -> None:
            """Shared path: status=Processing → llm_call → status=Speaking
            → streamed TTS chunks → status=Waiting. `llm_call` is an
            async callable taking the user text and returning the reply
            text, so 'real' and 'echo' modes share this body.
            TTS streams chunk-by-chunk so the client starts playback on
            the first chunk instead of waiting for the full sentence."""
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Processing..."}))
            t_llm = time.perf_counter()
            reply = await llm_call(text)
            print(f"[llm ] total {(time.perf_counter()-t_llm)*1000:.0f}ms "
                  f"reply_chars={len(reply)}")
            await _safe_send_text(websocket, json.dumps(
                {"type": "response", "text": reply}))
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Speaking..."}))
            t_tts = time.perf_counter()
            chunks = 0
            total_bytes = 0
            fragments = _split_for_tts(_apply_tts_pronunciation(reply))
            print(f"[tts ] fragments={len(fragments)} "
                  f"first_chars={len(fragments[0]) if fragments else 0}")
            for f_idx, fragment in enumerate(fragments):
                t_frag = time.perf_counter()
                async for chunk in synthesis.synthesize_stream(fragment):
                    if chunks == 0:
                        print(f"[tts ] first_chunk_to_client "
                              f"{(time.perf_counter()-t_tts)*1000:.0f}ms "
                              f"bytes={len(chunk)}")
                    chunks += 1
                    total_bytes += len(chunk)
                    await _safe_send_bytes(websocket, chunk)
                print(f"[tts ] fragment={f_idx} done "
                      f"{(time.perf_counter()-t_frag)*1000:.0f}ms "
                      f"chars={len(fragment)}")
            print(f"[tts ] stream_done {(time.perf_counter()-t_tts)*1000:.0f}ms "
                  f"chunks={chunks} bytes={total_bytes}")
            await _safe_send_text(websocket, json.dumps(
                {"type": "status", "text": "Waiting..."}))

        async def _delayed_reply(text: str) -> None:
            """Mode-switching wrapper. NOA_REPLY_MODE picks fake/echo/real.
            Cancellation is handled here so all modes share the same
            barge-in cleanup (stop_audio + status=Listening)."""
            try:
                if _REPLY_MODE == "real":
                    await _reply_with_tts(text, dialogue.respond)
                elif _REPLY_MODE == "echo":
                    await _reply_with_tts(text, _echo_llm)
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
        # Frozen text from windows that have scrolled off the partial
        # window. Each time buflen crosses a new window boundary we
        # promote the prior partial to committed so the client keeps
        # showing the full turn instead of only the last 6s.
        committed_text = ""
        committed_buflen = 0
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
            nonlocal committed_text, committed_buflen
            try:
                while True:
                    await asyncio.sleep(_PARTIAL_POLL_SECS)
                    buflen = len(audio_buffer)
                    if buflen < _MIN_PARTIAL_BYTES:
                        continue
                    if buflen == last_partial_buflen:
                        # No new audio since last partial — skip decode.
                        continue
                    # If the buffer has grown past the window, the prior
                    # partial saw audio that the next snapshot won't.
                    # Promote it to committed before we slide the window.
                    if (
                        buflen > _PARTIAL_WINDOW_BYTES
                        and last_partial
                        and last_partial_buflen > committed_buflen
                    ):
                        committed_text = (
                            (committed_text + " " + last_partial).strip()
                            if committed_text
                            else last_partial
                        )
                        committed_buflen = last_partial_buflen
                        print(f"[part ] committed grew chars={len(committed_text)} "
                              f"committed_buflen={committed_buflen}")
                    # Cap snapshot to last _PARTIAL_WINDOW_BYTES so decode
                    # cost stays bounded as the turn grows.
                    snapshot = bytes(audio_buffer[-_PARTIAL_WINDOW_BYTES:])
                    t_p = time.perf_counter()
                    txt = (await asyncio.to_thread(
                        speech.transcribe, snapshot, True)).strip()
                    dt_p = (time.perf_counter() - t_p) * 1000
                    audio_ms = len(snapshot) / 32  # int16@16kHz -> ms
                    changed = bool(txt) and txt != last_partial
                    print(f"[part ] {dt_p:5.0f}ms audio={audio_ms:.0f}ms "
                          f"changed={changed} chars={len(txt)}")
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
            phrase = self._greeting_text or "Hi! I'm Noa. How can I help?"
            cached_wav = self._greeting_wav
            print(f"[greet] mode={_REPLY_MODE} cached={bool(cached_wav)}")
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
            if cached_wav:
                await _safe_send_bytes(websocket, cached_wav)
                print(f"[greet] cached_sent {(time.perf_counter()-t0)*1000:.0f}ms "
                      f"bytes={len(cached_wav)}")
            else:
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
                                speech.set_language(lang)
                                print(f"language switched to {lang}")
                        elif ctype == "barge_in":
                            # Cancel a pending fake-LLM reply so the user
                            # can speak again immediately.
                            if pending_reply is not None and not pending_reply.done():
                                pending_reply.cancel()
                                pending_reply = None
                                print("barge_in: cancelled pending reply")
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
                    committed_buflen = 0
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
                    if last_partial:
                        await _safe_send_text(websocket, json.dumps(
                            {"type": "transcript", "text": last_partial,
                             "provisional": True}))
                        print(f"[turn ] vad_end -> partial_shown: "
                              f"{(time.perf_counter()-turn_end_t0)*1000:.0f}ms "
                              f"chars={len(last_partial)}")
                    final_audio = bytes(audio_buffer)
                    # Reuse last partial as final if:
                    #   - turn audio fits inside the partial sliding window
                    #     (partial saw it all), AND
                    #   - partial was decoded recently (text fresh), AND
                    #   - partial covered ~all buffered audio at that time.
                    age = time.perf_counter() - last_partial_at
                    covered = last_partial_buflen >= len(final_audio) - 8000
                    fits_window = len(final_audio) <= _PARTIAL_WINDOW_BYTES
                    reuse = (
                        bool(last_partial)
                        and age < _FINAL_REUSE_PARTIAL_SECS
                        and covered
                        and fits_window
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
                    committed_buflen = 0
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
