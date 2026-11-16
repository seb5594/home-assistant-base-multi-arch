"""Remove the superseded versions from the base image packages."""

import json
import os
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DAILY_TAG = re.compile(r"(.+-\d{4}\.\d{2})\.\d{2}\.\d+")
PYTHON_DEV_TAG = re.compile(r"(\d+\.\d+)-dev(?:-\d{4}\.\d{2}(?:\.\d{2}\.\d+)?)?")
COSIGN_TAG = re.compile(r"sha256-([a-f0-9]{64})(?:\.(sig|att))?")
SIGSTORE_BUNDLE = "application/vnd.dev.sigstore.bundle.v0.3+json"


def package_names(versions):
    """Use the same package names as the image workflow."""
    families = {
        "base": versions["alpine"],
        "base-debian": versions["debian"],
        "base-ubuntu": versions["ubuntu"],
        "base-python": versions["alpine"],
    }
    for name, releases in families.items():
        yield name
        arches = {arch for release in releases for arch in release["architectures"]}
        yield from (f"{arch}-{name}" for arch in sorted(arches))


def version_key(version):
    return tuple(map(int, version.split(".")))


def obsolete_tag(tag, existing_tags, is_python, newest_python, month):
    """Keep the current aliases and any daily tag without a monthly replacement."""
    dev = PYTHON_DEV_TAG.fullmatch(tag) if is_python else None
    if dev and version_key(dev[1]) < version_key(newest_python):
        return f"{newest_python}-dev-{month}" in existing_tags
    daily = DAILY_TAG.fullmatch(tag)
    return bool(daily and daily[1] in existing_tags)


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
    with urlopen(Request(url, method=method, headers=headers), timeout=30) as response:
        return json.load(response) if method == "GET" else None


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


def prune(owner, name, newest_python, month):
    endpoint = f"{os.environ['GITHUB_API_URL']}/users/{owner}/packages/container/{name}/versions"
    versions = list_versions(endpoint)
    existing_tags = {tag for version in versions for tag in tags(version)}
    if not any(tag.endswith(f"-{month}") for tag in existing_tags):
        print(f"{name}: waiting for a monthly image", flush=True)
        return
    repository = f"ghcr.io/{owner.lower()}/{name}"
    is_python = name.endswith("base-python")
    candidates = []
    bundle_digests = set()
    for version in versions:
        version_tags = tags(version)
        if not version_tags:
            continue
        if all(obsolete_tag(tag, existing_tags, is_python, newest_python, month) for tag in version_tags):
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


def tags(version):
    return version["metadata"]["container"]["tags"]


def main():
    owner = os.environ["GITHUB_REPOSITORY_OWNER"]
    month = os.environ["CURRENT_MONTH"]
    versions = json.loads(Path("versions.json").read_text(encoding="utf-8"))
    newest_python = max((release["version"] for release in versions["python"]), key=version_key)
    for name in package_names(versions):
        prune(owner, name, newest_python, month)


if __name__ == "__main__":
    main()
