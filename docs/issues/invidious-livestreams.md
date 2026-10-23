# Invidious: livestreams never start (empty DASH manifest)

**Status:** OPEN — upstream, not actionable in this repo · **Last updated:** 2026-10-24 00:35 CEST
**Track:** **I** — new
**Host:** `catafalco` (`invidious.catafal.co`, Invidious `2026.10.22-b852c4b`)
**Scope:** `roles/invidious` (Invidious + `invidious-companion` + `invidious-db`), the SWAG
vhost `invidious.subdomain.conf`, and the web player in the browser.

> **Short version.** The stack is healthy and **ordinary videos play**. **Active
> livestreams do not play at all**, and the reported flow ("Latest trends → open a video")
> hits livestreams 100 % of the time because the trending page was nothing but live streams
> when this was measured. The cause is upstream: `invidious-companion` builds the DASH
> manifest with `youtubei.js`, which silently drops live (OTF) formats that carry no
> `initRange`/`indexRange`, so the manifest is a valid XML document with an **empty
> `<Period/>`**. The web player's only live-capable path (HLS) is not offered because the
> player response contains no `hlsManifestUrl` any more. No configuration in this repo
> changes either fact.

---

## Verdict

| # | Finding | Evidence |
|---|---|---|
| **I-01** | Rendered player is broken **only for livestreams**; VOD playback is fully functional end-to-end | §1: headless Chromium plays 4/4 VODs (`currentTime` advances, buffer grows); 3/3 live streams stay at `readyState 0`, `currentTime 0` |
| **I-02** | The DASH manifest of a live stream is a **417-byte `<Period/>`** (`mediaPresentationDuration="PTNaNS"`, 0 `<AdaptationSet>`), while a VOD manifest is 42 952 B with 16 `<Representation>` in 4 `<AdaptationSet>` | §2 |
| **I-03** | `dash.js` (video.js VHS) throws on it: `TypeError: Cannot read properties of undefined (reading 'length')` in `addPropertiesToMaster` ← `parseMasterXml`. That is the "infinite loading" the user sees | §3 |
| **I-04** | The frontend's live path (HLS) is never taken: `/api/v1/videos/<id>` returns **no `hlsUrl`** (`streamingData.hlsManifestUrl` absent), so `player.ecr`'s `hls_manifest_url && live_now` branch is skipped and only the empty DASH source remains | §4 |
| **I-05** | Root cause is in `invidious-companion` → `youtubei.js` `StreamingInfo.getFormatGroupings()`, which `continue`s on every format without `init_range`/`index_range` unless `is_type_otf` or post-live-DVR. Live formats from the current fallback client (`TV_SIMPLY`) are plain, not OTF, so **all** of them are dropped | §5 |
| **I-06** | The companion only got those URLs from its **fallback client** at all: the primary `WEB` request returns no URLs ("No URLs found for adaptive formats", logged per request, including for VOD) | §6 |
| **I-07** | Ruled out: SWAG/nginx, Docker networking, the vhost variables, DB, PO token, companion auth (`check`), `ip=` URL locking, host load, Ansible rendering | §7 |
| **I-08** | Upstream knows and has not shipped a fix: `iv-org/invidious-companion#7` (**open**, "handle hls for apple devices and hls livestream"), `#375` (the exact symptom, closed **as duplicate**). `youtubei.js` main still has the same filter (checked 2026-10-24, v18.3.0 released 2026-10-23) | §8 |
| **I-09** | **No image pin or rollback helps.** The companion's `/api/manifest/dash` route has been built from `youtubei.js`'s `toDash()` since 2024-11 (file history), so no released companion ever emitted a playable live DASH manifest | §8 |

**Do not re-investigate I-02…I-06 as a local misconfiguration.** Re-run §9 after an image
update; that is the whole maintenance procedure.

---

## 1. Reproducibility: what works and what does not

Measured 2026-10-24 ~00:20–00:35 CEST from the laptop (same public IP as the server).

### VODs play

`/api/v1/videos/xRMPKQweySE` → 1 muxed (`itag 18`) + 30 adaptive formats (mp4 + webm); the
companion's manifest keeps the 16 mp4 representations (42 952 B).
A headless Chromium (CDP, `play()` called, muted) sampled the `<video>` element:

