def _headers(session):
    return {"Authorization": f"Bearer {session['token']}"}
