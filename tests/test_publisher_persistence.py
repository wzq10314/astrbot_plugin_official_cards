"""Published image capabilities survive reloads without extending their lifetime."""

import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image as PILImage
import test_transport as fixtures


class Service:
    def __init__(self):
        self.tokens = {}
        self.counter = 0

    async def register_file(self, path, timeout=None):
        self.counter += 1
        token = f"image-token-{self.counter}"
        self.tokens[token] = path
        return token

    async def handle_file(self, token):
        return self.tokens.pop(token)


class PublisherPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def make_publisher(self, service, cache):
        return fixtures.transport.ImagePublisher(service, cache, "https://example.test", ttl=60)

    async def test_reload_keeps_reusable_image_and_original_token_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "original.png"
            PILImage.new("RGB", (12, 8)).save(source)
            service = Service()
            external = await service.register_file("external-file")
            publisher = self.make_publisher(service, directory / "cache")
            publisher.install()
            url, _, _ = await publisher.publish(fixtures.Image(str(source)))
            token = url.rsplit("/", 1)[-1]
            published_path = await service.handle_file(token)
            index = json.loads(publisher.index_path.read_text())
            self.assertEqual(set(index["tokens"]), {token})
            self.assertNotIn(external, index["tokens"])
            original_expiry = index["tokens"][token]["expires_at"]
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(publisher.index_path.stat().st_mode), 0o600)
            publisher.close()
            self.assertTrue(publisher.index_path.is_file())
            with self.assertRaises(KeyError):
                await service.handle_file(token)
            reloaded = self.make_publisher(service, directory / "cache")
            reloaded.install()
            try:
                self.assertEqual(await service.handle_file(token), published_path)
                self.assertEqual(await service.handle_file(token), published_path)
                self.assertEqual(await service.handle_file(external), "external-file")
                with self.assertRaises(KeyError):
                    await service.handle_file(external)
                restored = json.loads(reloaded.index_path.read_text())["tokens"][token]
                self.assertAlmostEqual(restored["expires_at"], original_expiry, delta=0.05)
            finally:
                reloaded.close()

    async def test_expired_index_entry_is_removed_with_its_cache_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "original.png"
            PILImage.new("RGB", (12, 8)).save(source)
            service = Service()
            publisher = self.make_publisher(service, directory / "cache")
            publisher.install()
            url, _, _ = await publisher.publish(fixtures.Image(str(source)))
            token = url.rsplit("/", 1)[-1]
            published_path = Path(await service.handle_file(token))
            index = json.loads(publisher.index_path.read_text())
            index["tokens"][token]["expires_at"] = time.time() - 1
            publisher.index_path.write_text(json.dumps(index))
            publisher.close()
            reloaded = self.make_publisher(service, directory / "cache")
            self.assertFalse(reloaded.owned)
            self.assertFalse(published_path.exists())
            self.assertTrue(source.is_file())
            self.assertEqual(json.loads(reloaded.index_path.read_text())["tokens"], {})

    async def test_reload_rebuilds_monotonic_expiry_without_renewing_ttl(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            cache = directory / "cache"
            cache.mkdir()
            filename = "a" * 64 + ".png"
            PILImage.new("RGB", (2, 2)).save(cache / filename)
            index_path = cache / "owned_image_tokens.json"
            index_path.write_text(json.dumps({"version": 1, "tokens": {
                "owned-token": {"filename": filename, "expires_at": 1020},
            }}))
            with patch.object(fixtures.transport.time, "time", return_value=1000), patch.object(fixtures.transport.time, "monotonic", return_value=5000):
                publisher = self.make_publisher(Service(), cache)
            self.assertEqual(publisher.owned["owned-token"][1], 5020)

    async def test_index_rejects_traversal_absolute_paths_formats_and_bad_expiries(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            cache = directory / "cache"
            cache.mkdir()
            filename = "a" * 64 + ".png"
            PILImage.new("RGB", (2, 2)).save(cache / filename)
            outside = directory / ("b" * 64 + ".png")
            PILImage.new("RGB", (2, 2)).save(outside)
            invalid_format = cache / ("c" * 64 + ".txt")
            invalid_format.write_text("not an image")
            expiry = time.time() + 40
            rows = {
                "valid": {"filename": filename, "expires_at": expiry},
                "traversal": {"filename": "../" + outside.name, "expires_at": expiry},
                "absolute": {"filename": str(outside), "expires_at": expiry},
                "wrong-format": {"filename": invalid_format.name, "expires_at": expiry},
                "missing": {"filename": "d" * 64 + ".png", "expires_at": expiry},
                "wrong-name": {"filename": "source.png", "expires_at": expiry},
                "bad-expiry": {"filename": filename, "expires_at": "later"},
                "nan-expiry": {"filename": filename, "expires_at": float("nan")},
                "invalid/token": {"filename": filename, "expires_at": expiry},
            }
            index_path = cache / "owned_image_tokens.json"
            index_path.write_text(json.dumps({"version": 1, "tokens": rows}))
            publisher = self.make_publisher(Service(), cache)
            self.assertEqual(set(publisher.owned), {"valid"})
            self.assertEqual(set(json.loads(index_path.read_text())["tokens"]), {"valid"})
            self.assertTrue(outside.is_file())
            self.assertTrue(invalid_format.is_file())

    async def test_index_does_not_accept_symlink_outside_the_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            cache = directory / "cache"
            cache.mkdir()
            outside = directory / "private.png"
            PILImage.new("RGB", (2, 2)).save(outside)
            link = cache / ("a" * 64 + ".png")
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("Creating symbolic links is not available on this host")
            (cache / "owned_image_tokens.json").write_text(json.dumps({"version": 1, "tokens": {
                "symlink-token": {"filename": link.name, "expires_at": time.time() + 30},
            }}))
            publisher = self.make_publisher(Service(), cache)
            self.assertFalse(publisher.owned)
            self.assertTrue(outside.is_file())

    async def test_interrupted_atomic_replace_preserves_previous_valid_index(self):
        with tempfile.TemporaryDirectory() as directory:
            publisher = self.make_publisher(Service(), Path(directory) / "cache")
            publisher._save_index()
            before = publisher.index_path.read_bytes()
            with patch.object(fixtures.transport.os, "replace", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(OSError):
                    publisher._save_index()
            self.assertEqual(publisher.index_path.read_bytes(), before)
            self.assertEqual(list(publisher.cache_dir.glob(".owned_image_tokens-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