```
 +7s {"t":2.96,"rs":4,"ns":2,"paused":false,"dur":153.2,"buf":[0,39.9],"err":null}
+10s {"t":5.96,"rs":4,"ns":2,"paused":false,"dur":153.2,"buf":[0,45],"err":null}
+13s {"t":8.97,"rs":4,"ns":2,"paused":false,"dur":153.2,"buf":[0,49.9],"err":null}
...
+25s {"t":20.98,"rs":4,...                                    "buf":[0,74.4]}
```

Same result for `jZZ1cMD6r38`, `GxI6k5wDKXo`, `6dnwn5Cfy8A` (0 failed media requests, 0 HTTP ≥ 400).
As an independent check, the raw media URL was fetched directly with a byte range:

```
$ curl -sL -r 0-200000 "<formatStreams[0].url>"
HTTP 206, 200001 bytes, Content-Type: video/mp4, file(1): ISO Media, MP4 v2
```

So the tooling to *prove* a working stream exists and passes on VOD.

### Livestreams do not

Three live streams (`kdk6BoavEeI`, `nHEI1Wb9jtA`, `xcG7Ltmxa58`):

```
liveNow=true  lengthSeconds=0  isPostLiveDvr=false  formatStreams=0  adaptiveFormats=13…19
 +7s {"t":0,"rs":0,"ns":2,"paused":false,"dur":"NaN","buf":null,"err":null}
+10s {"t":0,...} +13s {"t":0,...} … (+25s identical: nothing is ever buffered)
```

### Why the user always lands on the broken case

At measurement time **all 15 entries** of `/api/v1/trending?region=IT` were live streams
(`lengthSeconds=0`, `formatStreams=0`). The trending extractor does not set `liveNow`, so the
grid renders them like normal videos; clicking one is the reported "player keeps loading".
This is not a bad-luck sample — a trending page of live streams is normal at peak hours in
that region.

---

## 2. The manifest itself

```sh
$ curl -sL -o m.xml -w '%{size_download}\n' \
    https://invidious.catafal.co/api/manifest/dash/id/kdk6BoavEeI
417

$ cat m.xml
<?xml version="1.0" encoding="utf-8"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011"
minBufferTime="PT1.500S" profiles="urn:mpeg:dash:profile:isoff-main:2011" type="static"
mediaPresentationDuration="PTNaNS" …><Period/></MPD>
```

`PTNaNS` and `<Period/>` are the signature of "the generator had zero usable formats"
(`getDuration()` returned `NaN`, both `audio_sets` and `video_sets` empty).
The same request for a VOD returns 42 952 B with 16 `<Representation>` elements in 4 `<AdaptationSet>`s.

Note the shape of the response, which is what makes this hard to see from monitoring:
`GET /api/manifest/dash/id/<id>` is a **302** to `/companion/api/manifest/dash/id/<id>` and the
companion answers **200** — the failure is a semantically empty body, not an HTTP error.

The live `adaptiveFormats` entries have `itag`, `type`, `qualityLabel`, `bitrate`, `url` and
`clen=-1` — and **no `init`/`index` keys at all** (`/api/v1/videos/<id>` omits `init`/`index`
when YouTube did not send `initRange`/`indexRange`).

---

## 3. What the browser actually reports

Console of the watch page (headless Chromium):

```
EXCEPTION: TypeError: Cannot read properties of undefined (reading 'length')
    at addPropertiesToMaster (…/videojs/video.js:40511)
    at parseMasterXml      (…/video.js:43046)
    at DashPlaylistLoader.handleMaster_ (…/video.js:43649)
```

video.js/VHS parses the MPD, finds no `AdaptationSet`, and the tech never leaves
`readyState 0` (no `error` event either, because nothing failed at the HTTP level) — hence a
spinner forever.

The unrelated `TypeError: Cannot set properties of null (setting 'onclick')` at
`js/watch.js:200` appears on *every* watch page (VOD too) and is **not** part of this bug.

---

## 4. Why there is no HLS fallback

Invidious' web player only knows one live-capable source
(`src/invidious/views/components/player.ecr`):

