"""入口：`PYTHONPATH=. python -m colab.worker`（仓库根目录）。"""
from .agent import Agent
from .config import Config


def main():
    cfg = Config.from_env()
    if not cfg.token:
        print("[worker] 警告：未设 WORKER_TOKEN（后端若设了 token 会全部 401）")
    agent = Agent(cfg)
    try:
        agent.run()
    except KeyboardInterrupt:
        print("\n[worker] 退出")
    finally:
        agent.shutdown()


if __name__ == "__main__":
    main()
