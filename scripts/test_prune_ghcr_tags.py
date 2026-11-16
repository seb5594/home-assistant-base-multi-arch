import unittest
from unittest.mock import call, patch

import prune_ghcr_tags as cleanup


def package_version(identifier, *tags):
    return {"id": identifier, "name": f"version-{identifier}", "metadata": {"container": {"tags": tags}}}


class PruneTagsTest(unittest.TestCase):
    def test_preserves_aliases_and_versions_without_replacement(self):
        versions = [
            package_version(1, "3.23", "3.23-2026.11.16.8"),
            package_version(2, "3.23-2026.11"),
            package_version(3, "3.23-2026.11.15.7"),
            package_version(4, "3.24-2026.11.15.7"),
        ]
        with (
            patch.dict(cleanup.os.environ, {"GITHUB_API_URL": "https://api.example.test"}),
            patch.object(cleanup, "list_versions", return_value=versions),
            patch.object(cleanup, "request", side_effect=[versions[2], None]) as request,
        ):
            cleanup.prune("owner", "base", "3.15", "2026.11")
        endpoint = "https://api.example.test/users/owner/packages/container/base/versions/3"
        self.assertEqual(request.call_args_list, [call(endpoint), call(endpoint, "DELETE")])

    def test_uses_monthly_tags_from_the_renamed_package_for_cleanup(self):
        old = package_version(3, "3.23-2026.11.15.7")
        with (
            patch.dict(cleanup.os.environ, {"GITHUB_API_URL": "https://api.example.test"}),
            patch.object(cleanup, "list_versions", return_value=[old]),
            patch.object(cleanup, "request", side_effect=[old, None]) as request,
        ):
            cleanup.prune("owner", "base", "3.15", "2026.11", {"3.23-2026.11"})
        endpoint = "https://api.example.test/users/owner/packages/container/base/versions/3"
        self.assertEqual(request.call_args_list, [call(endpoint), call(endpoint, "DELETE")])

    def test_retires_legacy_package_only_after_all_stable_tags_are_replaced(self):
        old = package_version(3, "3.23", "3.23-2026.11.15.7")
        endpoint = "https://api.example.test/users/owner/packages/container/base"
        for replacements, expected in (
            ({"3.23-2026.11"}, []),
            ({"3.23", "3.23-2026.11"}, [call(endpoint, "DELETE")]),
        ):
            with (
                patch.dict(cleanup.os.environ, {"GITHUB_API_URL": "https://api.example.test"}),
                patch.object(cleanup, "list_versions", return_value=[old]),
                patch.object(cleanup, "request") as request,
            ):
                cleanup.prune("owner", "base", "3.15", "2026.11", replacements, retire_package=True)
            self.assertEqual(request.call_args_list, expected)

    def test_retires_older_python_dev_after_the_replacement_exists(self):
        for tag in ("3.9-dev", "3.9-dev-2026.11.16.8", "3.9-dev-2026.11"):
            self.assertTrue(cleanup.obsolete_tag(tag, {"3.15-dev-2026.11"}, True, "3.15", "2026.11"))
            self.assertFalse(cleanup.obsolete_tag(tag, {"3.15-dev"}, True, "3.15", "2026.11"))
        self.assertFalse(cleanup.obsolete_tag("3.15-dev", {"3.15-dev-2026.11"}, True, "3.15", "2026.11"))

    def test_replacement_only_covers_platforms_present_in_the_image_index(self):
        index = {"manifests": [
            {"platform": {"os": "linux", "architecture": "arm", "variant": "v7"}},
            {"platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
            {"platform": {"os": "unknown", "architecture": "unknown"}},
        ]}
        tags = cleanup.platform_tags(
            "ghcr.io/owner/home-assistant-base", {"3.23"}, ["armv7", "armhf", "aarch64"], lambda _: index
        )
        self.assertEqual(tags, {"armv7": {"3.23"}, "armhf": set(), "aarch64": {"3.23"}})

    def test_recognizes_the_bundle_by_type_and_subject(self):
        subject = "sha256:" + "a" * 64
        tag = subject.replace(":", "-")
        digest = "sha256:" + "b" * 64
        repo = "ghcr.io/owner/base"
        manifests = {
            f"{repo}:{tag}": {"manifests": [{"digest": digest}]},
            f"{repo}@{digest}": {
                "artifactType": cleanup.SIGSTORE_BUNDLE,
                "subject": {"digest": subject},
            },
        }
        self.assertEqual(cleanup.cosign_sidecar(repo, tag, manifests.__getitem__), [digest])
        manifests[f"{repo}@{digest}"]["subject"]["digest"] = digest
        self.assertIsNone(cleanup.cosign_sidecar(repo, tag, manifests.__getitem__))


if __name__ == "__main__":
    unittest.main()
