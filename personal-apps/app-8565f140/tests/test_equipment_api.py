import unittest
from types import SimpleNamespace
from uuid import uuid4
from fastapi import FastAPI, HTTPException
import asyncio
import httpx

class TestClient:
    def __init__(self, app): self.app = app
    def request(self, method, path, **kwargs):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(run())
    def get(self, path, **kwargs): return self.request("GET", path, **kwargs)
    def post(self, path, **kwargs): return self.request("POST", path, **kwargs)
    def put(self, path, **kwargs): return self.request("PUT", path, **kwargs)
from business import install

class EquipmentAPITest(unittest.TestCase):
    def setUp(self):
        self.records = {}
        self.calls = []
        self.fail = False
        async def gateway(method, path, **kw):
            self.calls.append((method, path, kw))
            owner = kw["headers"]["Authorization"]
            if owner == "Bearer denied": raise HTTPException(403)
            if owner == "Bearer expired": raise HTTPException(401)
            if path == "/session": return {"id": owner}
            if self.fail: raise HTTPException(503)
            records = self.records.setdefault(owner, {})
            if path.endswith("by-key"):
                for rec in records.values():
                    if rec["payload"]["number"] == kw["params"]["record_key"]: return rec
                raise HTTPException(404)
            if path == "/_data/equipment":
                if method == "GET": return {"items":list(records.values()), "next_cursor":None}
                payload = kw["json"]["payload"]
                if any(r["payload"]["number"] == kw["json"]["record_key"] for r in records.values()): raise HTTPException(409)
                rec = {"id":str(uuid4()), "payload":payload, "version":1}
                records[rec["id"]] = rec
                return rec
            identifier = path.rsplit("/", 1)[1]
            if identifier not in records: raise HTTPException(404)
            rec = records[identifier]
            if method == "PUT":
                if kw["json"]["expected_version"] != rec["version"]: raise HTTPException(409)
                rec = {**rec, "payload":kw["json"]["payload"], "version":rec["version"]+1}
                records[identifier] = rec
            return rec
        app = FastAPI()
        install(app, SimpleNamespace(installation_id="fixed-install", origin="https://app.example"), gateway)
        self.client = TestClient(app)
        self.headers = {"Authorization":"Bearer alice"}
        self.payload = {"name":"노트북", "number":" test-001 ", "user":"가상사용자 A", "location":"가상 사무실", "status":"in_use"}

    def create(self):
        response = self.client.post("/api/equipment", json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_create_duplicate_lookup_and_roundtrip(self):
        rec = self.create()
        self.assertEqual(rec["payload"]["number"], "TEST-001")
        self.assertEqual(self.client.post("/api/equipment", json=self.payload, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.get("/api/equipment/by-number?number=test-001", headers=self.headers).json()["id"], rec["id"])
        self.assertEqual(self.client.get("/api/equipment", headers=self.headers).json()["items"], [rec])
        for _, _, kw in self.calls:
            self.assertEqual(kw["params"]["installation_id"], "fixed-install")
            self.assertEqual(kw["params"]["audience"], "https://app.example")

    def test_number_normalized_length_and_roundtrip(self):
        for invalid in ["ß" * 40, "ß" * 32 + "a", "a" * 65]:
            with self.subTest(invalid=invalid):
                before = len(self.calls)
                response = self.client.post("/api/equipment", json={**self.payload, "number":invalid}, headers=self.headers)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(len(self.calls), before)
                self.assertEqual(self.client.get("/api/equipment/by-number", params={"number":invalid}, headers=self.headers).status_code, 422)
        for raw in ["  " + "ß" * 32 + "  ", " a" + "b" * 63 + " ", " test-002 ", "😀" * 64]:
            with self.subTest(raw=raw):
                number = raw.strip().upper()
                rec = self.client.post("/api/equipment", json={**self.payload, "number":raw}, headers=self.headers).json()
                self.assertEqual(rec["payload"]["number"], number)
                self.assertEqual(self.calls[-1][2]["json"]["record_key"], number)
                for lookup in [raw, number]:
                    response = self.client.get("/api/equipment/by-number", params={"number":lookup}, headers=self.headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["id"], rec["id"])
                response = self.client.put("/api/equipment/"+rec["id"], json={**rec["payload"], "location":"변경 위치", "expected_version":1}, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["payload"]["number"], number)
                before = len(self.calls)
                invalid_update = {**rec["payload"], "number":"ß" * 40, "expected_version":2}
                self.assertEqual(self.client.put("/api/equipment/"+rec["id"], json=invalid_update, headers=self.headers).status_code, 422)
                self.assertEqual(len(self.calls), before)
                self.assertEqual(self.client.post("/api/equipment", json={**self.payload, "number":number}, headers=self.headers).status_code, 409)

    def test_update_conflict_and_immutable_number(self):
        rec = self.create()
        path = "/api/equipment/"+rec["id"]
        data = {**rec["payload"], "status":"stored", "expected_version":1}
        result = self.client.put(path, json=data, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["payload"]["user"], "")
        self.assertEqual(self.client.put(path, json=data, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.put(path, json={**data,"number":"NEW"}, headers=self.headers).status_code, 422)

    def test_auth_and_owner_isolation(self):
        rec = self.create()
        self.assertEqual(self.client.get("/api/equipment").status_code, 401)
        for token, code in [("denied",403),("expired",401)]:
            self.assertEqual(self.client.get("/api/equipment", headers={"Authorization":"Bearer "+token}).status_code, code)
        bob = {"Authorization":"Bearer bob"}
        self.assertEqual(self.client.get("/api/equipment", headers=bob).json()["items"], [])
        self.assertEqual(self.client.get("/api/equipment/"+rec["id"], headers=bob).status_code,404)

    def test_validation_and_storage_failure(self):
        for patch in [{"name":" "},{"location":" "},{"number":" "},{"user":" "},{"status":"broken"},{"extra":True}]:
            self.assertEqual(self.client.post("/api/equipment", json={**self.payload, **patch}, headers=self.headers).status_code,422)
        self.assertEqual(self.client.get("/api/equipment?after=invalid",headers=self.headers).status_code,422)
        self.assertEqual(self.client.get("/api/equipment/by-number?number=", headers=self.headers).status_code,422)
        self.assertEqual(self.client.post("/api/equipment", json=self.payload, headers={"Authorization":"Bearer denied"}).status_code,403)
        self.fail = True
        self.assertEqual(self.client.post("/api/equipment",json=self.payload,headers=self.headers).status_code,503)

if __name__ == "__main__": unittest.main()
