"""Remove the superseded versions from the base image packages."""

import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DAILY_TAG = re.compile(r"(.+-\d{4}\.\d{2})\.\d{2}\.\d+")
MONTHLY_TAG = re.compile(r".+-\d{4}\.\d{2}")
PYTHON_DEV_TAG = re.compile(r"(\d+\.\d+)-dev(?:-\d{4}\.\d{2}(?:\.\d+){0,2})?")
COSIGN_TAG = re.compile(r"sha256-([a-f0-9]{64})(?:\.(sig|att))?")
SIGSTORE_BUNDLE = "application/vnd.dev.sigstore.bundle.v0.3+json"
PLATFORMS = {
    "amd64": ("amd64", ""),
    "aarch64": ("arm64", ""),
    "armv7": ("arm", "v7"),
    "armhf": ("arm", "v6"),
    "i386": ("386", ""),
}


def package_architectures(versions):
    families = {
        "base": versions["alpine"],
        "base-debian": versions["debian"],
        "base-ubuntu": versions["ubuntu"],
        "base-python": versions["alpine"],
    }
    for name, releases in families.items():
        arches = {arch for release in releases for arch in release["architectures"]}
        yield name, sorted(arches)


def version_key(version):
    return tuple(map(int, version.split(".")))


def obsolete_tag(tag, existing_tags, is_python, newest_python, release):
    """Keep aliases and legacy tags without a matching upstream release image."""
    dev = PYTHON_DEV_TAG.fullmatch(tag) if is_python else None
    if dev and version_key(dev[1]) < version_key(newest_python):
        return f"{newest_python}-dev-{release}" in existing_tags
    daily = DAILY_TAG.fullmatch(tag)
    month_tag = daily[1] if daily else tag
    month = release.rsplit(".", 1)[0]
    if not MONTHLY_TAG.fullmatch(month_tag) or not month_tag.endswith(f"-{month}"):
        return False
    replacement = f"{month_tag.rsplit('-', 1)[0]}-{release}"
    return replacement in existing_tags


def inspect(reference):
    output = subprocess.check_output(
        ["docker", "buildx", "imagetools", "inspect", "--raw", reference], text=True
    )
    return json.loads(output)


def cosign_sidecar(repository, tag, read_manifest=inspect):
    """Return the bundle digests for a verified Cosign sidecar, or None."""
    match = COSIGN_TAG.fullmatch(tag)
    if not match:
        return None
    manifest = read_manifest(f"{repository}:{tag}")
    if match[2]:
        layer_type = {
            "sig": "application/vnd.dev.cosign.simplesigning.v1+json",
            "att": "application/vnd.dsse.envelope.v1+json",
        }[match[2]]
        layers = manifest.get("layers", [])
        if layers and all(layer.get("mediaType") == layer_type for layer in layers):
            return []
        return None

    descriptors = manifest.get("manifests", [])
    if not descriptors:
        return None
    digests = []
    for descriptor in descriptors:
        digest = descriptor["digest"]
        bundle = read_manifest(f"{repository}@{digest}")
        if (
            bundle.get("artifactType") != SIGSTORE_BUNDLE
            or bundle.get("subject", {}).get("digest") != f"sha256:{match[1]}"
        ):
            return None
        digests.append(digest)
    return digests


