# Backend Hosting Research (Workstream P)

**Scope.** This is research only — no code, `docker-compose.yml`, or deploy config was changed. It answers: where should the Python backend stack (FastAPI `app`, Playwright `scraper`, and the new APScheduler `scheduler` service) run, given the frontend (React/Vite) deploys separately to Netlify and can't host a persistent process.

## What the workload actually needs

Read from the repo as it stands today (`docker-compose.yml`, `app/Dockerfile`, `scraper/Dockerfile`):

- **Three long-running containers**, not one: `app` (FastAPI/uvicorn), `scraper` (Playwright), and `scheduler` (APScheduler — new per workstream K, not yet in `docker-compose.yml`). They share `./data` and `./input` volumes and a common `.env`.
- **Real Chromium, not a lightweight process.** `scraper/Dockerfile` runs `playwright install chromium` *and* `playwright install-deps chromium` — a full browser binary plus its OS-level shared libraries (fonts, graphics, NSS, etc.). This is materially heavier than a typical Python web container and is exactly the kind of thing that silently breaks on platforms that assume "container = small stateless process."
- **A persistent background process for the scheduler**, not request-triggered serverless. APScheduler needs to stay resident in memory and fire cron-style jobs (daily discovery, daily digest) at specific hours whether or not any HTTP request has come in. Anything that sleeps the process when idle, or that's architected around "spin up on a request, shut down after," breaks this.
- **Low traffic, single/few users.** This is not a scaling problem; it's a "keep three small containers alive reliably and cheaply" problem.
- **EU/Germany data residency preference.** The project has an EU/DE job-market focus, and personal data (resumes, generated cover letters) will live on this backend (destined for S3, but transiting and partly cached on the backend). EU-region hosting is a genuine "nice to have," not a hard compliance requirement at this scale (no stated GDPR/legal obligation exists for a personal project), but it matches the project's stated preferences.
- **Cost-consciousness.** Every decision so far in this project (Gemini Flash over a bigger model, JSON files before SQLite, free ATS APIs before paid ones) has favored free/cheap. The hosting answer should too.

## Option 1: Small VPS (Hetzner / DigitalOcean / OVH)

**What it is:** a bare virtual machine you SSH into and run `docker compose up -d` on directly — your existing `docker-compose.yml` works almost unmodified (just add the `scheduler` service per workstream K).

**Cost at this scale** (as of late 2026 pricing):
- **Hetzner Cloud** — CPX11-class shared vCPU box (2 vCPU / 2GB or similar) runs roughly **€5–8/month**; note Hetzner raised prices twice in 2026 (April and June), so the former €4.somthing entry tier is gone — budget closer to €6–8/month for a box with enough RAM to run three containers including Chromium comfortably (2GB+ RAM recommended, 4GB safer). Generous bundled traffic (20TB+).
- **DigitalOcean** — Basic Droplet from **$4–6/month** for 512MB–1GB RAM, but Chromium + FastAPI + APScheduler together realistically need the **$12/month (2GB RAM) tier** to avoid OOM kills.
- **OVH** — VPS-1 from roughly **€4–7/month**, similar sizing considerations as DO.
- **Realistic monthly total for this project: ~€6–12/month** for a single box big enough for all three services.

**Playwright/Chromium support:** Yes, genuinely — it's just Linux. `playwright install-deps chromium` installs normal apt packages on a normal Debian/Ubuntu kernel; there's no container sandbox or restricted syscall environment to fight. This is the same environment the scraper was developed and tested against.

**Persistent background scheduler:** Yes, natively. A VPS has no concept of "idle" — `docker compose up -d` keeps all three containers running indefinitely, APScheduler fires at its cron times regardless of request traffic. This is the one environment where "long-running background process" isn't a special case to design around.

**docker-compose fit:** This is the best-fit option by a wide margin — the existing `docker-compose.yml` is *already* the deployment artifact. No translation layer, no rewriting into a platform-specific manifest. Add the `scheduler` service, maybe put a Caddy/nginx reverse proxy in front for TLS, and it's done.