```crystal
<% if (hlsvp = video.hls_manifest_url) && video.live_now && !CONFIG.disabled?("livestreams") %>
    <source src="<%= URI.parse(hlsvp).request_target %>…" type="application/x-mpegURL" label="livestream">
```

and `hls_manifest_url` is just `info["streamingData"]["hlsManifestUrl"]` (`src/invidious/videos.cr`),
i.e. **whatever the companion's player response contains** (with a companion configured,
`YoutubeAPI.player` is always proxied to it — `_post_invidious_companion`).
Measured: `/api/v1/videos/kdk6BoavEeI` has **no `hlsUrl` field** → `hlsManifestUrl` is absent →
the HLS branch is skipped → the empty DASH source is all that is left.

The HLS endpoints (`/api/manifest/hls_variant/…`) answer 403 for a bare URL because they proxy
YouTube's `manifest.googlevideo.com` path and need the signed query string that only
`hlsManifestUrl` carries.

---

## 5. Root cause (upstream code path)

`invidious-companion` `src/routes/invidious_routes/dashManifest.ts`:

```ts
const dashFile = await FormatUtils.toDash(
    videoInfo.streaming_data,
    videoInfo.page[0].video_details?.is_post_live_dvr,  // ← false for an active stream
    …
);
```

`FormatUtils.toDash` is `youtubei.js`'s `DashManifest`, which calls
`StreamingInfo.getStreamingInfo()`. In `StreamingInfo.ts`:

```ts
for (const format of formats) {
  if (((!format.index_range || !format.init_range) && !format.is_type_otf && !is_post_live_dvr)) {
    continue;                                  // ← every live format is dropped here
  }
```

Active live formats are time-addressed OTF streams. The formats the companion receives are
**not** flagged OTF (upstream measured `isTypeOtf: false`) and have no init/index ranges, so
`audio_sets`/`video_sets` end up empty and the MPD is `<Period/>`.

`roles/invidious/tasks/main.yml` runs exactly that code:
`quay.io/invidious/invidious-companion:latest`, whose running container started 2026-10-22 —
i.e. built from upstream `master` at or after `fcb0456` (2026-10-18), which pins
`youtubei.js` v18.2.0.

---

## 6. The companion is already degraded before that

`docker logs invidious-companion` (also visible via MCP
`get_service_logs(service="invidious-companion")`), on every player request:

```
<-- POST /companion/youtubei/v1/player
[WARNING] No URLs found for adaptive formats. Falling back to other YT clients.
[WARNING] Trying fallback YT client TV_SIMPLY
--> POST /companion/youtubei/v1/player 200 278ms
```

The primary `WEB` client returns formats without `url`, so `youtubePlayerReq()` swaps in
`TV_SIMPLY`'s `formats`/`adaptiveFormats` (added upstream in `#371`, 2026-08-10) — and that
swap does **not** copy `hlsManifestUrl`. VOD survives the swap; live cannot.

The same warning fires every 5 minutes from the PO-token validation job — that is expected
noise, not the bug (`[INFO] Successfully validated PO token with video: …` follows it).

---

## 7. Ruled out (do not spend time here)

| Suspect | Why it is not the cause |
|---|---|
| SWAG / nginx vhost | `/watch` = 200, `/api/manifest/dash/id/…` = 302 → companion 200, `/companion/…` proxies fine (`set $upstream_*` form is correct). No `host not found`, no 502, no themed error page. |
| Docker networking / DNS | Same as above: the companion is reached per request; `invidious_network` + SWAG membership intact. |
| Ansible rendering / `INVIDIOUS_CONFIG` | `domain`, `https_only`, `public_url` and `invidious_companion_key` are accepted (the 302 to `/companion/...` and the `check=` verification both succeed). |
| Postgres / `invidious-db` | Container healthy, watch pages and API responses render with full metadata. |
| PO token / bgutils | Token generation and validation succeed continuously (`Successfully validated PO token with video: …` every 5 min, no `[ERROR]` in the logs). |
| Companion auth (`check=` / `secret_key`) | Requests are accepted (400 "ID incorrect." would be returned otherwise). |
| `ip=`-locked googlevideo URLs | The VOD byte-range fetch from the laptop (shared public IP) returns 206 + valid MP4; the failure is identical in shape for streams the browser never even requests. |
| Video.js / browser | VODs play in the same browser build; the exception is caused by the empty MPD (I-03). |
| Disk/CPU/memory on the host | `get_server_health`: load 0.22, 52 GiB available, `/` 32 %, no unhealthy container; playback is a direct stream, nothing is transcoded. |

