import os, types
import json
from enum import Enum
import requests  # type: ignore
import time
from typing import Callable, Optional, Union, List
from litellm.utils import ModelResponse, Usage, CustomStreamWrapper, map_finish_reason
import litellm, uuid
import httpx, inspect  # type: ignore
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler
from .base import BaseLLM


class VertexAIError(Exception):
    def __init__(self, status_code, message):
        self.status_code = status_code
        self.message = message
        self.request = httpx.Request(
            method="POST", url=" https://cloud.google.com/vertex-ai/"
        )
        self.response = httpx.Response(status_code=status_code, request=self.request)
        super().__init__(
            self.message
        )  # Call the base class constructor with the parameters it needs


class VertexLLM(BaseLLM):
    from google.auth.credentials import Credentials  # type: ignore[import-untyped]

    def __init__(self) -> None:
        from google.auth.credentials import Credentials  # type: ignore[import-untyped]

        super().__init__()
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self._credentials: Optional[Credentials] = None
        self.project_id: Optional[str] = None

    def load_auth(self) -> tuple[Credentials, str]:
        from google.auth.transport.requests import Request  # type: ignore[import-untyped]
        from google.auth.credentials import Credentials  # type: ignore[import-untyped]
        import google.auth as google_auth

        credentials, project_id = google_auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

        credentials.refresh(Request())

        if not project_id:
            raise ValueError("Could not resolve project_id")

        if not isinstance(project_id, str):
            raise TypeError(
                f"Expected project_id to be a str but got {type(project_id)}"
            )

        return credentials, project_id

    def refresh_auth(self, credentials: Credentials) -> None:
        from google.auth.transport.requests import Request  # type: ignore[import-untyped]

        credentials.refresh(Request())

    def _prepare_request(self, request: httpx.Request) -> None:
        access_token = self._ensure_access_token()

        if request.headers.get("Authorization"):
            # already authenticated, nothing for us to do
            return

        request.headers["Authorization"] = f"Bearer {access_token}"

    def _ensure_access_token(self) -> str:
        if self.access_token is not None:
            return self.access_token

        if not self._credentials:
            self._credentials, project_id = self.load_auth()
            if not self.project_id:
                self.project_id = project_id
        else:
            self.refresh_auth(self._credentials)

        if not self._credentials.token:
            raise RuntimeError("Could not resolve API token from the environment")

        assert isinstance(self._credentials.token, str)
        return self._credentials.token

    async def aimage_generation(
        self,
        prompt: str,
        vertex_project: str,
        vertex_location: str,
        model: Optional[
            str
        ] = "imagegeneration",  # vertex ai uses imagegeneration as the default model
        client: Optional[AsyncHTTPHandler] = None,
        optional_params: Optional[dict] = None,
        timeout: Optional[int] = None,
        logging_obj=None,
        model_response=None,
    ):
        response = None
        if client is None:
            _params = {}
            if timeout is not None:
                if isinstance(timeout, float) or isinstance(timeout, int):
                    _httpx_timeout = httpx.Timeout(timeout)
                    _params["timeout"] = _httpx_timeout
            client = AsyncHTTPHandler(**_params)  # type: ignore
        else:
            client = client  # type: ignore

        # make POST request to
        # https://us-central1-aiplatform.googleapis.com/v1/projects/PROJECT_ID/locations/us-central1/publishers/google/models/imagegeneration:predict
        url = f"https://{vertex_location}-aiplatform.googleapis.com/v1/projects/{vertex_project}/locations/{vertex_location}/publishers/google/models/{model}:predict"

        """
        Docs link: https://console.cloud.google.com/vertex-ai/publishers/google/model-garden/imagegeneration?project=adroit-crow-413218
        curl -X POST \
        -H "Authorization: Bearer $(gcloud auth print-access-token)" \
        -H "Content-Type: application/json; charset=utf-8" \
        -d {
            "instances": [
                {
                    "prompt": "a cat"
                }
            ]
        } \
        "https://us-central1-aiplatform.googleapis.com/v1/projects/PROJECT_ID/locations/us-central1/publishers/google/models/imagegeneration:predict"
        """

        import vertexai

        auth_header = self._ensure_access_token()

        request_data = {
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1},
        }

        response = await client.post(
            url=url,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {auth_header}",
            },
            data=json.dumps(request_data),
        )

        if response.status_code != 200:
            raise Exception(f"Error: {response.status_code} {response.text}")

        return model_response