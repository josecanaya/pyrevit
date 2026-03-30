# -*- coding: utf-8 -*-
"""
Worker externo (Python 3) para ejecutar agrupacion OpenAI fuera de IronPython.
"""
from __future__ import print_function

import argparse
import json
import os
import sys


def _u(value):
    try:
        return str(value)
    except Exception:
        return ""


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)


def _self_check():
    try:
        import openai  # noqa: F401
    except Exception as ex:
        print("openai import failed: {0}".format(_u(ex)))
        return 2
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("OPENAI_API_KEY missing")
        return 3
    print("ok")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    if args.self_check:
        return _self_check()

    if not args.input or not os.path.isfile(args.input):
        print("input file missing")
        return 4
    if not args.output:
        print("output path missing")
        return 5

    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    try:
        from btz_openai_grouping import analyze_grouping_with_openai
    except Exception as ex:
        print("import btz_openai_grouping failed: {0}".format(_u(ex)))
        return 6

    with open(args.input, "r", encoding="utf-8-sig") as fp:
        scenario = json.load(fp)

    logs = []
    try:
        ai_result = analyze_grouping_with_openai(
            scenario,
            client=None,
            model=_u(args.model),
            timeout_sec=float(args.timeout or 60.0),
            log_lines=logs,
        )
        out = {
            "ok": True,
            "ai_result": ai_result,
            "logs": logs,
            "model": _u(args.model),
        }
        _write_json(args.output, out)
        print("ok")
        return 0
    except Exception as ex:
        out = {
            "ok": False,
            "error": _u(ex),
            "logs": logs,
            "model": _u(args.model),
        }
        try:
            _write_json(args.output, out)
        except Exception:
            pass
        print("worker error: {0}".format(_u(ex)))
        return 7


if __name__ == "__main__":
    sys.exit(main())
