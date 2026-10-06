"""HEAD support for this plugin's published images, without changing core routes."""
from starlette.responses import FileResponse, Response
from starlette.routing import Route


class ImageHeadRoute:
    def __init__(self, app, publisher):
        self.app = app
        self.publisher = publisher
        self.route = None

    def install(self):
        async def head_image(request):
            token = request.path_params['token']
            # Do not inspect or consume unrelated one-shot AstrBot file tokens.
            if token not in self.publisher.owned:
                return Response(status_code=405, headers={'Allow': 'GET'})
            try:
                path = await self.publisher.wrapper(token)
            except (FileNotFoundError, KeyError):
                return Response(status_code=404)
            return FileResponse(path, headers={'Cache-Control': 'private, max-age=60'})

        self.route = Route('/api/file/{token}', head_image, methods=['HEAD'],
                           name='official_cards_image_head')
        self.app.router.routes.insert(0, self.route)

    def close(self):
        if self.route is not None and self.route in self.app.router.routes:
            self.app.router.routes.remove(self.route)
        self.route = None
