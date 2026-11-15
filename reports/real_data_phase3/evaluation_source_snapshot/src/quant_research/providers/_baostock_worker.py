"""Private subprocess worker. Parent enforces a hard process deadline."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import socket
import sys
import time

# Invoked by file path so an installed editable package is not a prerequisite.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quant_research.providers.baostock import Query, SDK_VERSION, HISTORY_FIELDS, NETWORK_CODES, canonical


def fetch(config):
    query = Query(**config["query"])
    query.validate()
    logs = io.StringIO()
    result = {"status": "FAILED", "retryable": False, "fields": [], "rows": []}
    sdk = None
    logged_in = False
    with redirect_stdout(logs), redirect_stderr(logs):
        try:
            if config.get("sdk_path"):
                sys.path.insert(0, config["sdk_path"])
            version = importlib.metadata.version("baostock")
            if version != SDK_VERSION:
                raise RuntimeError("Optional baostock==0.9.4 required, found " + version)
            import baostock as sdk
            sdk_dir = Path(sdk.__file__).resolve().parent
            hashes = {path.relative_to(sdk_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in sorted(sdk_dir.rglob("*.py"))}
            result.update(sdk_version=version, sdk_source_sha256=hashlib.sha256(canonical(hashes)).hexdigest())
            socket.setdefaulttimeout(config["socket_timeout"])
            login = sdk.login()
            result["login"] = {"error_code": login.error_code, "error_msg": login.error_msg}
            if login.error_code != "0":
                result.update(error_code=login.error_code, error_msg=login.error_msg, retryable=login.error_code in NETWORK_CODES)
                return result
            logged_in = True
            time.sleep(config["min_interval"])
            if query.kind == "history":
                response = sdk.query_history_k_data_plus(query.code, HISTORY_FIELDS, start_date=query.start,
                                                        end_date=query.end, frequency="d", adjustflag="3")
            elif query.kind == "calendar":
                response = sdk.query_trade_dates(start_date=query.start, end_date=query.end)
            elif query.kind == "universe":
                response = sdk.query_daily_history_k_ETF(date=query.date)
            else:
                response = sdk.query_stock_basic(code=query.code)
            result.update(error_code=response.error_code, error_msg=response.error_msg, fields=list(response.fields))
            if response.error_code != "0":
                result["retryable"] = response.error_code in NETWORK_CODES
                return result
            # SDK pagination errors can leave the original success flag intact.
            # This bounded sample rejects a full-page boundary if no positive
            # next-page transition can be established, rather than silently
            # admitting a truncated history.
            while True:
                prior_page = response.cur_page_num
                boundary = len(response.data) == int(response.per_page_count) and response.cur_row_num >= len(response.data)
                more = response.next()
                if not more:
                    if boundary and response.cur_page_num == prior_page and response.error_code == "0":
                        raise RuntimeError("Ambiguous pagination termination; possible truncated response")
                    break
                result["rows"].append(response.get_row_data())
                if len(result["rows"]) > 100_000:
                    raise RuntimeError("Sample row limit exceeded")
            result.update(error_code=response.error_code, error_msg=response.error_msg,
                          status="SUCCESS" if response.error_code == "0" else "FAILED",
                          retryable=response.error_code in NETWORK_CODES)
        except Exception as exc:
            result.update(status="FAILED", error_type=type(exc).__name__, error=str(exc),
                          retryable=isinstance(exc, (TimeoutError, ConnectionError, OSError)))
        finally:
            if sdk is not None and logged_in:
                try:
                    time.sleep(config["min_interval"])
                    logout = sdk.logout()
                    result["logout"] = {"error_code": logout.error_code, "error_msg": logout.error_msg}
                except Exception as exc:
                    result["logout"] = {"error_type": type(exc).__name__, "error": str(exc)}
            result["sdk_diagnostics"] = logs.getvalue()[-8000:]
    return result


if __name__ == "__main__":
    try:
        answer = fetch(json.load(sys.stdin))
    except Exception as exc:
        answer = {"status": "FAILED", "retryable": False, "error_type": type(exc).__name__,
                  "error": str(exc), "fields": [], "rows": []}
    sys.stdout.buffer.write(canonical(answer))
