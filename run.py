"""Web GUI（webapp/）の本番相当・単一プロセス起動スクリプト。

事前に `cd webapp/frontend && npm install && npm run build` を実行して
webapp/frontend/dist を生成しておくと、このプロセス1つでAPIとGUIの
両方を http://127.0.0.1:8000 で提供できる（webapp/app.py が dist の
有無を見て StaticFiles を自動でマウントする）。

開発時（フロントエンドを `npm run dev` で別プロセス起動する場合）は
このスクリプトではなく、以下をそれぞれ別ターミナルで実行する:
    python -m uvicorn webapp.app:app --reload --host 127.0.0.1 --port 8000
    cd webapp/frontend && npm run dev
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("webapp.app:app", host="127.0.0.1", port=8000)
