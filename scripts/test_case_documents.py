#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


class FakeCozeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "code": 0,
            "conversation_id": "fake-conversation",
            "messages": [{"type": "answer", "content": "这是一次测试回答"}],
        }


class FakeRecognizeAiResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "code": 0,
            "conversation_id": "fake-case-recognition",
            "messages": [{
                "type": "answer",
                "content": (
                    '{"title":"链接识别便秘案例","customer_profile":"42岁女性，久坐",'
                    '"symptom_tags":"便秘,腹胀","product_tags":"益生菌,膳食纤维",'
                    '"scenario":"两周调理反馈","summary":"客户排便频率改善，腹胀减轻。",'
                    '"content":"客户长期排便不规律，搭配益生菌和膳食纤维后反馈腹胀减轻。"}'
                ),
            }],
        }


class FakeHtmlResponse:
    status_code = 200
    headers = {"Content-Type": "text/html; charset=utf-8"}
    encoding = "utf-8"
    apparent_encoding = "utf-8"
    text = """
    <html>
      <head>
        <title>网页原始便秘案例</title>
        <meta name="description" content="客户三四天排便一次，关注肠道调理。">
      </head>
      <body>
        <header>导航</header>
        <article>
          <h1>长期便秘客户反馈</h1>
          <p>42岁女性，久坐办公室，饮食不规律。</p>
          <p>主要困扰是便秘、腹胀，使用益生菌和膳食纤维两周后反馈腹胀减轻。</p>
        </article>
      </body>
    </html>
    """

    def raise_for_status(self):
        return None


class FakeHtmlSession:
    def get(self, *args, **kwargs):
        return FakeHtmlResponse()


def fake_post(*args, **kwargs):
    return FakeCozeResponse()


