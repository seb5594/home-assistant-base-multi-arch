# Home Assistant Base Images – all architectures

A fork of [home-assistant/docker-base](https://github.com/home-assistant/docker-base) that keeps the
architectures alive which Home Assistant has retired (`armv7`, `armhf` and `i386`) and adds a rolling
`dev` channel. It is meant as one hybrid source for Alpine, Debian, Ubuntu and Python base images with
S6-Overlay, Bashio and TempIO, ready to pull from GitHub Container Registry.

The images contain the same components and keep the same default behavior as the originals. This is an
unofficial fork. It is not supported by the Open Home Foundation, and the Home Assistant Supervisor does
not run the legacy architectures any more. Use the images for your own containers and add-ons on older hardware.

The images include [S6-Overlay](https://github.com/just-containers/s6-overlay),
[Bashio](https://github.com/hassio-addons/bashio) and [TempIO](https://github.com/home-assistant/tempio).

## What this fork adds

- **Legacy architectures** `armv7`, `armhf` and `i386` next to `amd64` and `aarch64`, wherever the distribution still provides them.
- **Two channels**: the stable releases are the default, the experimental `dev` channel follows Alpine `edge`, Debian `testing` and the newest Ubuntu (`devel` or `rolling`).
- **Automatic version pinning**: the newest supported Alpine, Debian and Ubuntu LTS releases and the newest three Python releases are detected and pinned in [`versions.json`](versions.json) every day.
- **Upstream sync**: new stable releases of the source repository are checked daily and merged by tag.
- **Prebuilt packages** on GHCR, rebuilt every week to include operating system security updates.

## Supported architectures

| Architecture | Docker platform | Typical hardware |
|--------------|-----------------|------------------|
| `amd64` | `linux/amd64` | PCs, servers, virtual machines |
| `aarch64` | `linux/arm64` | Raspberry Pi 3/4/5 (64-bit OS), most ARM boards |
| `armv7` | `linux/arm/v7` | Raspberry Pi 2/3 (32-bit OS), many ARM boards |
| `armhf` | `linux/arm/v6` | Raspberry Pi 1 and Zero |
| `i386` | `linux/386` | Old 32-bit x86 machines |

Which architectures an image gets is not hardcoded. It follows what the distribution publishes as an
official Docker image, so a release that loses an architecture upstream loses it here as well.

| Image | amd64 | aarch64 | armv7 | armhf | i386 |
|-------|:-----:|:-------:|:-----:|:-----:|:----:|
| Alpine (all releases and `dev`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Debian `trixie` | ✅ | ✅ | ✅ | ✅ | ✅ |
| Debian `bookworm`, `testing` | ✅ | ✅ | ✅ | – | ✅ |
| Ubuntu (all releases and rolling) | ✅ | ✅ | ✅ | – | – |
| Python | same as the Alpine release it is built on | | | | |

Notes on the 32-bit variants:

- `armhf` is ARMv6 with hardware floating point. Alpine provides a native ARMv6 image. Debian only offers the ARMv5 `armel` port, which runs on ARMv6 hardware and is used for `armhf`.
- Ubuntu has no ARMv6 and no 32-bit x86 images, so only `armv7` is available there.
- The ARM variants are compiled under QEMU emulation. To stay inside the CI time limit, Python for `armv7` and `armhf` is built without profile-guided and link-time optimization, so it runs somewhat slower than the optimized builds. `i386` runs natively on the build machine and keeps the optimizations.

## Images

All images are published to `ghcr.io/seb5594/<image>` as multi-arch manifests, so `docker pull` picks the right architecture automatically.

```bash
docker pull ghcr.io/seb5594/home-assistant-base:3.23
```

| Image | OS | Tags | `latest` |
|-------|----|------|----------|
| `home-assistant-base` | Alpine | `3.22`, `3.23`, `3.24`, `dev` | `3.24` |
| `home-assistant-base-debian` | Debian | `bookworm`, `trixie`, `dev` | `trixie` |
| `home-assistant-base-ubuntu` | Ubuntu | `22.04`, `24.04`, `26.04`, `dev` | `26.04` |
| `home-assistant-base-python` | Alpine | `<python>-alpine<alpine>`, for example `3.14-alpine3.24` | `3.14-alpine3.24` |

The table shows the state at the time of writing. [`versions.json`](versions.json) always has the releases that are currently pinned, including the architectures of each one.

Every release is published with these tags:

| Tag | Meaning |
|-----|---------|
| `3.24` | Newest build of this release |
| `3.24-2026.11.0` | Alpine 3.24 image for the upstream docker-base release `2026.11.0` |
| `latest` | The newest stable release |
| `dev` | The experimental channel. Release builds also get a tag such as `dev-2026.11.0` |

Python images exist for the newest three Python releases on every stable Alpine release (for example `3.15-alpine3.24`). The `dev` channel combines only the newest Python release with Alpine edge (for example `3.15-dev`).
`latest` points to the newest Python release that is at least 90 days old, so a fresh release does not become the default right away.

Each tag points to one multi-architecture manifest. The platform builds are stored by digest in the same package.

### Channels

The stable releases are the default. Use the numbered or named tags (`3.24`, `trixie`, `24.04`, `3.14-alpine3.24`) for anything that should keep working.

The `dev` channel is experimental. It is built from the development branch of each distribution:

| Image | `dev` is built from |
|-------|---------------------|
| `home-assistant-base` | Alpine `edge` |
| `home-assistant-base-debian` | Debian `testing` |
| `home-assistant-base-ubuntu` | Ubuntu `devel`, or `rolling` while no development release is open |
| `home-assistant-base-python` | the newest Python release on Alpine `edge` |

The `dev` images are rebuilt every week and can break when the distribution changes under them. A failing `dev` build does not affect the stable images.

### jemalloc

The Alpine images include jemalloc. To enable it for an application, set `LD_PRELOAD="/usr/local/lib/libjemalloc.so.2"` in your Dockerfile or before you start the application.

## How the automation works

| Workflow | When | What it does |
|----------|------|--------------|
| `update.yml` | daily | Checks for the next stable release of `home-assistant/docker-base`, merges its tagged source, refreshes `versions.json` and starts publication from the matching fork tag |
| `builder.yml` | weekly, on release, manually, on push and pull request | Builds all pinned releases on all their architectures. Publishes on schedule, release and when started with `publish` enabled |
| `build-base-image.yml` | called by `builder.yml` | Builds one image for all its architectures and publishes the multi-arch manifest |

Details:

- **Pinning.** Alpine, Debian and Ubuntu releases come from [endoflife.date](https://endoflife.date), the architectures from the Docker official images, Python releases from python.org. Only releases that are in support and already published as Docker images are pinned. Debian and Ubuntu follow the same policy as the original: stable and LTS releases that are still in regular or LTS support, without ELTS and ESM.
- **New Python releases.** When a new Python release appears before the source repository has a Dockerfile for it, one is generated from the newest existing one and marked with `python/<version>/.auto-generated`. It is removed automatically as soon as the source repository ships its own.
- **Pull requests and pushes** only build the stable releases on `amd64`, `aarch64` and `i386`, to give quick feedback. The slow emulated builds and the `dev` images run on schedule, on release and when started manually.
- **Python builds.** Runs with publishing disabled build Python on the Alpine Dockerfile from the same checkout. Publishing runs verify the provenance of the Alpine manifest created by that run and build Python against its digest.
- **Publishing.** Stable upstream releases get the same GitHub release tag in the fork and the full upstream version as a suffix on GHCR, for example `3.23-2026.11.0`. The fork release is published after the images succeed. Weekly and regular manual runs refresh the moving aliases. Signed provenance is stored in GitHub Actions and can be checked with `gh attestation verify oci://ghcr.io/seb5594/home-assistant-base:3.23-2026.11.0 --repo seb5594/home-assistant-base-multi-arch`.
- **Registry cleanup.** Release builds remove obsolete monthly or daily tags once their release-tagged counterparts exist. The cleanup also handles retired Python dev builds, old Cosign sidecars and superseded packages.
- **Failures.** The ARM variants are best effort: if one of them fails, the remaining architectures are still published and the failed job is visible in the run.

### Setup for your own fork

1. Enable GitHub Actions and run `Sync upstream and update pins` to start the first release build.
2. Add a repository secret `SYNC_TOKEN` with a personal access token that has the `repo` and `workflow` scopes. The default token cannot push changes to `.github/workflows`, which merging the source repository can involve.
3. In the package settings of the images, link them to the repository and set the visibility you want.

## Staying in sync with the source repository

`update.yml` checks the stable releases of `home-assistant/docker-base` every day. It merges the selected release tag into this fork so new component versions, patches and Python Dockerfiles ship with the matching upstream version.

To keep merges conflict free, the fork changes the upstream files as little as possible. Only the architecture handling of the Dockerfiles and the Python optimization flag differ. The workflows `builder.yml` and `build-base-image.yml` and this README are owned by the fork, so changes to them upstream are not merged. If a merge does conflict anywhere else, nothing is pushed and an issue is opened.

## Building images locally

Docker BuildKit (`docker buildx`) can be used for building the images locally without any extra tooling.

Alpine base using the default version from the Dockerfile:

```bash
docker buildx build -t base alpine/
```

To use a specific Alpine base version:

```bash
docker buildx build \
  --build-arg ALPINE_VERSION=3.23 \
  -t base:3.23 \
  alpine/
```

Debian base:

```bash
docker buildx build \
  --build-arg DEBIAN_VERSION=trixie \
  -t base-debian:trixie \
  debian/
```

Ubuntu base:

```bash
docker buildx build \
  --build-arg UBUNTU_VERSION=26.04 \
  -t base-ubuntu:26.04 \
  ubuntu/
```

Python 3.14 image, using the Alpine 3.24 base image from GHCR:

```bash
docker buildx build \
  --build-arg BASE_IMAGE=ghcr.io/seb5594/home-assistant-base \
  --build-arg BASE_VERSION=3.24 \
  -t base-python:3.14-alpine3.24 \
  python/3.14/
```

For another architecture, set the platform. Building for a platform other than the host needs QEMU emulation, see the Docker documentation on [multi-platform builds](https://docs.docker.com/build/building/multi-platform/).

```bash
# 32-bit ARM (armv7), optimizations disabled to keep the build time reasonable under emulation
docker buildx build \
  --platform linux/arm/v7 \
  --build-arg BASE_IMAGE=ghcr.io/seb5594/home-assistant-base \
  --build-arg BASE_VERSION=3.24 \
  --build-arg PYTHON_OPTIMIZATIONS= \
  -t base-python:3.14-alpine3.24-armv7 \
  python/3.14/
```

The platforms to use are `linux/amd64`, `linux/arm64`, `linux/arm/v7`, `linux/arm/v6` (armhf) and `linux/386` (i386).

## Deutsch

Dieses Repository ist ein Fork von [home-assistant/docker-base](https://github.com/home-assistant/docker-base). Es bietet die Home-Assistant-Basis-Images (Alpine, Debian, Ubuntu, Python) weiterhin für die Architekturen an, die Home Assistant aufgegeben hat: `armv7`, `armhf` und `i386`. Dazu kommen `amd64` und `aarch64`. Die fertigen Images liegen auf `ghcr.io/seb5594/<image>` und sind Multi-Arch-Manifeste, Docker wählt die passende Architektur selbst.

Was dieser Fork ergänzt:

- **Legacy-Architekturen**, überall dort, wo die Distribution sie noch liefert. Ubuntu bietet nur `armv7`, Debian `bookworm` und `testing` haben kein `armhf`.
- **Zwei Kanäle**: Standard sind die stabilen Releases. Der experimentelle Kanal `dev` basiert auf Alpine `edge`, Debian `testing` und dem neuesten Ubuntu. Er wird jede Woche neu gebaut und kann brechen, wenn sich die Distribution ändert. Auf Alpine `edge` läuft jeweils nur die neueste Python-Version, zum Beispiel `3.15-dev`.
- **Release-Tags**: Neue stabile Releases von `home-assistant/docker-base` werden täglich erkannt und mit exakt derselben Version veröffentlicht. Der passende GHCR-Tag lautet zum Beispiel `3.23-2026.11.0`.
- **Automatisches Pinning** der neuesten unterstützten Alpine-, Debian- und Ubuntu-LTS-Releases sowie der drei neuesten Python-Versionen in [`versions.json`](versions.json), täglich geprüft.
- **Abgleich mit dem Quell-Repository**: Neue Komponentenversionen, Patches und Python-Versionen aus `home-assistant/docker-base` werden täglich eingespielt. Eigene Änderungen an den übernommenen Dateien sind bewusst minimal gehalten. Bei einem Konflikt wird nichts gepusht, stattdessen wird ein Issue angelegt.
- **Wöchentlich neu gebaute Images**, damit Sicherheitsupdates des Betriebssystems enthalten sind.

Hinweise:

- `armhf` ist ARMv6 mit Hardware-Fließkomma (Raspberry Pi 1 und Zero). Bei Debian wird dafür das ARMv5-Image (`armel`) verwendet, das auf ARMv6-Hardware läuft.
- Die ARM-Varianten werden unter QEMU gebaut. Python für `armv7` und `armhf` entsteht deshalb ohne PGO und LTO und läuft etwas langsamer als die optimierten Builds.
- Schlägt ein ARM-Build fehl, werden die übrigen Architekturen trotzdem veröffentlicht.
- Einrichtung im eigenen Fork: `Build base images` einmal manuell mit aktivierter Option `publish` starten und ein Repository-Secret `SYNC_TOKEN` (Personal Access Token mit `repo` und `workflow`) anlegen, damit der tägliche Abgleich auch Workflow-Dateien pushen darf.

Dieser Fork ist inoffiziell. Der Home Assistant Supervisor unterstützt die Legacy-Architekturen nicht mehr, die Images eignen sich für eigene Container und Add-ons auf älterer Hardware.

## License

Licensed under the Apache License 2.0, see [LICENSE](LICENSE). The base images originate from the
[Home Assistant](https://www.home-assistant.io) project of the Open Home Foundation.
