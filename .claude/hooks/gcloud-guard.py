"""Claude Code の PreToolUse フック。gcloud に --project loadline-app が無ければ止める。

この Mac の gcloud の既定は別プロジェクトを指している。付け忘れは人の注意では防げないので、
Bash を実行する前に機械で止める。終了コード 2 が「止める」の合図で、stderr が Claude に返る。
"""

import json
import re
import sys

PROJECT = "loadline-app"
# && || ; | で区切って、1 つずつ見る
SPLIT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
GCLOUD = re.compile(r"(?:^|\s)gcloud(?:\s|$)")
WITH_PROJECT = re.compile(rf"--project[= ]{PROJECT}(?:\s|$)")


def main() -> None:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    for part in SPLIT.split(command):
        if GCLOUD.search(part) and not WITH_PROJECT.search(part):
            print(f"gcloud には --project {PROJECT} を付ける: {part}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