def fake_public_dns(*args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


def main():
    with tempfile.TemporaryDirectory(prefix="acs-cases-") as tmpdir:
        os.environ["DATABASE_DIR"] = tmpdir
        os.environ["SECRET_KEY"] = "test-secret-key-32-bytes-minimum!!"
        os.environ["ADMIN_USERNAME"] = "admin8"
        os.environ["COZE_API_KEY"] = "fake-key"

        from app import app
        from models import (
            create_case_document,
            get_all_case_documents,
            get_db_connection,
            search_case_documents,
            set_case_document_status,
        )

        conn = get_db_connection()
        case_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='case_documents'"
        ).fetchone()
        fts_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='case_documents_fts'"
        ).fetchone()
        conn.close()
        assert_true(case_table is not None, "case_documents table missing")
        assert_true(fts_table is not None, "case_documents_fts table missing")

        seeded = get_all_case_documents()
        assert_true(len(seeded) == 5, f"expected 5 seed cases, got {len(seeded)}")

        constipation = search_case_documents("我妈便秘腹胀适合什么", limit=3)
        assert_true(
            constipation and constipation[0]["title"] == "长期便秘客户调理记录",
            f"便秘 search mismatch: {constipation}",
        )

        bloating = search_case_documents("饭后腹胀消化慢怎么办", limit=3)
        assert_true(
            bloating and bloating[0]["title"] == "饭后腹胀人群使用反馈",
            f"腹胀 search mismatch: {bloating}",
        )

        probiotic = search_case_documents("益生菌有没有客户案例", limit=5)
        assert_true(any("益生菌" in item["product_tags"] for item in probiotic), f"益生菌 search mismatch: {probiotic}")

        hidden_id = create_case_document({
            "title": "隐藏便秘案例",
            "customer_profile": "测试客户",
            "symptom_tags": "便秘",
            "product_tags": "益生菌",
            "summary": "这条隐藏后不应推荐",
            "content": "隐藏测试",
            "status": 1,
        })
        set_case_document_status(hidden_id, 0)
        hidden_results = search_case_documents("隐藏便秘案例", limit=5)
        assert_true(all(item["id"] != hidden_id for item in hidden_results), f"hidden case leaked: {hidden_results}")

        client = app.test_client()
        with patch("services.chat_service.requests.post", side_effect=fake_post):
            r = client.post("/api/chat/send", json={
                "message": "我妈便秘腹胀适合什么",
                "query_type": "产品咨询",
                "user_id": "case-test-user",
            })
        assert_true(r.status_code == 200, f"chat send failed: {r.status_code} {r.get_data(as_text=True)}")
        payload = r.get_json()
        related = payload.get("related_cases", [])
        assert_true(related, f"chat related_cases missing: {payload}")
        assert_true(
            payload.get("related_cases_total", 0) >= len(related),
            f"chat related_cases_total mismatch: {payload}",
        )
        assert_true(
            related[0]["title"] == "长期便秘客户调理记录",
            f"chat related_cases mismatch: {related}",
        )

        r = client.get(f"/api/cases/{related[0]['id']}")
        assert_true(r.status_code == 200, f"public case detail failed: {r.status_code}")
        assert_true(r.get_json()["title"] == "长期便秘客户调理记录", "public case detail mismatch")

        r = client.get("/api/cases?tag_type=symptom&tag=便秘")
        assert_true(r.status_code == 200, f"public case list failed: {r.status_code}")
        symptom_items = r.get_json().get("items", [])
        assert_true(symptom_items and all("便秘" in item["symptom_tags"] for item in symptom_items), f"symptom tag filter failed: {symptom_items}")

        r = client.get("/api/cases?tag_type=product&tag=益生菌")
        assert_true(r.status_code == 200, f"public product list failed: {r.status_code}")
        product_items = r.get_json().get("items", [])
        assert_true(product_items and all("益生菌" in item["product_tags"] for item in product_items), f"product tag filter failed: {product_items}")

        r = client.get("/api/cases/search?q=我妈便秘腹胀适合什么&page=1&limit=10")
        assert_true(r.status_code == 200, f"public case search failed: {r.status_code}")
        search_payload = r.get_json()
        search_items = search_payload.get("items", [])
        assert_true(search_items and search_items[0]["title"] == "长期便秘客户调理记录", f"case search mismatch: {search_payload}")
        assert_true(search_payload.get("total", 0) >= len(search_items), f"case search total mismatch: {search_payload}")

        r = client.post("/api/auth/register", json={"username": "admin8", "password": "pass123"})
        assert_true(r.status_code in (201, 409), f"admin register failed: {r.status_code}")
        r = client.post("/api/auth/login", json={"username": "admin8", "password": "pass123"})
        assert_true(r.status_code == 200, f"admin login failed: {r.status_code}")
        auth = {"Authorization": f"Bearer {r.get_json()['token']}"}

        r = client.get("/api/admin/cases", headers=auth)
        assert_true(r.status_code == 200, f"admin cases list failed: {r.status_code}")
        assert_true(len(r.get_json().get("cases", [])) >= 5, "admin cases list missing seeds")

        r = client.get("/api/admin/settings/case-library-url")
        assert_true(r.status_code == 401, f"case library setting should require auth: {r.status_code}")

        r = client.put("/api/admin/settings/case-library-url", headers=auth, json={"case_library_url": "ftp://example.com/cases"})
        assert_true(r.status_code == 400, f"invalid case library url should fail: {r.status_code}")

        r = client.put("/api/admin/settings/case-library-url", headers=auth, json={"case_library_url": "https://example.com/cases"})
        assert_true(r.status_code == 200, f"case library url save failed: {r.status_code}")
        assert_true(r.get_json().get("case_library_url") == "https://example.com/cases", "case library save mismatch")
        r = client.get("/api/case-library-config")
        assert_true(r.status_code == 200, f"public case library config failed: {r.status_code}")
        assert_true(r.get_json().get("case_library_url") == "https://example.com/cases", "public case library config mismatch")

        r = client.put("/api/admin/settings/case-library-url", headers=auth, json={"case_library_url": ""})
        assert_true(r.status_code == 200, f"case library url clear failed: {r.status_code}")
        r = client.get("/api/case-library-config")
        assert_true(r.get_json().get("case_library_url") == "", "case library clear mismatch")

        r = client.post("/api/admin/cases/recognize-link", json={"url": "https://example.com/case"})
        assert_true(r.status_code == 401, f"recognize should require admin auth: {r.status_code}")

        r = client.post("/api/admin/cases/recognize-link", headers=auth, json={"url": "ftp://example.com/case"})
        assert_true(r.status_code == 400, f"non-http recognize should fail: {r.status_code}")

        r = client.post("/api/admin/cases/recognize-link", headers=auth, json={"url": "http://127.0.0.1:5001/private"})
        assert_true(r.status_code == 400, f"private recognize should fail: {r.status_code}")

        before_recognize_count = len(get_all_case_documents())
        with patch("services.case_recognition_service.socket.getaddrinfo", side_effect=fake_public_dns), \
             patch("services.case_recognition_service.requests.Session", return_value=FakeHtmlSession()), \
             patch("services.case_recognition_service.requests.post", return_value=FakeRecognizeAiResponse()):
            r = client.post("/api/admin/cases/recognize-link", headers=auth, json={"url": "https://example.com/case"})
        assert_true(r.status_code == 200, f"recognize failed: {r.status_code} {r.get_data(as_text=True)}")
        recognized = r.get_json()
        fields = recognized.get("fields", {})
        assert_true(fields.get("title") == "链接识别便秘案例", f"ai title mismatch: {fields}")
        assert_true("便秘" in fields.get("symptom_tags", ""), f"ai symptom tags missing: {fields}")
        assert_true("益生菌" in fields.get("product_tags", ""), f"ai product tags missing: {fields}")
        assert_true("external_url" not in fields, f"recognize should not create per-case external_url: {fields}")
        assert_true(len(get_all_case_documents()) == before_recognize_count, "recognize should not insert cases")

        with patch("services.case_recognition_service.socket.getaddrinfo", side_effect=fake_public_dns), \
             patch("services.case_recognition_service.requests.Session", return_value=FakeHtmlSession()), \
             patch("services.case_recognition_service.requests.post", side_effect=Exception("ai down")):
            r = client.post("/api/admin/cases/recognize-link", headers=auth, json={"url": "https://example.com/fallback"})
        assert_true(r.status_code == 200, f"fallback recognize failed: {r.status_code}")
        fallback = r.get_json()
        assert_true(fallback["fields"]["title"] == "网页原始便秘案例", f"fallback title mismatch: {fallback}")
        assert_true(fallback["fields"]["summary"], f"fallback summary missing: {fallback}")
        assert_true(fallback.get("warnings"), f"fallback warning missing: {fallback}")

        r = client.post("/api/admin/cases", headers=auth, json=fields)
        assert_true(r.status_code == 201, f"recognized case create failed: {r.status_code} {r.get_data(as_text=True)}")
        recognized_case_id = r.get_json()["id"]
        assert_true(
            search_case_documents("链接识别便秘益生菌", limit=3)[0]["id"] == recognized_case_id,
            "recognized saved case not searchable",
        )
        r = client.delete(f"/api/admin/cases/{recognized_case_id}", headers=auth)
        assert_true(r.status_code == 200, f"recognized case cleanup failed: {r.status_code}")

        r = client.post("/api/admin/cases", headers=auth, json={
            "title": "测试睡眠案例",
            "customer_profile": "测试客户",
            "symptom_tags": "睡眠差",
            "product_tags": "营养组合",
            "summary": "测试摘要",
            "content": "测试正文",
            "status": 1,
        })
        assert_true(r.status_code == 201, f"admin case create failed: {r.status_code} {r.get_data(as_text=True)}")
        admin_case_id = r.get_json()["id"]

        r = client.put(f"/api/admin/cases/{admin_case_id}", headers=auth, json={
            "title": "测试睡眠案例已编辑",
            "customer_profile": "测试客户",
            "symptom_tags": "睡眠差,疲劳",
            "product_tags": "营养组合",
            "summary": "测试摘要已编辑",
            "content": "测试正文",
            "status": 1,
        })
        assert_true(r.status_code == 200, f"admin case update failed: {r.status_code}")
        assert_true(
            search_case_documents("睡眠差疲劳", limit=3)[0]["title"] == "测试睡眠案例已编辑",
            "updated case not searchable",
        )

        r = client.put(f"/api/admin/cases/{admin_case_id}/status", headers=auth, json={"status": 0})
        assert_true(r.status_code == 200, f"admin case status failed: {r.status_code}")
        assert_true(
            all(item["id"] != admin_case_id for item in search_case_documents("睡眠差疲劳", limit=5)),
            "hidden admin case leaked",
        )

        r = client.delete(f"/api/admin/cases/{admin_case_id}", headers=auth)
        assert_true(r.status_code == 200, f"admin case delete failed: {r.status_code}")

        print("PASS: case documents smoke test")


if __name__ == "__main__":
    main()
