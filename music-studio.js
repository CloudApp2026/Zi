(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("studio-form"), apiInput = $("api-base"), duration = $("duration");
  let pollTimer = null, polling = false, currentJob = null, supabase = null, spotifyToken = null;
  apiInput.value = localStorage.getItem("aio_api_base") || "";
  $("supabase-url").value = localStorage.getItem("zi_supabase_url") || "";
  $("supabase-key").value = sessionStorage.getItem("zi_supabase_key") || "";
  $("spotify-client-id").value = localStorage.getItem("zi_spotify_client_id") || "";
  $("supabase-url").addEventListener("change", () => localStorage.setItem("zi_supabase_url", $("supabase-url").value.trim()));
  $("supabase-key").addEventListener("change", () => sessionStorage.setItem("zi_supabase_key", $("supabase-key").value.trim()));
  $("spotify-client-id").addEventListener("change", () => localStorage.setItem("zi_spotify_client_id", $("spotify-client-id").value.trim()));
  duration.addEventListener("input", () => $("duration-value").textContent = duration.value);
  $("lyrics-mode").addEventListener("change", () => { $("lyrics-wrap").hidden = $("lyrics-mode").value !== "user"; });
  function setNotice(message, error = false) { $("notice").textContent = message; $("notice").style.color = error ? "#ff9b9b" : ""; }
  function apiUrl(path) { const base = apiInput.value.trim().replace(/\/$/, ""); if (!base) throw new Error("Enter your deployed FastAPI backend URL first."); return base + path; }
  async function request(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const admin = $("admin-token").value.trim(); if (admin) headers.Authorization = `Bearer ${admin}`;
    const response = await fetch(apiUrl(path), { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.error || `Backend request failed (${response.status}).`);
    return data;
  }
  function getSupabase() {
    const url = $("supabase-url").value.trim(), key = $("supabase-key").value.trim();
    if (!url || !key) throw new Error("Add your Supabase project URL and publishable/anon key in Connect your accounts.");
    if (!window.supabase?.createClient) throw new Error("Supabase client could not load.");
    if (!supabase) supabase = window.supabase.createClient(url, key);
    return supabase;
  }
  $("supabase-login").addEventListener("click", async () => {
    try { const sb = getSupabase(), email = $("supabase-email").value.trim(); if (!email) throw new Error("Enter your email first.");
      const { error } = await sb.auth.signInWithOtp({ email, options: { emailRedirectTo: location.href.split("?")[0] } });
      if (error) throw error; $("account-status").textContent = "Sign-in link sent. Open it on this device, then save your song.";
    } catch (e) { $("account-status").textContent = e.message; }
  });
  async function poll(jobId) {
    if (polling) return; polling = true;
    try {
      const job = await request("/api/generations/" + encodeURIComponent(jobId));
      setStatus(job.status);
      if (job.status === "succeeded") {
        clearInterval(pollTimer); const audioUrl = job.audio_url ? apiUrl(job.audio_url) : null;
        if (!audioUrl) throw new Error("The provider completed the job but returned no audio URL.");
        $("player").src = audioUrl; $("player").hidden = false; $("download").href = audioUrl; $("download").hidden = false;
        $("result-title").textContent = job.track_name || "Your generated song";
        $("result-description").textContent = "Your song is ready. Save the original audio and lyrics to your private Supabase library.";
        $("save-song").disabled = false; $("spotify-playlist").disabled = false;
        setNotice("Generation complete. Your song is ready."); $("generate").disabled = false;
      } else if (["failed", "canceled"].includes(job.status)) {
        clearInterval(pollTimer); setNotice(job.error || "Generation did not complete.", true); $("generate").disabled = false;
      } else setNotice(`Generating song sections: ${job.segments_done || 0}/${job.segments_total || "?"} complete…`);
    } catch (e) { clearInterval(pollTimer); setNotice(e.message, true); $("generate").disabled = false; }
    finally { polling = false; }
  }
  function setStatus(v) { $("status").textContent = String(v || "UNKNOWN").toUpperCase(); }
  apiInput.addEventListener("change", () => localStorage.setItem("aio_api_base", apiInput.value.trim()));
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); clearInterval(pollTimer); $("generate").disabled = true;
    $("player").hidden = true; $("download").hidden = true; $("save-song").disabled = true; $("spotify-playlist").disabled = true;
    $("result-title").textContent = "Creating your song…"; setStatus("QUEUED"); setNotice("Preparing lyrics and connecting to the music engine…");
    try {
      const title = $("track-name").value.trim() || "Untitled song";
      const brief = [$("prompt").value.trim(), `Genre: ${$("genre").value}`, `Mood: ${$("mood").value}`, `Lead instruments: ${$("instruments").value}`, `Energy: ${$("energy").value}`].join(". ");
      let lyrics = ""; const lyricsSource = $("lyrics-mode").value;
      if (lyricsSource === "user") { lyrics = $("lyrics").value.trim(); if (!lyrics) throw new Error("Paste your lyrics before generating."); }
      else {
        setNotice("Writing original lyrics…");
        const generated = await request("/api/lyrics", { method: "POST", body: JSON.stringify({ title, prompt: brief, genre: $("genre").value, mood: $("mood").value }) });
        lyrics = generated.lyrics || ""; if (!lyrics) throw new Error("The lyrics model returned empty lyrics.");
        $("lyrics").value = lyrics; $("lyrics-wrap").hidden = false; $("lyrics-mode").value = "user";
      }
      const health = await request("/api/health"); if (health.status !== "ok") throw new Error("Backend health check failed.");
      $("engine").textContent = `Replicate · ${health.model}`;
      if (!health.ffmpeg) throw new Error("The backend has no ffmpeg installed.");
      const payload = { track_name: title, prompt: `${brief}. Full song with lead vocals.`, duration: Number(duration.value), lyrics, lyrics_mode: lyricsSource, vocal_style: $("vocal-style").value.trim() };
      const job = await request("/api/generations", { method: "POST", body: JSON.stringify(payload) });
      currentJob = { ...payload, id: job.id }; $("job-id").textContent = job.id; setStatus(job.status); setNotice("Generation started. Checking progress…");
      pollTimer = setInterval(() => poll(job.id), 8000); await poll(job.id);
    } catch (e) { setStatus("ERROR"); setNotice(e.message, true); $("result-title").textContent = "Configuration needed"; $("generate").disabled = false; }
  });
  $("save-song").addEventListener("click", async () => {
    try {
      const sb = getSupabase(); const { data: { user }, error: authError } = await sb.auth.getUser();
      if (authError || !user) throw new Error("Sign in to Supabase first using the email link.");
      if (!currentJob?.id) throw new Error("There is no completed song to save.");
      const audio = await fetch(apiUrl(`/api/generations/${encodeURIComponent(currentJob.id)}/audio`)); if (!audio.ok) throw new Error("Could not retrieve generated audio.");
      const blob = await audio.blob(), path = `${user.id}/${crypto.randomUUID()}.mp3`;
      const { error: uploadError } = await sb.storage.from("zi-audio").upload(path, blob, { contentType: "audio/mpeg", upsert: false }); if (uploadError) throw uploadError;
      const { data: song, error: songError } = await sb.from("songs").insert({ user_id: user.id, title: currentJob.track_name, description: currentJob.prompt, genre: $("genre").value, mood: $("mood").value, status: "completed" }).select().single();
      if (songError) throw songError;
      const { error: lyricError } = await sb.from("lyrics").insert({ song_id: song.id, user_id: user.id, source: currentJob.lyrics_mode, content: currentJob.lyrics, version: 1, is_current: true }); if (lyricError) throw lyricError;
      const { error: assetError } = await sb.from("audio_assets").insert({ song_id: song.id, user_id: user.id, storage_path: path, asset_type: "full_song", mime_type: "audio/mpeg" }); if (assetError) throw assetError;
      setNotice("Song, lyrics and audio saved to your private Zi library."); $("account-status").textContent = `Saved song ${song.id}`;
    } catch (e) { setNotice(`Save failed: ${e.message}`, true); }
  });
  async function spotifyAuth() {
    const clientId = $("spotify-client-id").value.trim(); if (!clientId) throw new Error("Enter your Spotify app client ID first.");
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
    const verifier = [...crypto.getRandomValues(new Uint8Array(64))].map(b => alphabet[b % alphabet.length]).join("");
    sessionStorage.setItem("zi_spotify_client_id", clientId);
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
    const challenge = btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
    sessionStorage.setItem("zi_spotify_verifier", verifier);
    const params = new URLSearchParams({ client_id: clientId, response_type: "code", redirect_uri: location.origin + location.pathname, code_challenge_method: "S256", code_challenge: challenge, scope: "playlist-modify-private playlist-modify-public user-read-private" });
    location.href = "https://accounts.spotify.com/authorize?" + params;
  }
  async function spotifyRequest(path, options = {}) { const r = await fetch("https://api.spotify.com/v1" + path, { ...options, headers: { Authorization: `Bearer ${spotifyToken}`, "Content-Type": "application/json", ...(options.headers || {}) } }); const d = await r.json().catch(()=>({})); if (!r.ok) throw new Error(d.error?.message || "Spotify request failed."); return d; }
  async function finishSpotifyAuth() {
    if (!$("spotify-client-id").value.trim()) $("spotify-client-id").value = sessionStorage.getItem("zi_spotify_client_id") || "";
    const code = new URLSearchParams(location.search).get("code"); if (!code) return;
    const verifier = sessionStorage.getItem("zi_spotify_verifier"); if (!verifier) return;
    const body = new URLSearchParams({ client_id: $("spotify-client-id").value.trim(), grant_type: "authorization_code", code, redirect_uri: location.origin + location.pathname, code_verifier: verifier });
    const r = await fetch("https://accounts.spotify.com/api/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body });
    const data = await r.json(); if (!r.ok) throw new Error(data.error_description || "Spotify authorization failed.");
    spotifyToken = data.access_token; sessionStorage.removeItem("zi_spotify_verifier"); history.replaceState({}, "", location.pathname);
    $("account-status").textContent = "Spotify connected for this browser session.";
  }
  $("spotify-connect").addEventListener("click", () => { try { spotifyAuth().catch(e => $("account-status").textContent = e.message); } catch (e) { $("account-status").textContent = e.message; } });
  $("spotify-playlist").addEventListener("click", async () => {
    try {
      if (!spotifyToken) throw new Error("Connect Spotify first."); if (!currentJob) throw new Error("Create a song first.");
      const matches = await spotifyRequest(`/search?type=track&limit=5&q=${encodeURIComponent(`${$("genre").value} ${$("mood").value} ${currentJob.track_name}`)}`);
      const uris = (matches.tracks?.items || []).map(t => t.uri); if (!uris.length) throw new Error("No matching Spotify tracks found.");
      const me = await spotifyRequest("/me");
      const playlist = await spotifyRequest(`/users/${me.id}/playlists`, { method: "POST", body: JSON.stringify({ name: `Inspired by ${currentJob.track_name}`, description: "A Zi-curated playlist inspired by your generated song. The original audio remains in your Zi library.", public: false }) });
      await spotifyRequest(`/playlists/${playlist.id}/tracks`, { method: "POST", body: JSON.stringify({ uris }) });
      setNotice("Spotify inspiration playlist created: " + playlist.name); $("account-status").textContent = "Spotify playlist: " + playlist.external_urls.spotify;
    } catch (e) { setNotice(`Spotify: ${e.message}`, true); }
  });
  finishSpotifyAuth().catch(e => { $("account-status").textContent = e.message; });
})();
