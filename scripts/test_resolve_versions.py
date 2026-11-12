"""Offline tests for resolve_versions.py, run with: python3 -m unittest discover scripts"""

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import resolve_versions as rv

TODAY = dt.date(2026, 11, 12)

ALPINE_LIBRARY = """\
Maintainers: Someone <someone@example.org> (@someone)
GitRepo: https://github.com/alpinelinux/docker-alpine.git

Tags: 20260805, edge
Architectures: arm64v8, arm32v6, arm32v7, ppc64le, riscv64, s390x, i386, amd64
GitCommit: aaaa

Tags: 3.24.3, 3.24, 3, latest
Architectures: arm64v8, arm32v6, arm32v7, ppc64le, riscv64, s390x, i386, amd64
GitCommit: bbbb

Tags: 3.23.7, 3.23
Architectures: arm64v8, arm32v6, arm32v7, i386, amd64
GitCommit: cccc

Tags: 3.21.9, 3.21
Architectures: amd64
GitCommit: dddd
"""

DEBIAN_LIBRARY = """\
Tags: trixie-slim, 13.7-slim
Architectures: amd64, arm32v5, arm32v7, arm64v8, i386, ppc64le

Tags: bookworm-slim, 12.15-slim
Architectures: amd64, arm32v7, arm64v8, i386, ppc64le

Tags: testing-slim
Architectures: amd64, arm32v7, arm64v8, i386
"""

UBUNTU_LIBRARY = """\
Tags: 24.04, noble
Architectures: amd64, arm32v7, arm64v8, ppc64le, riscv64, s390x

Tags: 26.04, resolute, latest
Architectures: amd64, arm32v7, arm64v8, ppc64le, riscv64, s390x

Tags: 26.10, stonking, rolling
Architectures: amd64, arm32v7, arm64v8, ppc64le, riscv64, s390x
"""

ALPINE_CYCLES = [
    {"cycle": "3.24", "releaseDate": "2026-06-09", "eol": "2028-06-01"},
    {"cycle": "3.23", "releaseDate": "2025-12-04", "eol": "2027-11-01"},
    {"cycle": "3.21", "releaseDate": "2024-12-05", "eol": "2026-11-01"},
    {"cycle": "3.25", "releaseDate": "2026-12-01", "eol": "2028-12-01"},
]

PYTHON_INDEX = """\
<a href="3.12.3/">3.12.3/</a>
<a href="3.13.17/">3.13.17/</a><a href="3.13.18/">3.13.18/</a>
<a href="3.14.10/">3.14.10/</a>
<a href="3.15.2/">3.15.2/</a>
<a href="3.16.0/">3.16.0/</a>
<a href="2.7.18/">2.7.18/</a>
"""

PYTHON_DOCKERFILE = "FROM base\nARG PYTHON_VERSION=3.15.2\nARG CERT_IDENTITY=someone@python.org\n"


class LibraryTest(unittest.TestCase):
    def test_parses_tags_and_architectures(self):
        entries = rv.parse_library(ALPINE_LIBRARY)
        self.assertEqual(len(entries), 4)  # the header stanza has no tags
        self.assertIn("edge", entries[0].tags)
        self.assertEqual(rv.find_entry(entries, "3.24").tags[0], "3.24.3")
        self.assertIsNone(rv.find_entry(entries, "3.99"))

    def test_architecture_mapping_per_distro(self):
        docker = ["amd64", "arm32v5", "arm32v6", "arm32v7", "arm64v8", "i386", "s390x"]
        self.assertEqual(
            rv.map_architectures("alpine", docker), ["amd64", "aarch64", "armv7", "armhf", "i386"]
        )
        # Debian provides armhf through the ARMv5 image, Ubuntu has neither armhf nor i386.
        self.assertEqual(
            rv.map_architectures("debian", ["arm32v5", "amd64"]), ["amd64", "armhf"]
        )
        self.assertEqual(rv.map_architectures("ubuntu", docker), ["amd64", "aarch64", "armv7"])


