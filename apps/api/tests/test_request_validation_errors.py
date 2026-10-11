from miy_api.core.request_validation_errors import build_request_validation_error_body


def test_request_validation_body_handles_unknown_error_shape() -> None:
    body, error_code = build_request_validation_error_body(
        [{"loc": ("query", "cursor"), "ctx": {"unexpected": object()}}],
        "en-US",
    )

    assert error_code == "validation.request_invalid"
    assert body == {
        "detail": "Request validation failed.",
        "code": "validation.request_invalid",
        "validation": [
            {
                "loc": ["query", "cursor"],
                "type": "unknown",
                "message": "Value is invalid.",
            }
        ],
    }