---

## 8. Upstream status (as of 2026-10-24)

| Ref | State | Note |
|---|---|---|
| `iv-org/invidious-companion#7` — "handle hls for apple devices and hls livestream" | **open** | The actual gap: no live path in the companion |
| `iv-org/invidious-companion#375` — "Live streams fail to generate a valid DASH manifest when adaptiveFormats lack initRange/indexRange" | closed **as duplicate** (2026-09-24) | Its own measurements match I-02/I-05/I-06 exactly (`417 bytes`, `PTNaNS`, `hlsManifestUrl: NO`, `isTypeOtf: false`) |
| `iv-org/invidious` core DASH generator (`src/invidious/routes/api/manifest.cr`) | unchanged | Also skips formats without `indexRange`/`initRange` ("OTF streams aren't supported yet") — dropping the companion would not help |
| `LuanRT/YouTube.js` `StreamingInfo.ts` | unchanged on `main`, incl. **v18.3.0** (2026-10-23) | The filter in I-05 is still there |

Would fixing it locally be possible? Only by not using the upstream binary: patch
`dashManifest.ts`/`StreamingInfo.ts` and build a custom companion image (Deno compile), or add a
manifest shim that synthesises `SegmentTemplate`/`$Number$` addresses for live URLs. Both are
maintained forks of a fast-moving dependency for a feature YouTube changes often — **not
justified** while `#7` is open. Revisit if upstream closes `#7` without shipping, or if the
pain becomes worse than the fork.

---

## 9. Preflight / re-check procedure

Cheap check (no browser, ~2 s) — the whole diagnosis is in the manifest size:

```sh
# live: expect the broken 417-byte empty Period today; a body with <Representation> means fixed
id=$(curl -s 'https://invidious.catafal.co/api/v1/trending?region=IT' \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["videoId"])')
curl -sL "https://invidious.catafal.co/api/manifest/dash/id/$id" | tee /tmp/m.xml | wc -c
# 417 today; count elements, not lines — the whole MPD is a single line
grep -o '<Representation' /tmp/m.xml | wc -l   # 0 = still broken

# VOD baseline (any long-lived VOD works; must stay > 0, a regression here is a *new* bug):
curl -sL "https://invidious.catafal.co/api/manifest/dash/id/xRMPKQweySE" \
  | grep -o '<Representation' | wc -l          # 16 today
```

Real playback proof (what was used here) — headless Chromium + CDP, then sample the
`<video>` element:

```sh
chromium --headless=new --no-sandbox --disable-gpu \
  --autoplay-policy=no-user-gesture-required \
  --remote-debugging-port=9224 --user-data-dir=/tmp/chrome-probe about:blank &
# then, over CDP: Page.navigate, Runtime.evaluate v.play(),
# and read {readyState, currentTime, buffered, error} every 3 s.
```

Pass criteria: `readyState 4` and `currentTime` increasing. Live today: `readyState 0`,
`currentTime 0`, `buffered null`, forever.

Checklist when the Invidious/companion images change (watchtower pulls them):

1. `curl -s https://invidious.catafal.co/api/v1/stats` → note the new version.
2. Run the cheap check above against **a live stream**.
3. If `<Representation>` > 0 → run the browser probe once, then delete this track from
   `docs/issues/README.md` and the note in `AGENTS.md`.
4. If still `<Period/>` → check `iv-org/invidious-companion#7` for status; do not open a new
   local investigation.

---

## 10. Related documents

- `AGENTS.md` — "Invidious (video frontend)" section: the standing invariant and the one-line check.
- `roles/invidious/tasks/main.yml` — companion container + healthcheck (a green healthcheck only
  proves `/api/v1/trending` answers; it has never implied playback works).
- `roles/invidious/templates/invidious.subdomain.conf.j2` — vhost (not involved, see §7).
