from fastapi import FastAPI, Response

from fast_ddd_port.models import RequestModel, ResponseModel
from fast_ddd_port.preconditions import ExpectedVersion, install_openapi_fixups


class Resource(ResponseModel):
    etag: str


class Change(RequestModel):
    display_name: str


def test_openapi_declares_shared_problem_media_headers_and_retains_success_models() -> None:
    app = FastAPI()

    @app.post("/resources", status_code=201)
    async def create(body: Change, response: Response) -> Resource:
        del body
        response.headers["Location"] = "/resources/1"
        return Resource(etag='"1"')

    @app.patch("/resources/{resource_id}")
    async def change(resource_id: str, body: Change, version: ExpectedVersion) -> Resource:
        del resource_id, body
        return Resource(etag=f'"{version}"')

    install_openapi_fixups(app)
    schema = app.openapi()
    for operation in (
        schema["paths"]["/resources"]["post"],
        schema["paths"]["/resources/{resource_id}"]["patch"],
    ):
        for status in ("400", "401", "403", "404", "405", "409", "422", "500", "503"):
            response = operation["responses"][status]
            assert response["content"] == {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}},
            }
            assert "X-Trace-Id" in response["headers"]
        assert "WWW-Authenticate" in operation["responses"]["401"]["headers"]
        assert "Allow" in operation["responses"]["405"]["headers"]
    created = schema["paths"]["/resources"]["post"]["responses"]["201"]
    assert created["content"]["application/json"]["schema"]["$ref"].endswith("/Resource")
    assert {"Location", "ETag", "X-Trace-Id"} <= created["headers"].keys()
    changed = schema["paths"]["/resources/{resource_id}"]["patch"]
    assert changed["parameters"][1]["required"] is True
    assert {"412", "428"} <= changed["responses"].keys()
    assert schema["components"]["schemas"]["Problem"]["properties"]["traceId"]
    assert schema["components"]["schemas"]["FieldError"]["properties"]["pointer"]
    assert app.openapi() is schema
