#!/usr/bin/env python3
"""Pin the release lines that this fork builds into versions.json.

The script answers two questions for Alpine, Debian, Ubuntu and Python:

* Which releases are currently supported (and which one is "latest")?
* For which CPU architectures does the upstream Docker image exist?

Lifecycle data comes from endoflife.date, architecture data from the Docker
official-images library and Python releases from python.org. Only the Python
standard library is used so the script runs on a plain GitHub runner.

Python releases that upstream has not added yet get a Dockerfile of their own,
copied from the newest existing one and marked with an ``.auto-generated`` file.
The sync workflow drops such a directory as soon as upstream ships the release.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSIONS_FILE = REPO_ROOT / "versions.json"
PYTHON_DIR = REPO_ROOT / "python"
GENERATED_MARKER = ".auto-generated"

ENDOFLIFE_URL = "https://endoflife.date/api/{product}.json"
DOCKER_LIBRARY_URL = (
    "https://raw.githubusercontent.com/docker-library/official-images/master/library/{image}"
)
PYTHON_FTP_URL = "https://www.python.org/ftp/python/"

# Same policy as the original repository: the newest three Python releases.
PYTHON_RELEASES_KEPT = 3
# A new Python release only becomes "latest" once it had time to settle.
PYTHON_LATEST_MIN_AGE_DAYS = 90

# Our architecture names, in the order they are published.
ARCHITECTURES = ["amd64", "aarch64", "armv7", "armhf", "i386"]

# Docker library architecture -> our architecture name.
# Alpine ships a real ARMv6 image, Debian only has the ARMv5 "armel" port, which
# runs on ARMv6 hardware and therefore serves as the armhf variant.
DOCKER_ARCHITECTURES = {
    "alpine": {
        "amd64": "amd64",
        "arm64v8": "aarch64",
        "arm32v7": "armv7",
        "arm32v6": "armhf",
        "i386": "i386",
    },
    "debian": {
        "amd64": "amd64",
        "arm64v8": "aarch64",
        "arm32v7": "armv7",
        "arm32v5": "armhf",
        "i386": "i386",
    },
    "ubuntu": {
        "amd64": "amd64",
        "arm64v8": "aarch64",
        "arm32v7": "armv7",
    },
}


class ResolveError(RuntimeError):
    """Raised when upstream data does not look the way we expect."""


@dataclass(frozen=True)
class LibraryEntry:
    """One stanza of a Docker official-images library file."""

    tags: tuple[str, ...]
    architectures: tuple[str, ...]


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #


def _request(url: str, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(
        url, method=method, headers={"User-Agent": "base-image-version-resolver"}
    )


def fetch_text(url: str, attempts: int = 3) -> str:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(_request(url), timeout=30) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def fetch_json(url: str):
    return json.loads(fetch_text(url))


def url_exists(url: str) -> bool:
    try:
        with urllib.request.urlopen(_request(url, "HEAD"), timeout=30):
            return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def parse_library(text: str) -> list[LibraryEntry]:
    """Parse a Docker official-images library file into its tag/arch stanzas."""
    entries = []
    for block in re.split(r"\n\s*\n", text):
        fields = {}
        for line in block.splitlines():
            if line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
        if "Tags" not in fields:
            continue
        entries.append(
            LibraryEntry(
                tags=tuple(tag.strip() for tag in fields["Tags"].split(",")),
                architectures=tuple(
                    arch.strip() for arch in fields.get("Architectures", "").split(",") if arch.strip()
                ),
            )
        )
    return entries


def find_entry(entries: list[LibraryEntry], tag: str) -> LibraryEntry | None:
    return next((entry for entry in entries if tag in entry.tags), None)


def map_architectures(distro: str, docker_architectures) -> list[str]:
    mapping = DOCKER_ARCHITECTURES[distro]
    found = {mapping[arch] for arch in docker_architectures if arch in mapping}
    return [arch for arch in ARCHITECTURES if arch in found]


def is_supported(cycle: dict, today: dt.date) -> bool:
    """A cycle counts when it has been released and its end of life is still ahead."""
    if dt.date.fromisoformat(cycle["releaseDate"]) > today:
        return False
    eol = cycle.get("eol")
    if isinstance(eol, bool):
        return not eol
    return dt.date.fromisoformat(eol) > today


def release_line(version: str, architectures: list[str], latest: bool, edge: bool) -> dict:
    return {
        "version": version,
        "architectures": architectures,
        "latest": latest,
        "edge": edge,
    }


def build_lines(
    distro: str,
    stable: list[tuple[str, str]],
    library: list[LibraryEntry],
    edge: tuple[str, str] | None,
) -> list[dict]:
    """Turn (version, library tag) pairs into release lines.

    ``stable`` must be sorted newest first. Releases whose image is not on the
    Docker library yet are skipped, they are picked up by a later run.
    """
    lines = []
    for version, tag in stable:
        entry = find_entry(library, tag)
        if entry is None:
            print(f"warning: no {distro} image for {tag} yet, skipping", file=sys.stderr)
            continue
        lines.append(
            release_line(version, map_architectures(distro, entry.architectures), not lines, False)
        )
    if not lines:
        raise ResolveError(f"no supported {distro} release found")
    lines.reverse()  # oldest first, like the original build matrices

    if edge is not None:
        version, tag = edge
        entry = find_entry(library, tag)
        if entry is not None:
            lines.append(release_line(version, map_architectures(distro, entry.architectures), False, True))
    return lines


# --------------------------------------------------------------------------- #
# Distributions
# --------------------------------------------------------------------------- #


def resolve_alpine(cycles: list[dict], library: list[LibraryEntry], today: dt.date) -> list[dict]:
    supported = sorted(
        (cycle for cycle in cycles if is_supported(cycle, today)),
        key=lambda cycle: version_key(cycle["cycle"]),
        reverse=True,
    )
    stable = [(cycle["cycle"], cycle["cycle"]) for cycle in supported]
    return build_lines("alpine", stable, library, edge=("edge", "edge"))


def resolve_debian(cycles: list[dict], library: list[LibraryEntry], today: dt.date) -> list[dict]:
    supported = sorted(
        (cycle for cycle in cycles if is_supported(cycle, today)),
        key=lambda cycle: version_key(cycle["cycle"]),
        reverse=True,
    )
    # The images are built from the -slim variants, named after the release codename.
    stable = [
        (cycle["codename"].lower(), f"{cycle['codename'].lower()}-slim") for cycle in supported
    ]
    return build_lines("debian", stable, library, edge=("testing", "testing-slim"))


def resolve_ubuntu(cycles: list[dict], library: list[LibraryEntry], today: dt.date) -> list[dict]:
    # Only LTS releases that are still in standard support, no ESM / Ubuntu Pro.
    supported = sorted(
        (cycle for cycle in cycles if cycle.get("lts") and is_supported(cycle, today)),
        key=lambda cycle: version_key(cycle["cycle"]),
        reverse=True,
    )
    stable = [(cycle["cycle"], cycle["cycle"]) for cycle in supported]
    # "devel" only exists while a development cycle is open, "rolling" is the newest release.
    edge_tag = "devel" if find_entry(library, "devel") else "rolling"
    return build_lines("ubuntu", stable, library, edge=(edge_tag, edge_tag))


# --------------------------------------------------------------------------- #
# Python
# --------------------------------------------------------------------------- #


def python_versions_from_index(index_html: str) -> dict[str, list[str]]:
    """Map every minor release to its patch directories of the python.org FTP index, newest first."""
    patches: dict[str, list[str]] = {}
    for version in re.findall(r'href="(3\.\d+\.\d+)/"', index_html):
        minor = ".".join(version.split(".")[:2])
        patches.setdefault(minor, []).append(version)
    return {
        minor: sorted(versions, key=version_key, reverse=True) for minor, versions in patches.items()
    }


def select_python_releases(
    index_html: str, is_final_release, kept: int = PYTHON_RELEASES_KEPT
) -> dict[str, str]:
    """Return {minor: newest final patch release} for the newest ``kept`` minors.

    Pre-releases live in the directory of their final version, so a directory is
    only trusted once ``is_final_release(version)`` confirms the final tarball.
    """
    selected: dict[str, str] = {}
    by_minor = python_versions_from_index(index_html)
    for minor in sorted(by_minor, key=version_key, reverse=True):
        patch = next((v for v in by_minor[minor][:3] if is_final_release(v)), None)
        if patch is not None:
            selected[minor] = patch
        if len(selected) == kept:
            break
    if not selected:
        raise ResolveError("no final Python release found on python.org")
    return selected


def python_is_final_release(version: str) -> bool:
    base = f"{PYTHON_FTP_URL}{version}/Python-{version}.tar.xz"
    return url_exists(base) and url_exists(f"{base}.sigstore")


def resolve_python(
    patches: dict[str, str], cycles: list[dict], today: dt.date
) -> list[dict]:
    """Build the Python release lines, the latest one is the newest that is old enough."""
    release_dates = {cycle["cycle"]: dt.date.fromisoformat(cycle["releaseDate"]) for cycle in cycles}
    minors = sorted(patches, key=version_key)
    cutoff = today - dt.timedelta(days=PYTHON_LATEST_MIN_AGE_DAYS)
    settled = [m for m in minors if m in release_dates and release_dates[m] <= cutoff]
    latest = settled[-1] if settled else minors[0]
    return [{"version": minor, "latest": minor == latest} for minor in minors]


# --------------------------------------------------------------------------- #
# Python Dockerfiles that upstream does not ship yet
# --------------------------------------------------------------------------- #

PYTHON_VERSION_ARG = re.compile(r"^(ARG PYTHON_VERSION=)\S+$", re.MULTILINE)


def sync_generated_python_dirs(patches: dict[str, str], python_dir: Path = PYTHON_DIR) -> list[str]:
    """Create missing Python directories and keep generated ones on the newest patch release."""
    existing = {
        path.name: path
        for path in python_dir.iterdir()
        if (path / "Dockerfile").is_file() and re.fullmatch(r"3\.\d+", path.name)
    }
    if not existing:
        raise ResolveError(f"no Python Dockerfile found in {python_dir}")
    template = existing[max(existing, key=version_key)]
    touched = []

    for minor, patch in sorted(patches.items(), key=lambda item: version_key(item[0])):
        target = existing.get(minor)
        created = target is None
        if created:
            target = python_dir / minor
            shutil.copytree(template, target)
            (target / GENERATED_MARKER).write_text(
                "This directory was generated from the newest Python Dockerfile because\n"
                "upstream does not ship this release yet. It is removed automatically once\n"
                f"upstream adds python/{minor}. Check the signing identity and patches if the\n"
                "build fails.\n"
            )
        elif not (target / GENERATED_MARKER).exists():
            continue  # owned by upstream, it follows its own version pins

        dockerfile = target / "Dockerfile"
        content = dockerfile.read_text()
        updated = PYTHON_VERSION_ARG.sub(rf"\g<1>{patch}", content)
        if created or updated != content:
            dockerfile.write_text(updated)
            touched.append(minor)
    return touched


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def resolve_all(today: dt.date) -> tuple[dict, dict[str, str]]:
    library = {
        distro: parse_library(fetch_text(DOCKER_LIBRARY_URL.format(image=distro)))
        for distro in ("alpine", "debian", "ubuntu")
    }
    patches = select_python_releases(fetch_text(PYTHON_FTP_URL), python_is_final_release)
    python_cycles = fetch_json(ENDOFLIFE_URL.format(product="python"))

    document = {
        "alpine": resolve_alpine(fetch_json(ENDOFLIFE_URL.format(product="alpine")), library["alpine"], today),
        "debian": resolve_debian(fetch_json(ENDOFLIFE_URL.format(product="debian")), library["debian"], today),
        "ubuntu": resolve_ubuntu(fetch_json(ENDOFLIFE_URL.format(product="ubuntu")), library["ubuntu"], today),
        "python": resolve_python(patches, python_cycles, today),
    }
    return document, patches


def write_if_changed(path: Path, document: dict) -> bool:
    rendered = json.dumps(document, indent=2) + "\n"
    if path.exists() and path.read_text() == rendered:
        return False
    path.write_text(rendered)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write anything, exit with 1 if versions.json is out of date",
    )
    args = parser.parse_args(argv)

    today = dt.datetime.now(dt.timezone.utc).date()
    document, patches = resolve_all(today)

    if args.check:
        current = json.loads(VERSIONS_FILE.read_text()) if VERSIONS_FILE.exists() else None
        if current != document:
            print("versions.json is out of date")
            return 1
        return 0

    if write_if_changed(VERSIONS_FILE, document):
        print("updated versions.json")
    for minor in sync_generated_python_dirs(patches):
        print(f"updated python/{minor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
