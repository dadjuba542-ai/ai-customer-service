#!/usr/bin/env python3
import os
import tempfile
import sys
from pathlib import Path

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
        from models import create_question, save_chat_history

        client = app.test_client()

        # Create and login admin user.
        r = client.post("/api/auth/register", json={"username": "admin8", "password": "pass123"})
        assert_true(r.status_code in (201, 409), f"register failed: {r.status_code} {r.get_data(as_text=True)}")
        r = client.post("/api/auth/login", json={"username": "admin8", "password": "pass123"})
        assert_true(r.status_code == 200, f"login failed: {r.status_code} {r.get_data(as_text=True)}")
        token = r.get_json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

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

        print("PASS: today features smoke test")


if __name__ == "__main__":
    main()
