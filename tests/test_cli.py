import json

from cyberbody import cli, ipc


def test_status_prints_response_from_running_instance(monkeypatch, capsys):
    monkeypatch.setattr(
        ipc,
        "send_command",
        lambda command, payload: {"ok": True, "state": "idle", "command": command},
    )

    assert cli.main(["status"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "idle"
    assert output["command"] == "status"


def test_run_forwards_task_to_existing_instance(monkeypatch):
    received = {}

    def send(command, payload):
        received.update(command=command, payload=payload)
        return {"ok": True}

    monkeypatch.setattr(ipc, "send_command", send)

    assert cli.main(["run", "--task", "打开项目"]) == 0
    assert received == {"command": "run", "payload": {"task": "打开项目"}}


def test_status_reports_when_no_instance_is_running(monkeypatch, capsys):
    released = []
    monkeypatch.setattr(ipc, "send_command", lambda _command, _payload: None)
    monkeypatch.setattr(ipc, "acquire_instance_mutex", lambda: True)
    monkeypatch.setattr(ipc, "release_instance_mutex", lambda: released.append(True))

    assert cli.main(["status"]) == 1
    assert "当前未运行" in capsys.readouterr().out
    assert released == [True]


def test_status_waits_for_process_that_is_still_starting(monkeypatch, capsys):
    monkeypatch.setattr(ipc, "send_command", lambda _command, _payload: None)
    monkeypatch.setattr(ipc, "acquire_instance_mutex", lambda: False)
    monkeypatch.setattr(
        ipc,
        "wait_for_existing",
        lambda command, payload: {"ok": True, "state": "planning", "command": command},
    )

    assert cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "planning"


def test_failed_running_instance_command_returns_nonzero(monkeypatch):
    monkeypatch.setattr(
        ipc,
        "send_command",
        lambda _command, _payload: {"ok": False, "error": "invalid"},
    )

    assert cli.main(["stop"]) == 1


def test_server_name_is_stable_and_does_not_expose_user(monkeypatch):
    monkeypatch.setattr(ipc.getpass, "getuser", lambda: "private-user")

    first = ipc.server_name()

    assert first == ipc.server_name()
    assert first.startswith("cyberbody-")
    assert "private-user" not in first
