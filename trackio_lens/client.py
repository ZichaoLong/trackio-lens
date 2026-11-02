"""HTTP SDK authentication, separate from Trackio's write token."""

import httpx


class LensAuth(httpx.Auth):
    def __init__(self, token: str):
        self.token = token

    def auth_flow(self, request):
        request.headers["X-Trackio-Lens-Token"] = self.token
        yield request


def remote_client(url: str, token: str, write_token: str | None = None):
    from trackio.remote_client import RemoteClient

    # Auth handles both version negotiation and API calls. Upstream 0.44.0
    # passes headers twice during negotiation if httpx_kwargs['headers'] is used.
    return RemoteClient(
        url, write_token=write_token, httpx_kwargs={"auth": LensAuth(token)}
    )
