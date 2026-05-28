# Containers (Docker, OCI)

- **One process per container.** PID 1 should be your app; not bash, not supervisord, not a sidecar bundled in. Use multi-container pods/compose if you need more than one process working together.
- **PID 1 must handle signals.** `tini` or `dumb-init` as the entrypoint, or your app must explicitly install a SIGTERM handler. Without it, `docker stop` waits the full grace period before SIGKILL — every time.
- **Multi-stage builds.** A `builder` stage with the toolchain, a `runtime` stage with just the artifact. Your production image should not contain `gcc`, npm dev deps, or the test runner.
- **Use a minimal base.** `python:3.12-slim`, `node:20-alpine`, `gcr.io/distroless/...`. `ubuntu:latest` is rarely what you want — 70 MB of base before you've added anything.
- **Pin the base image digest in production.** `python:3.12-slim` floats; `python:3.12-slim@sha256:abc...` doesn't. Floating bases are how supply-chain compromises ship.
- **Don't run as root inside the container.** Add a non-root user in the Dockerfile; `USER appuser`. Even with namespacing, root inside means root if the container escapes.
- **`COPY` the smallest possible set.** `.dockerignore` is mandatory: exclude `.git/`, `node_modules/`, build artifacts, secrets. Otherwise your build context is gigabytes and every change busts the cache.
- **Layer order matters for cache hits.** Cheap, rarely-changing layers first (system deps); expensive layers later (source code). `COPY package.json .` then `RUN npm install` then `COPY . .` — not the reverse.
- **Health checks at the container level too.** `HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1`. Orchestrators use this to decide whether the container is alive; without it they assume "running" = "healthy".
- **Secrets via mount or env, never baked into the image.** A docker image leaked is a permanent leak; secrets baked in are leaked forever. Mount at runtime; rotate when you suspect compromise.
- **`ENTRYPOINT` for the binary, `CMD` for the default args.** Lets users override args without losing the binary. Mixing them in `CMD` makes overrides verbose.
- **Image size discipline.** `docker history` shows what each layer costs. A 1.5 GB image will pull slowly on every node; a 150 MB image pulls in seconds. The difference is usually a few `RUN` cleanups and a multi-stage build.
- **Tag immutably; tag deliberately.** `app:v1.2.3` is forever; `app:latest` lies. Production pulls by digest, not by tag.
