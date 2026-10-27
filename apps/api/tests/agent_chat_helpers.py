"""Bounded public Turn polling; never resend consent while waiting."""
import time


def post_chat_turn(v, conversation_id, content):
    response = v["client"].post(f"/v1/conversations/{conversation_id}/messages",
        headers=v["headers"], json={"content": content})
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["conversation_id"] == conversation_id
    path = f"/v1/conversations/{conversation_id}/turns/{accepted['turn_id']}"
    for _ in range(200):
        response = v["client"].get(path, headers=v["headers"])
        assert response.status_code == 200, response.text
        turn = response.json()
        if turn["status"] in {"completed", "failed", "interrupted"}:
            return turn
        time.sleep(0.05)
    raise AssertionError(f"Turn did not reach a terminal state: {turn['status']}")
