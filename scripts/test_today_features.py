#!/usr/bin/env python3
import os
import tempfile
import sys
import base64
import hashlib
import hmac
from urllib.parse import unquote
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix="acs-test-") as tmpdir:
        os.environ["DATABASE_DIR"] = tmpdir
        os.environ["SECRET_KEY"] = "test-secret-key-32-bytes-minimum!!"
        os.environ["ADMIN_USERNAME"] = "admin8"

        from app import app
        from routes.auth import generate_token, hash_password
        from models import create_question, create_user, save_chat_history

        client = app.test_client()

        # Create an admin directly; public registration is intentionally disabled by default.
        admin_id = create_user("test-admin", hash_password("pass123456"), is_admin=1)
        auth = {"Authorization": f"Bearer {generate_token(admin_id)}"}

        # 1) PUT default-team with empty/non-json body should not 500.
        r = client.put("/api/admin/settings/default-team", headers=auth)
        assert_true(r.status_code != 500, "default-team PUT returned 500 on empty body")

        # 2) Save team list and read back.
        r = client.put(
            "/api/admin/settings/default-team",
            headers=auth,
            json={"team_names": ["一团队", "二团队"]},
        )
        assert_true(r.status_code == 200, f"default-team save failed: {r.status_code}")
        r = client.get("/api/default-team")
        teams = r.get_json().get("team_names", [])
        assert_true(teams == ["一团队", "二团队"], f"default-team read mismatch: {teams}")

        # Insert sample chat records for stats query.
        save_chat_history("u1", "产品咨询", "问题A", "答复", team_name="一团队", member_name="张三")
        save_chat_history("u1", "产品咨询", "问题A", "答复", team_name="一团队", member_name="张三")
        save_chat_history("u2", "产品咨询", "问题B", "答复", team_name="二团队", member_name="李%四")

        # 3) Team filter works.
        r = client.get("/api/admin/dashboard/team-question-stats?team_name=一团队", headers=auth)
        items = r.get_json().get("items", [])
        assert_true(len(items) == 1 and items[0]["team_name"] == "一团队", f"team filter failed: {items}")

        # 4) Member literal wildcard query should not match everything.
        r = client.get("/api/admin/dashboard/team-question-stats?member_name=%25", headers=auth)
        items = r.get_json().get("items", [])
        assert_true(
            len(items) == 1 and items[0]["member_name"] == "李%四",
            f"member wildcard escaping failed: {items}",
        )

        # 5) Admin Q&A list should include all statuses; public list only visible questions.
        visible_id = create_question("", "公开问答", "公开回答", "产品知识", 1)
        hidden_id = create_question("", "隐藏问答", "隐藏回答", "产品知识", 0)
        r = client.get("/api/community/admin/questions?page=1&limit=50", headers=auth)
        assert_true(r.status_code == 200, f"admin question list failed: {r.status_code}")
        admin_ids = {item["id"] for item in r.get_json().get("items", [])}
        assert_true(visible_id in admin_ids and hidden_id in admin_ids, f"admin question list missing items: {admin_ids}")

        r = client.get("/api/community/questions?page=1&limit=50")
        public_ids = {item["id"] for item in r.get_json().get("items", [])}
        assert_true(visible_id in public_ids and hidden_id not in public_ids, f"public question visibility failed: {public_ids}")

        # 6) New replies stay pending: visible only to the author until admin approves.
        qid = create_question("", "评论精选测试", "评论精选测试答案", "产品知识", 1)
        r = client.post(
            f"/api/community/questions/{qid}/replies",
            headers=auth,
            json={"nickname": "张三", "content": "这是一条待精选评论", "viewer_id": "viewer-a"},
        )
        assert_true(r.status_code == 201, f"reply create failed: {r.status_code} {r.get_data(as_text=True)}")
        reply = r.get_json()
        reply_id = reply["id"]
        assert_true(reply.get("status") == 0, f"new reply should be pending: {reply}")

        r = client.get(f"/api/community/questions/{qid}")
        q = r.get_json()
        assert_true(not q.get("replies"), f"pending reply leaked publicly: {q.get('replies')}")
        assert_true(q.get("reply_count") == 0, f"public count should ignore pending replies: {q.get('reply_count')}")

        r = client.get(f"/api/community/questions/{qid}", headers=auth)
        own_replies = r.get_json().get("replies", [])
        assert_true(
            len(own_replies) == 1 and own_replies[0]["id"] == reply_id and own_replies[0].get("is_own_pending"),
            f"author cannot see pending reply: {own_replies}",
        )
        assert_true(own_replies[0].get("nickname") == "匿名用户", f"reply nickname should be masked: {own_replies}")

        r = client.get(f"/api/community/questions/{qid}?viewer_id=viewer-b")
        assert_true(not r.get_json().get("replies"), "another viewer should not see pending reply")

        r = client.put(f"/api/community/admin/replies/{reply_id}/status", headers=auth, json={"status": 1})
        assert_true(r.status_code == 200, f"reply approve failed: {r.status_code} {r.get_data(as_text=True)}")
        r = client.get(f"/api/community/questions/{qid}")
        q = r.get_json()
        approved = q.get("replies", [])
        assert_true(len(approved) == 1 and approved[0]["id"] == reply_id, f"approved reply missing: {approved}")
        assert_true(approved[0].get("nickname") == "匿名用户", f"approved reply nickname should be masked: {approved}")
        assert_true(q.get("reply_count") == 1, f"approved count should be public: {q.get('reply_count')}")
        r = client.get("/api/community/admin/questions?page=1&limit=50", headers=auth)
        admin_item = next(item for item in r.get_json().get("items", []) if item["id"] == qid)
        assert_true(admin_item.get("reply_count") == 1, f"admin approved count mismatch: {admin_item}")
        assert_true(admin_item.get("pending_reply_count") == 0, f"admin pending count mismatch: {admin_item}")
        assert_true(admin_item["replies"][0].get("nickname") == "匿名用户", f"admin reply nickname should be masked: {admin_item}")

        # 7) Replies can be liked and expose their like count.
        r = client.post(f"/api/community/replies/{reply_id}/like", headers=auth)
        assert_true(r.status_code == 200, f"reply like failed: {r.status_code} {r.get_data(as_text=True)}")
        liked = r.get_json()
        assert_true(liked.get("like_count") == 1, f"reply like count mismatch: {liked}")
        r = client.get(f"/api/community/questions/{qid}")
        approved = r.get_json().get("replies", [])
        assert_true(approved[0].get("like_count") == 1, f"reply like count missing in detail: {approved}")

        # 8) Share event endpoint records answer-card generation without auth.
        r = client.post(
            "/api/share-events",
            headers=auth,
            json={
                "user_id": "u-share",
                "team_name": "一团队",
                "member_name": "张三",
                "query_type": "产品咨询",
                "history_id": None,
                "share_type": "answer_card",
            },
        )
        assert_true(r.status_code == 201, f"share event failed: {r.status_code} {r.get_data(as_text=True)}")
        assert_true(r.get_json().get("id"), f"share event id missing: {r.get_json()}")

        # 9) Speech settings gate frontend voice input and transcribe endpoint.
        r = client.get("/api/speech/config")
        assert_true(r.status_code == 200 and r.get_json().get("enabled") is False, f"speech should default off: {r.get_json()}")
        r = client.put("/api/admin/settings/speech", headers=auth, json={"enabled": True})
        assert_true(r.status_code == 400, f"speech enabled without tencent config should fail: {r.status_code}")
        r = client.put(
            "/api/admin/settings/speech",
            headers=auth,
            json={
                "enabled": True,
                "mode": "auto",
                "tencent_app_id": "1234567890",
                "tencent_secret_id": "tencent-secret-id",
                "tencent_secret_key": "tencent-secret-key",
            },
        )
        assert_true(r.status_code == 200, f"speech settings save failed: {r.status_code} {r.get_data(as_text=True)}")
        settings = r.get_json()
        assert_true(settings.get("provider") == "tencent_asr", f"speech provider mismatch: {settings}")
        assert_true(settings.get("tencent_secret_key_masked"), f"speech secret should be masked: {settings}")
        r = client.get("/api/speech/config")
        public_speech = r.get_json()
        assert_true(public_speech.get("enabled") is True, f"speech public config not enabled: {public_speech}")
        assert_true(public_speech.get("realtime_enabled") is True, f"speech realtime config not ready: {public_speech}")

        r = client.post("/api/speech/realtime/session", headers=auth, json={"user_id": "u-speech"})
        assert_true(r.status_code == 200, f"realtime speech session failed: {r.status_code} {r.get_data(as_text=True)}")
        realtime = r.get_json()
        signed_url = realtime.get("url", "")
        assert_true(signed_url.startswith("wss://asr.cloud.tencent.com/asr/v2/1234567890?"), f"realtime url mismatch: {signed_url}")
        assert_true("tencent-secret-key" not in signed_url and "signature=" in signed_url, "secret leaked or signature missing")
        sign_source, signature = signed_url.removeprefix("wss://").rsplit("&signature=", 1)
        expected_signature = base64.b64encode(
            hmac.new(b"tencent-secret-key", sign_source.encode("utf-8"), hashlib.sha1).digest()
        ).decode("ascii")
        assert_true(unquote(signature) == expected_signature, "realtime websocket signature mismatch")
        page = client.get("/")
        csp = page.headers.get("Content-Security-Policy", "")
        assert_true("wss://asr.cloud.tencent.com" in csp, f"tencent realtime websocket blocked by CSP: {csp}")

        r = client.post("/api/speech/transcribe", headers=auth, data={"user_id": "u-speech"})
        assert_true(r.status_code == 400, f"speech missing audio should 400: {r.status_code} {r.get_data(as_text=True)}")
        oversized = BytesIO(b"x" * (10 * 1024 * 1024 + 1))
        r = client.post(
            "/api/speech/transcribe",
            headers=auth,
            data={"audio": (oversized, "voice.webm", "audio/webm"), "user_id": "u-speech"},
        )
        assert_true(r.status_code == 400, f"speech oversized audio should 400: {r.status_code} {r.get_data(as_text=True)}")
        with patch("services.speech_service._convert_audio_to_wav", return_value=b"wav-bytes") as convert_mock, \
             patch("services.speech_service._tencent_api_request", return_value={"Result": "这是语音识别结果"}) as asr_mock:
            r = client.post(
                "/api/speech/transcribe",
                headers=auth,
                data={"audio": (BytesIO(b"voice-bytes"), "voice.mp4", "audio/mp4"), "user_id": "u-speech"},
            )
        assert_true(r.status_code == 200, f"speech transcribe failed: {r.status_code} {r.get_data(as_text=True)}")
        assert_true(r.get_json().get("text") == "这是语音识别结果", f"speech text mismatch: {r.get_json()}")
        assert_true(r.get_json().get("provider") == "tencent_asr", f"speech provider mismatch: {r.get_json()}")
        assert_true(convert_mock.called, "speech audio should be converted to wav")
        asr_mock.assert_called_once()
        action, payload, secret_id, secret_key = asr_mock.call_args.args
        assert_true(action == "SentenceRecognition", f"tencent action mismatch: {action}")
        assert_true(secret_id == "tencent-secret-id" and secret_key == "tencent-secret-key", "tencent credentials mismatch")
        assert_true(base64.b64decode(payload.get("Data", "")) == b"wav-bytes", "tencent asr should receive wav bytes")

        print("PASS: today features smoke test")


if __name__ == "__main__":
    main()
