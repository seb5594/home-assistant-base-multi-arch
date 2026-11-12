# Home Assistant Base Images – all architectures

A fork of [home-assistant/docker-base](https://github.com/home-assistant/docker-base) that keeps the
architectures alive which Home Assistant has retired (`armv7`, `armhf` and `i386`) and adds rolling
`edge` images. It is meant as one hybrid source for Alpine, Debian, Ubuntu and Python base images with
S6-Overlay, Bashio and TempIO, ready to pull from GitHub Container Registry.

The images contain the same components and keep the same default behavior as the originals. This is an
unofficial fork. It is not supported by the Open Home Foundation, and the Home Assistant Supervisor does
not run the legacy architectures any more. Use the images for your own containers and add-ons on older hardware.

The images include [S6-Overlay](https://github.com/just-containers/s6-overlay),
[Bashio](https://github.com/hassio-addons/bashio) and [TempIO](https://github.com/home-assistant/tempio).

## What this fork adds

- **Legacy architectures** `armv7`, `armhf` and `i386` next to `amd64` and `aarch64`, wherever the distribution still provides them.
- **Edge images** that follow Alpine `edge`, Debian `testing` and the newest Ubuntu (`devel` or `rolling`).
- **Automatic version pinning**: the newest supported Alpine, Debian and Ubuntu LTS releases and the newest three Python releases are detected and pinned in [`versions.json`](versions.json) every day.
- **Upstream sync**: new Home Assistant component versions, patches and Python releases from the source repository are merged in every day.
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
| Alpine (all releases and edge) | ✅ | ✅ | ✅ | ✅ | ✅ |
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

| Image | OS | Tags | `latest` |
|-------|----|------|----------|
| `base` | Alpine | `3.22`, `3.23`, `3.24`, `edge` | `3.24` |
| `base-debian` | Debian | `bookworm`, `trixie`, `testing` | `trixie` |
| `base-ubuntu` | Ubuntu | `22.04`, `24.04`, `26.04`, `rolling` | `26.04` |
| `base-python` | Alpine | `<python>-alpine<alpine>`, for example `3.14-alpine3.24` | `3.14-alpine3.24` |

The table shows the state at the time of writing. [`versions.json`](versions.json) always has the releases that are currently pinned, including the architectures of each one.

Every release is published with these tags:

| Tag | Meaning |
|-----|---------|
| `3.24` | Newest build of this release |
| `3.24-2026.11.12.57` | A specific build (date and run number, or the release tag for tagged releases) |
| `latest` | The newest stable release |
| `edge` | The rolling release of the Debian and Ubuntu images. Alpine already uses `edge` as its tag |

Python images exist for the newest three Python releases, on every Alpine release including edge (for example `3.15-alpineedge`).
`latest` points to the newest Python release that is at least 90 days old, so a fresh release does not become the default right away.

The per-architecture images (`amd64-base`, `armv7-base-python`, …) are building blocks for the manifests. Use the plain names.

### Edge images

Edge images follow the development branch of the distribution (Alpine `edge`, Debian `testing`, Ubuntu `devel`, or `rolling` while no development release is open).
They are rebuilt every week and can break when the distribution changes under them. A failing edge build does not affect the stable images.

### jemalloc

The Alpine images include jemalloc. To enable it for an application, set `LD_PRELOAD="/usr/local/lib/libjemalloc.so.2"` in your Dockerfile or before you start the application.

## How the automation works

| Workflow | When | What it does |
|----------|------|--------------|
| `update.yml` | daily | Merges the source repository, runs [`scripts/resolve_versions.py`](scripts/resolve_versions.py) to refresh `versions.json`, pushes the result and starts a publishing build when images are affected |
| `builder.yml` | weekly, on release, manually, on push and pull request | Builds all pinned releases on all their architectures. Publishes on schedule, release and when started with `publish` enabled |
| `build-base-image.yml` | called by `builder.yml` | Builds one image for all its architectures and publishes the multi-arch manifest |

Details:

- **Pinning.** Alpine, Debian and Ubuntu releases come from [endoflife.date](https://endoflife.date), the architectures from the Docker official images, Python releases from python.org. Only releases that are in support and already published as Docker images are pinned. Debian and Ubuntu follow the same policy as the original: stable and LTS releases that are still in regular or LTS support, without ELTS and ESM.
- **New Python releases.** When a new Python release appears before the source repository has a Dockerfile for it, one is generated from the newest existing one and marked with `python/<version>/.auto-generated`. It is removed automatically as soon as the source repository ships its own.
- **Pull requests and pushes** only build the stable releases on `amd64`, `aarch64` and `i386`, to give quick feedback. The slow emulated builds and the edge images run on schedule, on release and when started manually.
- **Publishing.** Scheduled builds are tagged `YYYY.MM.DD.<run number>`, releases use their release tag. Images are signed with Cosign, and the Python images verify the signature of their base image before building.
- **Failures.** The ARM variants are best effort: if one of them fails, the remaining architectures are still published and the failed job is visible in the run.

### Setup for your own fork

1. Enable GitHub Actions and run `Build base images` once manually with `publish` enabled. The Python images are built on top of the published base images.
2. Add a repository secret `SYNC_TOKEN` with a personal access token that has the `repo` and `workflow` scopes. The default token cannot push changes to `.github/workflows`, which merging the source repository can involve.
3. In the package settings of the images, link them to the repository and set the visibility you want.

## Staying in sync with the source repository

`update.yml` merges `home-assistant/docker-base` into this fork every day, so new component versions of S6-Overlay, Bashio, TempIO and jemalloc, new patches and new Python releases arrive without manual work.

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
  --build-arg BASE_IMAGE=ghcr.io/seb5594/base \
  --build-arg BASE_VERSION=3.24 \
  -t base-python:3.14-alpine3.24 \
  python/3.14/
```

For another architecture, set the platform. Building for a platform other than the host needs QEMU emulation, see the Docker documentation on [multi-platform builds](https://docs.docker.com/build/building/multi-platform/).

```bash
# 32-bit ARM (armv7), optimizations disabled to keep the build time reasonable under emulation
docker buildx build \
  --platform linux/arm/v7 \
  --build-arg BASE_IMAGE=ghcr.io/seb5594/base \
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
- **Edge-Images** für Alpine `edge`, Debian `testing` und das neueste Ubuntu. Sie werden jede Woche neu gebaut und können brechen, wenn sich die Distribution ändert.
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
