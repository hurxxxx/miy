def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
