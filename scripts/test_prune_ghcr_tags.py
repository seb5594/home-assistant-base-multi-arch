import unittest
from unittest.mock import patch

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
        self.assertEqual(request.call_args_list, [unittest.mock.call(endpoint), unittest.mock.call(endpoint, "DELETE")])

    def test_retires_older_python_dev_after_the_replacement_exists(self):
        for tag in ("3.9-dev", "3.9-dev-2026.11.16.8", "3.9-dev-2026.11"):
            self.assertTrue(cleanup.obsolete_tag(tag, {"3.15-dev-2026.11"}, True, "3.15", "2026.11"))
            self.assertFalse(cleanup.obsolete_tag(tag, {"3.15-dev"}, True, "3.15", "2026.11"))
        self.assertFalse(cleanup.obsolete_tag("3.15-dev", {"3.15-dev-2026.11"}, True, "3.15", "2026.11"))

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
