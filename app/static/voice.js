  /* ====================================================================
     Noa - a living plasma orb bound to the assistant's voice state.
     Blob shape is procedural: points on a circle wobbled by sine waves;
     lobe positions are angle-locked so it pulses in place (no rotation).
       idle       : slow soft wobble
       listening  : small + tight tense wobble, halo pulls inward (suck in)
       processing : gentle quicker pulse, violet glow
       speaking   : big + loose waves, halo radiates outward (voice out)
  ==================================================================== */
  const isi       = document.getElementById('isi');
  const core      = document.getElementById('noa-core');
  const blob      = document.getElementById('blob');
  const subEl     = document.getElementById('noa-sub');
  const transcript= document.getElementById('transcript');
  let livePartialBubble = null;
  let followTranscript = true;

  // Reload the page as a different user. The server mints a JWT for this
  // subject; today it only shows up in server logs.
  function switchUser(){
    const v = (document.getElementById('user-input').value || '').trim();
    if(!v) return;
    const r = (document.getElementById('role-input').value || 'admin');
    location.search = '?user=' + encodeURIComponent(v) + '&role=' + encodeURIComponent(r);
  }

  transcript.addEventListener('scroll', () => {
    const bottomGap = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight;
    followTranscript = bottomGap < 24;
  });

  // --- debug mock helpers ---
  const MOCK_PHRASES = [
    "Hello!",
    "I'm listening.",
    "Could you tell me more about that? I'm particularly interested in how the knowledge graph integration handles real-time updates without blocking the primary dialogue thread.",
    "That sounds interesting.",
    "Yes, I can help with that. What specifically do you need?",
    "Noa is a privacy-first assistant designed to run on local hardware whenever possible, ensuring your data stays yours while providing high-quality voice interactions and intelligent response synthesis.",
    "Short reply.",
    "This is a significantly longer message designed to test the multi-line wrapping and the scrolling behavior of the transcript drawer when there are multiple bubbles of varying heights active at the same time."
  ];
  function mockMsg(role) {
    const text = MOCK_PHRASES[Math.floor(Math.random() * MOCK_PHRASES.length)];
    bubble(role, text);
  }

  // --- procedural wobble: blob = N points on a circle, each radius
  //     modulated by layered sine waves. State tunes amplitude/character.
  const CX = 100, CY = 100, N = 14;
  const ANG = Array.from({length:N}, (_,i)=> (i/N)*Math.PI*2);

  // per-state wobble config: base radius, amplitude, wave speed, lobe count
  const WOBBLE = {
    idle:       { base: 66, amp: 4,  speed: .55, waves: 2 },
    listening:  { base: 56, amp: 10, speed: 2.6, waves: 3 },  // tight, alert, quick
    processing: { base: 61, amp: 5,  speed: 1.6, waves: 3 },  // gentle quicker pulse
    speaking:   { base: 78, amp: 11, speed: .85, waves: 2.4 }, // broad, alive waves
    error:      { base: 60, amp: 15, speed: 4.0, waves: 4 },  // jittery/spiky
    waking:     { base: 42, amp: 0,  speed: 0,   waves: 0 },  // phase 1: shrink
    woke:       { base: 82, amp: 0,  speed: 0,   waves: 0 },  // phase 2: expand
  };

  let auraState = 'idle';

  // debug toggle logic
  const debugToggle = document.getElementById('debug-toggle');
  const debugPanel = document.getElementById('debug-panel');
  debugToggle.onclick = () => debugPanel.classList.toggle('open');
  // live config eased toward the target state's WOBBLE — no hard snap.
  let curCfg = { ...WOBBLE.idle };
  let phase = 0;
  let lastT = 0;

  // Caption text per state — idle invites the tap; others show the state.
  // Transient captions (errors, mic failures) go through setCaption() AFTER
  // the setState() that triggered them, so they win over the state default.
  const CAPTION = { idle: 'tap to wake' };
  const setCaption = (t) => { subEl.textContent = t; };
  function setState(s) {
    if (s === auraState) return;
    auraState = s;
    isi.dataset.state = s;
    setCaption(CAPTION[s] || s);

    // special handling for 'waking' chain
    if (s === 'waking') {
      setTimeout(() => {
        if (auraState === 'waking') setState('woke');
      }, 400);
    }
    else if (s === 'woke') {
      setTimeout(() => {
        if (auraState === 'woke') setState('listening');
      }, 500);
    }
  }

  // build a smooth closed SVG path through wobbled points
  function wobblePath(t, level) {
    const dt = lastT ? t - lastT : 0;
    lastT = t;

    const tgt = WOBBLE[auraState] || WOBBLE.idle;
    // ease base/amp/speed toward target every frame -> smooth state morph.
    // Significantly slower easing (0.015 instead of 0.04) for a relaxed, 
    // liquid-like transition between states.
    const morphEase = 0.015;
    const waveEase = 0.01;

    curCfg.base  += (tgt.base  - curCfg.base)  * morphEase;
    curCfg.amp   += (tgt.amp   - curCfg.amp)   * morphEase;
    curCfg.speed += (tgt.speed - curCfg.speed) * morphEase;
    curCfg.waves += (tgt.waves - curCfg.waves) * waveEase;

    // phase accumulation prevents the "jumping" effect when speed changes
    phase += dt * curCfg.speed;

    const cfg = curCfg;
    const reactGain = auraState==='speaking' ? 34
                    : auraState==='listening' ? 38 : 12;
    const ampNow = cfg.amp + level * reactGain;
    const pts = ANG.map((a) => {
      // lobe SHAPE fixed by angle (a*waves) — peaks stay put, no rotation.
      // phase only breathes the amplitude, so the blob pulses in place.
      const env  = Math.sin(phase);
      const env2 = Math.sin(phase * 1.7 + 1.3);
      const w = Math.cos(a*cfg.waves)        * ampNow      * env
              + Math.cos(a*(cfg.waves+1)+.7) * ampNow*.45  * env2;
      const r = cfg.base + w;
      return [CX + Math.cos(a)*r, CY + Math.sin(a)*r];
    });
    // quadratic smoothing through midpoints
    let d = `M${((pts[0][0]+pts[N-1][0])/2).toFixed(1)},${((pts[0][1]+pts[N-1][1])/2).toFixed(1)}`;
    for (let i=0;i<N;i++){
      const cur = pts[i], nxt = pts[(i+1)%N];
      const mx = (cur[0]+nxt[0])/2, my = (cur[1]+nxt[1])/2;
      d += ` Q${cur[0].toFixed(1)},${cur[1].toFixed(1)} ${mx.toFixed(1)},${my.toFixed(1)}`;
    }
    return d + 'Z';
  }

  // --- audio-amplitude reactivity ------------------------------------
  let analyser = null, ampData = null, rafId = null, micAnalyser = null;
  function rms() {
    if (!analyser) return 0;
    analyser.getByteTimeDomainData(ampData);
    let sum = 0;
    for (let i = 0; i < ampData.length; i++) {
      const v = (ampData[i] - 128) / 128;
      sum += v * v;
    }
    return Math.sqrt(sum / ampData.length); // 0..~1
  }
  // smoothed audio level so the wobble eases instead of snapping
  let smoothLevel = 0;
  function animate() {
    // enable reactivity for both listening (user) and speaking (assistant)
    const isReactive = auraState === 'listening' || auraState === 'speaking';
    const target = isReactive ? Math.min(1, rms() * 6) : 0;

    // synth-wave envelope: snap up on signal, decay slow on release
    const k = target > smoothLevel ? 0.35 : 0.08;
    smoothLevel += (target - smoothLevel) * k;
    // Intentional debug override — bypasses setCaption() on purpose: this is a
    // per-frame write behind an opt-in flag, not a state caption. Keep it raw.
    if (window.DEBUG_LEVEL) subEl.textContent = 'lvl ' + smoothLevel.toFixed(2);
    const t = performance.now() / 1000;
    blob.setAttribute('d', wobblePath(t, smoothLevel));
    rafId = requestAnimationFrame(animate);
  }
  // keep the blob alive even before the mic starts (idle wobble)
  function idleAnimate() {
    if (rafId) return;
    const tick = () => {
      const t = performance.now() / 1000;
      blob.setAttribute('d', wobblePath(t, 0));
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
  }
  idleAnimate();

  function bindMicAnalyser() {
    if (micAnalyser) { analyser = micAnalyser; ampData = new Uint8Array(micAnalyser.fftSize); }
  }

  // ================= voice transport =================================
  let socket=null, audioContext=null, processor=null, stream=null;
  let currentAssistantMsg=null, playbackCtx=null;
  let audioQueue = [];
  let isQueuePlaying = false;
  let currentSource = null;

  function scrollTranscript(){
    if (followTranscript) {
      transcript.scrollTo({ top: transcript.scrollHeight, behavior:'smooth' });
    }
  }

  function bubble(role, text){
    const b=document.createElement('div');
    b.className=`bubble ${role}`;
    b.textContent=text;
    transcript.appendChild(b);
    scrollTranscript();
    return b;
  }

  // Typed input: bypass mic/ASR and drive the same reply path. Requires the
  // socket to be open — tap the orb first to connect.
  function sendText(ev){
    if(ev) ev.preventDefault();              // stop Enter from also submitting
    const inp=document.getElementById('text-input');
    const msg=(inp.value||'').trim();
    if(!msg) return;
    if(!socket || socket.readyState !== WebSocket.OPEN){
      setCaption('tap the orb to connect first');
      return;
    }
    inp.value='';                            // clear first → re-entry can't resend
    bubble('user', msg);
    currentAssistantMsg=null;
    setState('processing');
    socket.send(JSON.stringify({type:'text_input', text: msg}));
  }

  async function processAudioQueue() {
    if (audioQueue.length === 0) {
      isQueuePlaying = false;
      if (auraState === 'speaking') { setState('listening'); bindMicAnalyser(); }
      return;
    }
    isQueuePlaying = true;
    const arrayBuffer = audioQueue.shift();
    try {
      if(!playbackCtx) playbackCtx=new (window.AudioContext||window.webkitAudioContext)();
      const buf=await playbackCtx.decodeAudioData(arrayBuffer.slice(0));
      const src=playbackCtx.createBufferSource();
      src.buffer=buf;
      const an=playbackCtx.createAnalyser(); an.fftSize=512;
      src.connect(an); an.connect(playbackCtx.destination);
      analyser=an; ampData=new Uint8Array(an.fftSize);
      setState('speaking');
      currentSource = src;
      src.onended = () => {
        if (currentSource === src) currentSource = null;
        processAudioQueue();
      };
      src.start();
    } catch(err) {
      console.error('Playback decode failed:', err);
      processAudioQueue();
    }
  }

  // route assistant playback through an analyser so the orb reacts to TTS
  async function playReactive(arrayBuffer){
    audioQueue.push(arrayBuffer);
    if (!isQueuePlaying) processAudioQueue();
  }

  async function startVoice(){
    try{
      if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia){
        throw new Error(window.isSecureContext
          ? 'Microphone API unavailable in this browser.'
          : 'Microphone needs a secure context. Open this page over HTTPS or via http://localhost.');
      }
      stream=await navigator.mediaDevices.getUserMedia({audio:true});
      audioContext=new (window.AudioContext||window.webkitAudioContext)({sampleRate:16000});
      const source=audioContext.createMediaStreamSource(stream);

      micAnalyser=audioContext.createAnalyser(); micAnalyser.fftSize=512;
      source.connect(micAnalyser);
      bindMicAnalyser();

      processor=audioContext.createScriptProcessor(4096,1,1);
      const proto=location.protocol==='https:'?'wss:':'ws:';
      const wsToken=document.querySelector('meta[name="ws-token"]').content;
      const initialLang=(localStorage.getItem('noaLang')||'en').toLowerCase();
      socket=new WebSocket(`${proto}//${location.host}/api/v1/voice/ws?token=${encodeURIComponent(wsToken)}&lang=${encodeURIComponent(initialLang)}`);
      // Live language switch: nav radio dispatches noa-lang-change; we
      // forward to the server so the next partial/final uses the new
      // language without dropping the session.
      window.addEventListener('noa-lang-change', function(ev){
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({type:'set_language', language: ev.detail}));
        }
      });
      socket.binaryType='arraybuffer';

      socket.onopen=()=>{
        setState('waking');
        if(rafId){ cancelAnimationFrame(rafId); rafId=null; }  // stop idle loop
        animate();                                             // start reactive loop
      };

      socket.onerror = (err) => {
        console.error('WebSocket error:', err);
        setState('error');
        setCaption('connection error');
      };

      socket.onclose = (ev) => {
        if (!ev.wasClean) {
          setState('error');
          setCaption('connection lost');
        }
      };

      socket.onmessage=async (ev)=>{
        if(ev.data instanceof ArrayBuffer){
          await playReactive(ev.data);
        }else{
          const d=JSON.parse(ev.data);
          if(d.type==='user_transcript_chunk'){
            const text = ((d.committed||'') + ' ' + (d.tail||'')).trim();
            if(!livePartialBubble) {
              livePartialBubble = bubble('user','');
            }
            livePartialBubble.textContent = text;
            scrollTranscript();
          }
          else if(d.type==='transcript'){
            // Provisional transcripts (from the last partial) replace
            // the live bubble text but keep the ref so the subsequent
            // final transcript can overwrite the same bubble.
            if(livePartialBubble){
              livePartialBubble.textContent = d.text;
              if(!d.provisional) livePartialBubble = null;
            } else {
              const b = bubble('user', d.text);
              if(d.provisional) livePartialBubble = b;
            }
          }
          else if(d.type==='response_chunk'){
            if(!currentAssistantMsg) currentAssistantMsg=bubble('assistant','');
            currentAssistantMsg.textContent+=d.text;
            scrollTranscript();
          }
          else if(d.type==='response'){
            if(!currentAssistantMsg) bubble('assistant',d.text);
            else currentAssistantMsg.textContent=d.text;
            currentAssistantMsg=null;
          }
          else if(d.type==='status'){
            // setState() below already writes the lowercased state name; no manual caption needed.
            if(d.text==='Listening...'||d.text==='Waiting...'){ currentAssistantMsg=null; livePartialBubble=null; setState('listening'); bindMicAnalyser(); }
            else if(d.text==='Processing...'){ setState('processing'); }
            else if(d.text==='Speaking...'){ setState('speaking'); }
          }
          else if(d.type==='stop_audio'){
            audioQueue = [];
            if (currentSource) { try { currentSource.stop(); } catch(e) {} currentSource = null; }
            isQueuePlaying = false;
            livePartialBubble = null;
            setState('listening'); bindMicAnalyser();
          }
        }
      };

      // Barge-in: while the assistant is processing/speaking, watch mic
      // RMS. If voice activity persists past _BARGE_VOICE_MS, send one
      // barge_in to the server (cooldown until next state change).
      // Threshold sized to ignore short backchannels ("ok", "hm", "yeah")
      // — those run ~300–500ms. Real interruptions are usually 800ms+.
      const _BARGE_RMS = 0.05;          // input level threshold
      const _BARGE_VOICE_MS = 900;      // sustained voice to trigger
      let _bargeVoiceMs = 0;
      let _bargeCooldown = false;
      processor.onaudioprocess=(e)=>{
        if(!(socket&&socket.readyState===WebSocket.OPEN)) return;
        const inp=e.inputBuffer.getChannelData(0);

        // Barge-in detector (only when not in 'listening' state).
        const interruptible = (auraState === 'processing' || auraState === 'speaking');
        if (interruptible && !_bargeCooldown) {
          let sum = 0;
          for (let i=0;i<inp.length;i++){ const v=inp[i]; sum += v*v; }
          const rms = Math.sqrt(sum / inp.length);
          if (rms > _BARGE_RMS) {
            _bargeVoiceMs += e.inputBuffer.duration * 1000;
            if (_bargeVoiceMs >= _BARGE_VOICE_MS) {
              socket.send(JSON.stringify({type:'barge_in'}));
              _bargeCooldown = true;
              _bargeVoiceMs = 0;
            }
          } else {
            _bargeVoiceMs = 0;
          }
        } else {
          _bargeVoiceMs = 0;
          if (!interruptible) _bargeCooldown = false;
        }

        const pcm=new Int16Array(inp.length);
        for(let i=0;i<inp.length;i++) pcm[i]=Math.max(-1,Math.min(1,inp[i]))*0x7FFF;
        socket.send(pcm.buffer);
      };
      source.connect(processor);
      processor.connect(audioContext.destination);
    }catch(err){
      console.error('Mic error:',err);
      setCaption(err.message||'mic blocked');
    }
  }

  function stopVoice(){
    if(socket) socket.close();
    if(processor) processor.disconnect();
    if(audioContext) audioContext.close();
    if(stream) stream.getTracks().forEach(t=>t.stop());
    if(rafId){ cancelAnimationFrame(rafId); rafId=null; }
    analyser=micAnalyser=null;
    smoothLevel=0;
    auraState='';                 // force setState to re-apply
    setState('idle');             // caption -> 'tap to wake'
    idleAnimate();                // resume idle wobble loop
  }

  // Orb is the toggle: a live session stops, anything else (idle, error) starts.
  // Gating on socket liveness — not auraState==='idle' — means tapping an
  // errored orb retries instead of needing two taps to get back to idle.
  isi.addEventListener('click', () => {
    const live = socket && socket.readyState <= WebSocket.OPEN;  // CONNECTING or OPEN
    if (live) stopVoice();
    else startVoice();
  });
