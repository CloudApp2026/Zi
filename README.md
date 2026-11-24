# Zi — AI Song Studio

Zi turns a creative brief into a complete song workflow: AI-written or user-written lyrics, vocal-style direction, full-song generation through a configurable vocal-capable Replicate model, private Supabase song/audio storage, and Spotify playlist discovery. **fal.ai is intentionally not integrated.**

## Project structure
- `music-studio.html`, `music-studio.css`, `music-studio.js` — browser studio and account integrations
- `backend/` — FastAPI service, Replicate generation, lyric generation, local job orchestration and RouteNote packaging
- `index.html`, `releases.html`, `releases.js` — operations and release workflows
- `.github/workflows/pages.yml` — GitHub Pages deployment

## Run locally
Frontend: `python -m http.server 8080` → http://localhost:8080

Backend:
```bash
cd backend && pip install -r requirements.txt
cp .env.example .env  # edit values; never commit .env
set -a && . ./.env && set +a
uvicorn main:app --reload --port 8000
```

## Required backend configuration
- `REPLICATE_API_TOKEN` — server-side Replicate token
- `LYRICS_MODEL=meta/meta-llama-3-8b-instruct` — Replicate text model with a `prompt` input; used for AI-written lyrics
- `LYRICS_EXTRA_INPUT` — output token/temperature settings for the lyrics model
- `MUSIC_MODEL=minimax/music-2.6` — official Replicate model supporting full-length songs with sung vocals and lyrics
- `MODEL_SUPPORTS_VOCALS=1` — enabled for the verified MiniMax Music 2.6 full-song model
- `MODEL_LYRICS_KEY=lyrics` — exact input field name for lyrics in MiniMax Music 2.6
- `MODEL_DURATION_KEY=` — MiniMax 2.6 controls length through the prompt, not a numeric duration input
- `MODEL_LICENSE_COMMERCIAL=1` — only after verifying the selected model's commercial-use terms
- `ALLOWED_ORIGINS`, `ADMIN_TOKEN` — restrict CORS and protect generation/lyrics endpoints

Zi refuses to start music generation while `MODEL_SUPPORTS_VOCALS` is off, preventing the old instrumental-only model from being mistaken for a complete-song engine. The selected model's input schema must match `MODEL_LYRICS_KEY`; no provider can be assumed to accept a generic lyrics field. MiniMax Music 2.6 accepts a lyrics field up to 3,500 characters and generates complete songs, commonly 2–4 minutes and up to 6 minutes.

## Supabase
The existing `zi-music` project already has `profiles`, `songs`, `lyrics`, `generation_jobs`, `audio_assets`, `favorites` and a private `zi-audio` bucket. In Studio, provide the project URL and publishable/anon key, then sign in using the email magic link. The browser uploads the generated MP3 to `zi-audio` and writes song, lyric and audio-asset metadata. Keep RLS enabled and never put a service-role key in the browser.

## Spotify
Create a Spotify Developer app, add the exact Studio URL (for example `https://<owner>.github.io/Zi/music-studio.html`) as a Redirect URI, and enter its Client ID in Studio. OAuth uses Authorization Code with PKCE. Zi can search Spotify's catalogue and create a private inspiration playlist. Spotify's Web API does **not** let third-party apps upload arbitrary generated MP3s into Spotify's catalogue; original Zi audio stays in Supabase.

## Important rollout note
This code provides the full-song integration path, but generation requires selecting and configuring a Replicate model that supports vocals and lyrics. The default vocal model is `minimax/music-2.6`; its Replicate schema accepts `lyrics`, `prompt`, `is_instrumental=false`, and `output_format`. Configure a separate `LYRICS_MODEL` for AI-written lyrics, and verify model terms before enabling commercial release. fal.ai remains cancelled.
