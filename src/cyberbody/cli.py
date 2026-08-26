from __future__ import annotations

import argparse
import json
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cyberbody",
        description="自然语言驱动的 Windows 可视化操作智能体",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("start", help="启动或显示监管面板")
    run_parser = subparsers.add_parser("run", help="启动并预填一条自然语言任务")
    run_parser.add_argument("--task", required=True, help="自然语言任务")
    subparsers.add_parser("status", help="查看正在运行的 cyberbody 状态")
    subparsers.add_parser("stop", help="紧急停止并关闭 cyberbody")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "start"

    try:
        from .ipc import (
            acquire_instance_mutex,
            release_instance_mutex,
            send_command,
            wait_for_existing,
        )
    except ImportError as exc:
        print(f"cyberbody 依赖未安装：{exc}", file=sys.stderr)
        return 2

    payload = {"task": args.task} if command == "run" else None
    response = send_command(command, payload)
    if response is not None:
        if command in {"status", "stop"}:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0 if response.get("ok", False) else 1

    if command in {"status", "stop"}:
        if not acquire_instance_mutex():
            response = wait_for_existing(command, payload)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False, indent=2))
                return 0 if response.get("ok", False) else 1
            print("cyberbody 进程存在，但控制通道没有响应。", file=sys.stderr)
            return 1
        release_instance_mutex()
        print("cyberbody 当前未运行。")
        return 1

    if not acquire_instance_mutex():
        response = wait_for_existing(command, payload)
        if response is None:
            print("cyberbody 正在启动，但本地控制通道尚未就绪。", file=sys.stderr)
            return 1
        return 0 if response.get("ok", False) else 1

    from .ui import run_gui

    try:
        return run_gui(getattr(args, "task", ""))
    finally:
        release_instance_mutex()


if __name__ == "__main__":
    raise SystemExit(main())
