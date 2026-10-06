import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from starlette.applications import Starlette
from starlette.responses import FileResponse, Response
from starlette.routing import Route

spec = importlib.util.spec_from_file_location('image_http_under_test', Path(__file__).parents[1] / 'image_http.py')
image_http = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image_http)


class ImageHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_head_keeps_image_headers_without_consuming_other_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.png'
            path.write_bytes(b'example-image-bytes')
            publisher = SimpleNamespace(owned={'owned': (path, 100)}, wrapper=AsyncMock(return_value=str(path)))
            async def original_get(request):
                return FileResponse(path)
            app = Starlette(routes=[Route('/api/file/{token}', original_get, methods=['GET'])])
            app.router.routes[0].methods.discard('HEAD')  # Match FastAPI's GET-only route.
            route = image_http.ImageHeadRoute(app, publisher)
            route.install()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
                head = await client.head('/api/file/owned')
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.headers['content-type'], 'image/png')
                self.assertEqual(int(head.headers['content-length']), len(path.read_bytes()))
                self.assertEqual(head.content, b'')
                self.assertEqual((await client.get('/api/file/owned')).content, path.read_bytes())
                publisher.wrapper.reset_mock()
                self.assertEqual((await client.head('/api/file/unrelated')).status_code, 405)
                publisher.wrapper.assert_not_awaited()
                route.close()
                self.assertEqual((await client.head('/api/file/owned')).status_code, 405)

    async def test_expired_image_head_is_not_success(self):
        publisher = SimpleNamespace(owned={'expired': None}, wrapper=AsyncMock(side_effect=FileNotFoundError))
        app = Starlette()
        route = image_http.ImageHeadRoute(app, publisher)
        route.install()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            self.assertEqual((await client.head('/api/file/expired')).status_code, 404)
