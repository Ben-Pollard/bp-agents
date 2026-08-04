import httpx


def make_handler(json_data: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, json=json_data)

    return handler
