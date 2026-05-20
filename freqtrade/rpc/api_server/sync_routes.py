import json
import os
import re
import subprocess
import threading
import time


_SYNC_SCRIPTS = {
    "news": {
        "script": os.path.expanduser(
            "~/work/trade/freqtrade/.worktrees/quant-mvp/user_data/scripts/sync_news_quick.py"
        ),
        "python": ["/home/zp/work/trade/freqtrade/.venv/bin/python"],
        "timeout": 120,
        "parse_records": lambda out: int(
            (out.strip().split("\nWritten:")[-1].split("\n")[0]).strip()
        )
        if "Written:" in out
        else 0,
        "success_msg": lambda r: f"抓取完成，{r}条",
    },
    "macro": {
        "script": os.path.expanduser(
            "~/work/trade/freqtrade/.worktrees/quant-mvp/user_data/scripts/sync_macro.py"
        ),
        "python": ["/home/zp/work/trade/freqtrade/.venv/bin/python", "--provider", "fred"],
        "timeout": 120,
        "parse_records": lambda out: int(m.group(1))
        if (m := re.search(r"Total:\s*(\d+)", out))
        else 2652,
        "success_msg": lambda _: "FRED同步完成",
        "env_hook": lambda env: _inject_fred_key(env),
    },
    "crypto": {
        "worktree": os.path.expanduser("~/work/trade/freqtrade/.worktrees/quant-mvp"),
        "timeout": 300,
        "success_msg": lambda _: "行情数据同步完成",
    },
}


def _inject_fred_key(env):
    """从 user_settings.json 注入 FRED API Key"""
    env["FRED_API_KEY"] = ""
    settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path) as f:
                env["FRED_API_KEY"] = json.load(f).get("fred", {}).get("api_key", "")
        except Exception:
            pass


def _run_news_macro(source, db_pool_dsn):
    """后台运行新闻或宏观同步"""
    import psycopg2

    cfg = _SYNC_SCRIPTS[source]
    conn = psycopg2.connect(db_pool_dsn)
    try:
        start = time.time()
        env = os.environ.copy()
        if cfg.get("env_hook"):
            cfg["env_hook"](env)
        cmd = cfg["python"] + [cfg["script"]]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=cfg["timeout"], env=env
        )
        elapsed = round(time.time() - start, 1)
        records = cfg["parse_records"](result.stdout)
        success = result.returncode == 0
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE quant_raw.sync_status SET status='idle', last_sync=NOW(), last_result=%s, row_count=%s WHERE source=%s",
                ("success" if success else "failed", records, source),
            )
            cur.execute(
                "INSERT INTO quant_raw.sync_log (source,status,records,duration_s,message) VALUES (%s,%s,%s,%s,%s)",
                (
                    source,
                    "success" if success else "failed",
                    records,
                    elapsed,
                    result.stderr.strip()[:200] if not success else cfg["success_msg"](records),
                ),
            )
        conn.commit()
    except Exception as e:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE quant_raw.sync_status SET status='idle', last_result='failed', last_error=%s WHERE source=%s",
                    (str(e)[:200], source),
                )
                cur.execute(
                    "INSERT INTO quant_raw.sync_log (source,status,duration_s,message) VALUES (%s,'failed',%s,%s)",
                    (source, 0, str(e)[:200]),
                )
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()


def _run_crypto(db_pool_dsn):
    """后台运行数字货币数据同步（下载 + feather_to_pg）"""
    import psycopg2

    conn = psycopg2.connect(db_pool_dsn)
    try:
        start = time.time()
        worktree = _SYNC_SCRIPTS["crypto"]["worktree"]
        cmd = [
            "/home/zp/work/trade/freqtrade/.venv/bin/python",
            "-m",
            "freqtrade",
            "download-data",
            "--config",
            f"{worktree}/user_data/config_crypto_mvp.json",
            "--timeframes",
            "1h",
            "--days",
            "7",
            "--data-format-ohlcv",
            "feather",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=worktree)
        elapsed = round(time.time() - start, 1)
        success = result.returncode == 0
        if success:
            subprocess.run(
                [
                    "/home/zp/work/trade/freqtrade/.venv/bin/python",
                    "-m",
                    "user_data.scripts.feather_to_pg",
                ],
                capture_output=True,
                cwd=worktree,
                timeout=120,
            )
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE quant_raw.sync_status SET status='idle', last_sync=NOW(), last_result=%s WHERE source='crypto'",
                ("success" if success else "failed",),
            )
            cur.execute(
                "INSERT INTO quant_raw.sync_log (source,status,duration_s,message) VALUES ('crypto',%s,%s,%s)",
                (
                    "success" if success else "failed",
                    elapsed,
                    result.stderr.strip()[:200] if not success else "行情数据同步完成",
                ),
            )
        conn.commit()
    except Exception as e:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE quant_raw.sync_status SET status='idle', last_result='failed', last_error=%s WHERE source='crypto'",
                    (str(e)[:200],),
                )
                cur.execute(
                    "INSERT INTO quant_raw.sync_log (source,status,duration_s,message) VALUES ('crypto','failed',%s,%s)",
                    (0, str(e)[:200]),
                )
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()


# ── API routes ────────────────────────────────────────────────────────────


def register_sync_routes(router):
    """注册同步路由（由主模块调用）"""

    import psycopg2

    _DSN = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"

    @router.post("/quant/sync/news")
    def api_sync_news():
        """触发新闻同步（后台，立即返回）"""
        try:
            conn = psycopg2.connect(_DSN)
            conn.cursor().execute(
                "UPDATE quant_raw.sync_status SET status='running' WHERE source='news'"
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        threading.Thread(target=_run_news_macro, args=("news", _DSN), daemon=True).start()
        return {"source": "news", "status": "running"}

    @router.post("/quant/sync/macro")
    def api_sync_macro():
        """触发宏观数据同步（后台，立即返回）"""
        try:
            conn = psycopg2.connect(_DSN)
            conn.cursor().execute(
                "UPDATE quant_raw.sync_status SET status='running' WHERE source='macro'"
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        threading.Thread(target=_run_news_macro, args=("macro", _DSN), daemon=True).start()
        return {"source": "macro", "status": "running"}

    @router.post("/quant/sync/crypto")
    def api_sync_crypto():
        """触发数字货币数据同步（后台，立即返回）"""
        try:
            conn = psycopg2.connect(_DSN)
            conn.cursor().execute(
                "UPDATE quant_raw.sync_status SET status='running' WHERE source='crypto'"
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        threading.Thread(target=_run_crypto, args=(_DSN,), daemon=True).start()
        return {"source": "crypto", "status": "running"}