**EU region:** Yes, trivially — Hetzner (Nuremberg/Falkenstein, Germany; Helsinki), DigitalOcean (Amsterdam, Frankfurt), and OVH (France, Germany, Poland) all have EU data centers to choose from explicitly at signup.

**The real cost of this option isn't money, it's operational burden:** you own OS patching, Docker engine updates, firewall rules, TLS certificate renewal, container restarts after a crash or VM reboot (needs `restart: unless-stopped` policies and ideally a `systemd` unit or watchdog), and monitoring/alerting if something dies silently (e.g., the scheduler process crashes and nobody notices for three days). None of this is hard, but it is all on you, with no managed safety net.

## Option 2: PaaS (Render / Railway / Fly.io)

**What it is:** managed container hosting — push code or an image, the platform builds/runs/restarts it, typically with its own manifest format rather than raw `docker-compose.yml`.

### Render
- **Cost:** Background Workers (the service type that fits the scheduler) start at **$7/month** for the cheapest paid tier; a web service is another **$7/month**; a third worker-type service for the scraper would be a third **$7/month** line. Realistic total for three always-on services: **~$21+/month**, more than double the VPS option. Render's free tier exists but free *web services* spin down on idle (fine for nothing here, since the FastAPI app needs to be reachable) and free tier has no background-worker equivalent that stays resident — so a genuinely-free Render setup for this workload isn't viable.
- **docker-compose support:** **No native support**, confirmed via Render's own feature-request tracker, open for years with no commitment to ship it. You'd hand-translate `docker-compose.yml` into a `render.yaml` blueprint (doable, each service becomes a separate `type: web`/`type: worker` block, but it's a real rewrite, not a drop-in).
- **Playwright/Chromium:** Supported — Render publishes/accepts Playwright-based Docker images (Chromium + deps pre-installed) and this is a documented, common pattern on the platform. Genuinely fine, not a free-tier trap here.
- **Persistent scheduler:** Render's **Background Worker** service type is explicitly designed for this (long-running process, no request-response assumption) — this is the one PaaS service type built for exactly our scheduler's shape.
- **EU region:** Only **one** EU region (Frankfurt). Fine for this project's single EU focus, but worth knowing if Render is ever a long-term bet — no region choice within the EU.

### Railway
- **Cost:** Usage-based billing on top of a plan minimum (Hobby $5/mo credit, Pro $20/mo credit) — a single always-on 0.25vCPU worker alone runs **~$30/month** in pure compute once you exceed the bundled credit, and three services (app + scraper + scheduler) would burn through the Hobby tier's credit fast. Realistic total: **likely $20–40+/month**, the most expensive and least predictable of the three PaaS options for this workload.
- **docker-compose support:** Weak — compose files can be dragged into Railway's canvas but "may not work completely as intended"; Railway's own guidance is to port services over individually rather than relying on compose compatibility.
- **Playwright/Chromium:** Works via a custom Dockerfile (confirmed real-world deployments exist), so no fundamental blocker.
- **Persistent scheduler — the actual trap:** Railway's **free/Hobby tier defaults to a "serverless" sleep mode** that puts services to sleep after ~10 minutes of no *inbound HTTP traffic*. A background worker with no HTTP endpoint (which is exactly what an APScheduler process is) can get swept into this unless you explicitly configure it as always-on (costs more, undoing the free-tier appeal). This is precisely the "request-driven assumption breaks a cron-style background service" failure mode flagged as a risk going into this research — confirmed real on Railway.
- **EU region:** Available (Railway has EU regions), but combined with cost and sleep-mode risk, this is the weakest of the three PaaS options for this specific workload.

### Fly.io
- **Cost:** Cheapest PaaS option — a `shared-cpu-1x` 256MB machine runs **~$2.19/month**, a 1GB machine in Frankfurt **~$7.73/month**. Three small machines (app, scraper, scheduler) sized modestly could realistically land around **$10–20/month** — competitive with, though still generally above, the VPS option.
- **docker-compose support:** Partial and newer (added 2026) — `fly.toml` gained a `[build.compose]` section that auto-detects `docker-compose.yml` and runs its services as containers within a Fly Machine. This is the closest any PaaS gets to "just point it at your existing compose file." The caveat: **only one service in the compose file can specify a `build`** — since both `app` and `scraper` (and the future `scheduler`) each build from their own Dockerfile, this repo's actual compose file would hit that limitation and need at least one service's image pre-built and pushed separately, or restructured into Fly's `processes` block instead. Not a clean drop-in, but closer than Render/Railway.
- **Playwright/Chromium:** Works, with the usual Docker Chromium flags (`--disable-dev-shm-usage` etc.) needed — same category of fix as on a VPS, nothing Fly-specific blocks it.
- **Persistent scheduler:** Fly Machines can be configured to stay running continuously (no forced sleep-on-idle for a machine not marked auto-stop), so a true always-on background worker is supported — this is **not** a request-driven-only platform.
- **EU region:** Yes — Frankfurt (`fra`) is a first-class region choice.

## Side-by-side

| | VPS (Hetzner/DO/OVH) | Render | Railway | Fly.io |
|---|---|---|---|---|
| Realistic monthly cost (3 services) | **~€6–12** | ~$21+ | ~$20–40+ | ~$10–20 |
| Real Chromium support | Yes (it's just Linux) | Yes (documented pattern) | Yes (custom Dockerfile) | Yes (needs Docker flags) |
| True always-on background scheduler | Yes, trivially | Yes (Background Worker type built for this) | **Risk**: free/Hobby tier sleeps non-HTTP workers | Yes (machines don't force-sleep) |
| Existing docker-compose.yml reusable | **Yes, as-is** | No — rewrite to render.yaml | No — weak/unofficial support | Partial — new `[build.compose]`, hits multi-build limitation |
| EU region choice | Yes, multiple countries | Only Frankfurt | Yes | Yes, Frankfurt |
| Who manages OS/patching/restarts | You | Platform | Platform | Platform |

## Recommendation

**Pick the small VPS — Hetzner, in an EU region (Nuremberg/Falkenstein or Helsinki).**

Reasoning: this project's three real constraints — real Chromium, a genuinely persistent (not request-triggered) background scheduler, and cost-consciousness — are exactly the three places where PaaS free/cheap tiers are most likely to disappoint. Railway's sleep-on-idle behavior is a confirmed, documented risk for a non-HTTP background worker like the scheduler — the one failure mode this research was specifically asked to check for. Render avoids that trap (its Background Worker type is built for this) but costs 2-3x the VPS at this project's scale and requires hand-translating `docker-compose.yml` into `render.yaml`. Fly.io is the closest PaaS competitor — cheap, EU region available, real always-on machines — but its new compose support still trips on this repo's exact shape (multiple services each with their own `build:`), so it isn't the clean drop-in it first appears to be.

A VPS running the existing `docker-compose.yml` almost unmodified is the only option where the deployment artifact you already have *is* the deployment — add the `scheduler` service, `docker compose up -d`, done. Hetzner specifically because its EU pricing (even after 2026's increases) is still the cheapest of the three VPS providers for a box with enough RAM to run Chromium, FastAPI, and APScheduler together comfortably (recommend a 2-4GB RAM tier, ~€6-10/month), and it has multiple EU-country data centers to choose from.

**The tradeoff being made, explicitly:** this choice trades managed convenience for cost and portability. There is no platform auto-restarting a crashed container, no managed TLS, no one-click rollback, no automatic zero-downtime deploys — all of that has to be set up by hand (a `restart: unless-stopped` policy, a reverse proxy with Let's Encrypt, maybe a simple healthcheck/alerting script) and kept working by hand going forward. For a single/few-user personal project where the owner is comfortable with Docker and SSH and has already prioritized cheap tooling throughout, that tradeoff is the right one. If the project later grows multiple real users, needs zero-downtime deploys, or the owner's time becomes worth more than the ~$15/month difference, Fly.io is the natural next option to revisit — it's the PaaS that fights this workload's shape (Chromium + always-on worker) the least.