def request(url, method="GET"):
    headers = {
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    for attempt in range(8):
        try:
            with urlopen(Request(url, method=method, headers=headers), timeout=30) as response:
                if method == "GET":
                    return json.load(response)
            # Space out registry mutations during the initial migration.
            time.sleep(1)
            return None
        except HTTPError as error:
            retry_after = error.headers.get("Retry-After")
            exhausted = error.headers.get("X-RateLimit-Remaining") == "0"
            limited = error.code == 429 or (
                error.code == 403 and (retry_after or exhausted or b"rate limit" in error.read().lower())
            )
            if not limited or attempt == 7:
                raise
            delay = 60 * 2**attempt
            if retry_after:
                delay = max(delay, int(retry_after))
            elif exhausted:
                delay = max(delay, int(error.headers["X-RateLimit-Reset"]) - int(time.time()) + 1)
            print(f"GitHub Packages rate limit, retrying in {delay}s", flush=True)
            time.sleep(delay)


def list_versions(endpoint):
    versions = []
    page = 1
    while True:
        try:
            batch = request(f"{endpoint}?per_page=100&page={page}")
        except HTTPError as error:
            if page == 1 and error.code == 404:
                return []
            raise
        versions.extend(batch)
        if len(batch) < 100:
            return versions
        page += 1


def prune(owner, name, newest_python, release, replacement_tags=None, retire_package=False):
    endpoint = versions_endpoint(owner, name)
    versions = list_versions(endpoint)
    if not versions:
        return True
    existing_tags = collect_tags(versions) if replacement_tags is None else replacement_tags
    if not any(tag.endswith(f"-{release}") for tag in existing_tags):
        print(f"{name}: waiting for a release image", flush=True)
        return False
    repository = f"ghcr.io/{owner.lower()}/{name}"
    is_python = name.endswith("base-python")
    if retire_package:
        legacy_tags = collect_tags(versions)
        sidecar_tags = {tag for tag in legacy_tags if COSIGN_TAG.fullmatch(tag)}
        covered = all(
            tag in existing_tags or obsolete_tag(tag, existing_tags, is_python, newest_python, release)
            for tag in legacy_tags - sidecar_tags
        )
        if (
            legacy_tags
            and covered
            and all(cosign_sidecar(repository, tag) is not None for tag in sorted(sidecar_tags))
            and legacy_tags == collect_tags(list_versions(endpoint))
        ):
            print(f"{name}: removing the legacy package after verifying its replacements", flush=True)
            try:
                request(endpoint.removesuffix("/versions"), "DELETE")
            except HTTPError as error:
                if error.code not in (400, 422):
                    raise
                print(f"{name}: GitHub refused package deletion, pruning obsolete versions individually", flush=True)
            else:
                return True
    candidates = []
    bundle_digests = set()
    for version in versions:
        version_tags = tags(version)
        if not version_tags:
            continue
        if all(obsolete_tag(tag, existing_tags, is_python, newest_python, release) for tag in version_tags):
            candidates.append(version)
        elif all(COSIGN_TAG.fullmatch(tag) for tag in version_tags):
            sidecars = [cosign_sidecar(repository, tag) for tag in version_tags]
            if all(sidecar is not None for sidecar in sidecars):
                candidates.append(version)
                bundle_digests.update(digest for sidecar in sidecars for digest in sidecar)
    candidates.extend(
        version for version in versions
        if not tags(version) and version["name"] in bundle_digests
    )

    for version in candidates:
        url = f"{endpoint}/{version['id']}"
        current = request(url)
        if set(tags(current)) != set(tags(version)):
            print(f"{name}: tags changed for version {version['id']}, keeping it", flush=True)
            continue
        print(f"{name}: removing {', '.join(tags(version)) or version['name']}", flush=True)
        request(url, "DELETE")
    return False


def versions_endpoint(owner, name):
    return f"{os.environ['GITHUB_API_URL']}/users/{owner}/packages/container/{name}/versions"


def collect_tags(versions):
    return {tag for version in versions for tag in tags(version)}


def tags(version):
    return version["metadata"]["container"]["tags"]


def public_tags(owner, name):
    repository = f"{owner.lower()}/{name}"
    query = urlencode({"service": "ghcr.io", "scope": f"repository:{repository}:pull"})
    try:
        with urlopen(f"https://ghcr.io/token?{query}", timeout=30) as response:
            token = json.load(response)["token"]
        request = Request(
            f"https://ghcr.io/v2/{repository}/tags/list?n=1000",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request, timeout=30) as response:
            return set(json.load(response).get("tags") or [])
    except HTTPError as error:
        if error.code in (401, 403, 404):
            print(f"{name}: replacement is not publicly pullable (HTTP {error.code})", flush=True)
            return set()
        raise


def platform_tags(repository, release_tags, arches, read_manifest=inspect):
    replacements = {arch: set() for arch in arches}
    for tag in sorted(release_tags):
        manifest = read_manifest(f"{repository}:{tag}")
        for descriptor in manifest.get("manifests", []):
            platform = descriptor.get("platform", {})
            if platform.get("os") != "linux":
                continue
            for arch in arches:
                cpu, variant = PLATFORMS[arch]
                if platform.get("architecture") == cpu and (not variant or platform.get("variant") == variant):
                    replacements[arch].add(tag)
    return replacements


def main():
    owner = os.environ["GITHUB_REPOSITORY_OWNER"]
    release = os.environ["CURRENT_RELEASE"]
    versions = json.loads(Path("versions.json").read_text(encoding="utf-8"))
    newest_python = max((release["version"] for release in versions["python"]), key=version_key)
    for old_name, arches in package_architectures(versions):
        new_name = f"home-assistant-{old_name}"
        replacements = public_tags(owner, new_name)
        if not any(tag.endswith(f"-{release}") for tag in replacements):
            continue
        by_platform = platform_tags(f"ghcr.io/{owner.lower()}/{new_name}", replacements, arches)
        legacy_platforms_retired = True
        for arch in arches:
            retired = prune(owner, f"{arch}-{old_name}", newest_python, release, by_platform[arch], retire_package=True)
            legacy_platforms_retired = legacy_platforms_retired and retired
        prune(owner, old_name, newest_python, release, replacements, retire_package=legacy_platforms_retired)
        prune(owner, new_name, newest_python, release)


if __name__ == "__main__":
    main()