class DistributionTest(unittest.TestCase):
    def test_alpine_skips_eol_unreleased_and_unpublished(self):
        lines = rv.resolve_alpine(ALPINE_CYCLES, rv.parse_library(ALPINE_LIBRARY), TODAY)
        self.assertEqual([line["version"] for line in lines], ["3.23", "3.24", "edge"])
        self.assertEqual([line["latest"] for line in lines], [False, True, False])
        self.assertEqual([line["dev"] for line in lines], [False, False, True])
        self.assertEqual(lines[1]["architectures"], ["amd64", "aarch64", "armv7", "armhf", "i386"])

    def test_debian_uses_codename_and_slim_tags(self):
        cycles = [
            {"cycle": "13", "codename": "Trixie", "releaseDate": "2025-08-09", "eol": "2030-06-30"},
            {"cycle": "12", "codename": "Bookworm", "releaseDate": "2023-06-10", "eol": "2028-06-30"},
            {"cycle": "11", "codename": "Bullseye", "releaseDate": "2021-08-14", "eol": "2026-08-31"},
        ]
        lines = rv.resolve_debian(cycles, rv.parse_library(DEBIAN_LIBRARY), TODAY)
        self.assertEqual([line["version"] for line in lines], ["bookworm", "trixie", "testing"])
        self.assertNotIn("armhf", lines[0]["architectures"])
        self.assertIn("armhf", lines[1]["architectures"])

    def test_ubuntu_only_lts_and_rolling_dev(self):
        cycles = [
            {"cycle": "26.10", "releaseDate": "2026-10-15", "eol": "2027-07-01", "lts": False},
            {"cycle": "26.04", "releaseDate": "2026-04-23", "eol": "2031-05-29", "lts": True},
            {"cycle": "24.04", "releaseDate": "2024-04-25", "eol": "2029-05-31", "lts": True},
            {"cycle": "20.04", "releaseDate": "2020-04-23", "eol": "2025-05-31", "lts": True},
        ]
        lines = rv.resolve_ubuntu(cycles, rv.parse_library(UBUNTU_LIBRARY), TODAY)
        self.assertEqual([line["version"] for line in lines], ["24.04", "26.04", "rolling"])
        self.assertTrue(lines[1]["latest"])

    def test_ubuntu_prefers_devel_when_present(self):
        library = rv.parse_library(UBUNTU_LIBRARY + "\nTags: devel\nArchitectures: amd64\n")
        cycles = [{"cycle": "26.04", "releaseDate": "2026-04-23", "eol": "2031-05-29", "lts": True}]
        self.assertEqual(rv.resolve_ubuntu(cycles, library, TODAY)[-1]["version"], "devel")


class PythonTest(unittest.TestCase):
    def test_selects_newest_final_minors(self):
        final = lambda version: version != "3.16.0"  # 3.16.0 only has pre-releases
        self.assertEqual(
            rv.select_python_releases(PYTHON_INDEX, final),
            {"3.15": "3.15.2", "3.14": "3.14.10", "3.13": "3.13.18"},
        )

    def test_latest_is_the_newest_settled_release(self):
        patches = {"3.13": "3.13.18", "3.14": "3.14.10", "3.15": "3.15.2"}
        cycles = [
            {"cycle": "3.15", "releaseDate": "2026-10-01"},
            {"cycle": "3.14", "releaseDate": "2025-10-07"},
            {"cycle": "3.13", "releaseDate": "2024-10-07"},
        ]
        lines = rv.resolve_python(patches, cycles, TODAY)
        self.assertEqual([line["version"] for line in lines if line["latest"]], ["3.14"])
        later = rv.resolve_python(patches, cycles, dt.date(2027, 2, 1))
        self.assertEqual([line["version"] for line in later if line["latest"]], ["3.15"])


class GeneratedPythonDirsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for minor in ("3.14", "3.15"):
            (self.root / minor).mkdir()
            (self.root / minor / "Dockerfile").write_text(PYTHON_DOCKERFILE)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_missing_release_from_newest_template(self):
        touched = rv.sync_generated_python_dirs(
            {"3.14": "3.14.11", "3.15": "3.15.3", "3.16": "3.16.0"}, self.root
        )
        self.assertEqual(touched, ["3.16"])
        generated = self.root / "3.16"
        self.assertTrue((generated / rv.GENERATED_MARKER).exists())
        self.assertIn("ARG PYTHON_VERSION=3.16.0", (generated / "Dockerfile").read_text())
        # Directories owned by upstream are left alone.
        self.assertIn("3.15.2", (self.root / "3.15" / "Dockerfile").read_text())

    def test_generated_directory_follows_patch_releases(self):
        rv.sync_generated_python_dirs({"3.16": "3.16.0"}, self.root)
        touched = rv.sync_generated_python_dirs({"3.16": "3.16.1"}, self.root)
        self.assertEqual(touched, ["3.16"])
        self.assertIn("3.16.1", (self.root / "3.16" / "Dockerfile").read_text())


if __name__ == "__main__":
    unittest.main()
