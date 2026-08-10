# ポートフォリオ分析システム

楽天証券形式の保有銘柄CSVから現在株価を自動取得し、Claude APIで
ポートフォリオの割安度・改善提案を分析するツールです。CLI（`main.py`）と、
ブラウザから操作できるWeb GUI（後述の「Web GUI（ブラウザからの操作）」を参照）の
両方を提供しています。

## 機能概要

1. 保有銘柄CSV（楽天証券形式）をパース
2. Yahoo Finance（yfinance）で現在株価を取得（キャッシュ・リトライ付き）
3. Yahoo Finance（yfinance）で保有銘柄の最新ニュースを取得（キャッシュ・リトライ付き）
4. PER・PBR・評価額・含み損益・損益率を自動計算
5. 銘柄ごとの「愛着度」（1〜100）・最新ニュースを考慮したうえでClaude APIが
   ポートフォリオを分析し、Markdownレポートを生成
6. 保有ポートフォリオの傾向（セクター偏重・割安度など）を踏まえ、Claude API
   （web検索ツール併用）が**現在保有していない**新規投資候補をおすすめ
7. `--cache-only` により定期実行・オフライン再実行にも対応
8. CLIに加え、ブラウザから操作できるWeb GUI（FastAPI + React）を提供

## 動作環境

macOS・Linux・Windowsのいずれでも動作します（動作確認は主にmacOSで実施）。
以下を事前にインストールしてください。

| 項目 | 要件 | 備考 |
|---|---|---|
| Python | 3.10以上 | `str \| None` 形式の型ヒントを使用しているため3.10未満では動作しません |
| Node.js | 18以上推奨 | Web GUIのフロントエンド（`webapp/frontend/`）をビルド・開発する場合のみ必要。CLIのみ使う場合は不要。開発時はNode 22（LTS）で動作確認済み |
| Anthropicアカウント | APIキーが必要 | Claude APIは従量課金です。料金は[公式サイト](https://www.anthropic.com/pricing)を参照してください |

保有銘柄CSVの文字コード（Shift-JIS/CP932）は自動判別して読み込むため、OSによる
文字化けは基本的に発生しません。

### Windowsでの実行について

コマンド例はmacOS/Linux（bash）を前提に記載していますが、Windowsでは主に
以下の点が異なります。

- **仮想環境の有効化コマンド**が異なります。
  - コマンドプロンプト: `.venv\Scripts\activate.bat`
  - PowerShell: `.venv\Scripts\Activate.ps1`
    （初回のみ実行ポリシーの制限で失敗する場合、管理者権限のPowerShellで
    `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` を実行してください）
- ディレクトリ移動の `cd portfolio_analyzer` 等はそのままWindowsでも使用できます
  （PowerShell・コマンドプロンプトともに`/`区切りのパスも解釈されます）。
- 後述の「定期実行（例: cron）」はUnix系OS向けの`cron`の例です。
  Windowsで同等の定期実行を行う場合は、代わりに**タスクスケジューラ**
  （`schtasks`コマンド、またはGUIの「タスクスケジューラ」アプリ）から
  `python main.py --portfolio ... --output ...` を実行するタスクを登録してください。
- それ以外（`pip install`、`python main.py ...`、`python run.py`等）はOS共通で
  同じコマンドがそのまま使えます。

## セットアップ

```bash
cd portfolio_analyzer

# 仮想環境の作成（任意）
python3 -m venv .venv

# 仮想環境の有効化
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate.bat     # Windows（コマンドプロンプト）
# .venv\Scripts\Activate.ps1     # Windows（PowerShell）

# 依存ライブラリのインストール
pip install -r requirements.txt

# APIキーの設定
cp .env.example .env
# .env を開き ANTHROPIC_API_KEY=your-api-key-here を実際のキーに書き換える
```

### APIキーの設定方法

1. [Anthropic Console](https://console.anthropic.com/) でAPIキーを発行する
2. `.env` ファイルに以下のように記載する

   ```
   ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
   ```

3. `ANTHROPIC_API_KEY` が未設定のまま実行すると、起動時に分かりやすいエラーメッセージが表示され処理は中断します。

## 実行方法

```bash
# サンプルデータで動作確認
python main.py --portfolio sample_portfolio.csv --output report.md

# キャッシュ済み株価のみを使用（ネットワーク接続不要）
python main.py --portfolio sample_portfolio.csv --output report.md --cache-only

# ログレベルを変更
python main.py --portfolio sample_portfolio.csv --log-level DEBUG

# ニュース取得をスキップ（指標のみで分析、実行時間短縮）
python main.py --portfolio sample_portfolio.csv --no-news
```

### コマンドライン引数

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--portfolio` | `sample_portfolio.csv` | 保有銘柄CSVファイルのパス |
| `--output` | `analysis_report.md` | 分析結果の出力先ファイルパス |
| `--preferences` | `stock_preferences.csv` | 銘柄ごとの愛着度設定CSVのパス（無くても実行可） |
| `--cache-only` | 無効 | キャッシュ済み株価・ニュースのみを使用し、Yahoo Financeへ問い合わせない |
| `--no-news` | 無効 | 保有銘柄の最新ニュース取得をスキップする |
| `--no-recommend` | 無効 | おすすめ新規投資候補の提案をスキップする（web検索を伴うため実行時間短縮にも有効） |
| `--log-level` | `.env`の`LOG_LEVEL`（未設定時`INFO`） | ログレベル（DEBUG/INFO/WARNING/ERROR） |

## CSVフォーマット

`portfolio_loader.py` は以下の3形式を自動判別して読み込みます
（`--portfolio` に指定したファイルの内容から自動判定するため、
どの形式かを指定するオプションは不要です）。

### 1. シンプル形式（サンプル・テスト用）

UTF-8エンコーディングの単一テーブルCSVです。`sample_portfolio.csv` はこの形式です。

| カラム名 | 説明 | 例 |
|---|---|---|
| `code` | 銘柄コード（東証コード） | `9983` |
| `name` | 銘柄名 | `ファーストリテイリング` |
| `purchase_price` | 取得単価（円） | `1200` |
| `quantity` | 保有数量 | `10` |
| `purchase_date` | 購入日（`YYYY-MM-DD`） | `2025-01-15` |

```csv
code,name,purchase_price,quantity,purchase_date
9983,ファーストリテイリング,1200,10,2025-01-15
7203,トヨタ,2500,5,2024-12-20
```

### 2. 楽天証券「資産残高」エクスポート形式（実運用）

楽天証券のサイトから実際にダウンロードできる `assetbalance_YYYYMMDD_HHMMSS.csv`
形式にも対応しています。この形式は以下の特徴を持ちます。

- 文字コードは Shift-JIS(CP932)（自動判別して読み込みます）
- `■特定口座` `■NISA成長投資枠` 等、口座区分ごとに複数セクションへ分かれた帳票形式
- 数値は `"1,015.00"` のように桁区切りカンマ付きでダブルクォート
- **購入日（purchase_date）は含まれない**ため、内部的に欠損値（NaT）として扱われます
- 同一銘柄を複数口座（特定口座・NISA等）で保有している場合は口座ごとに別行として扱われ、
  出力レポートにも「口座区分」列として表示されます

このファイルはそのまま `--portfolio` に指定できます。

```bash
python main.py --portfolio assetbalance_20260809_080158.csv --output report.md
```

> **注意**: 実際の資産残高CSVには保有銘柄・取得単価などの個人情報が含まれます。
> `.gitignore` で `assetbalance_*.csv` はGit管理対象外にしていますが、
> 第三者と共有・Claude API以外へ送信しないよう取り扱いに注意してください。

### 3. 楽天証券「取引履歴」エクスポート形式（実運用）

楽天証券のサイトからダウンロードできる `tradehistoryJP_YYYYMMDD.csv` にも
対応しています。この形式には現在の保有銘柄そのものは含まれず、約定日ごとの
買付・売付・入庫/出庫の明細のみが記録されているため、以下のロジックで
**口座区分・銘柄コードごとに集計し、現在保有中（数量>0）の銘柄のみ**を
算出します。

- 文字コードは Shift-JIS(CP932)（自動判別して読み込みます）
- 約定日の昇順に取引を処理し、移動平均法で取得総額を積み上げます
  - 買付: 受渡金額（手数料・税込）を取得総額に加算
  - 売付: その時点の平均取得単価×売却数量ぶんを取得総額から控除
  - 入庫/出庫: 株式分割等による数量調整であるケースが多いため、取得総額は
    据え置いたまま数量のみ増減させます
  - 信用取引（信用区分が現物以外）の行は保有株数に影響しないため除外します
- 購入日（purchase_date）は「保有数量が0から増加した直近の約定日」を
  現在のポジションの開始日として推定します（判定できない場合はNaT）。
  この日付は後述の愛着度に基づくアドバイス（保有期間の考慮）にも使われます

> **精度についての注意**: この集計方法で算出した取得単価は概算値です。
> 実データで検証したところ、資産残高CSVが示す実際の平均取得単価とほぼ
> 一致しました（12銘柄中10銘柄が完全一致、残り2銘柄も誤差0.1%未満）が、
> これは入庫/出庫が株式分割によるものだったためです。口座間移管など
> 実際にコストが発生する入庫があった場合は、取得単価が実態と乖離する
> 可能性があります。正確な取得単価が必要な場合は資産残高CSV
> （`assetbalance_*.csv`）の利用を推奨します。

```bash
python main.py --portfolio tradehistoryJP_20260809.csv --output report.md
```

> **注意**: 取引履歴CSVにも個人の保有・取引情報が含まれます。`.gitignore` で
> `tradehistoryJP_*.csv` はGit管理対象外にしていますが、取り扱いに注意してください。

銘柄コードはいずれの形式でも日本株を前提とし、内部で自動的に `.T` サフィックスを
付与してYahoo Financeへ問い合わせます（例: `9983` → `9983.T`）。

## 銘柄への「愛着度」設定（個人の投資方針の反映）

含み損益やPER/PBRだけでは測れない、個人の投資方針を分析に反映するための
仕組みです。以下のような方針を持つ場合に有効です。

1. 好きな銘柄は基本的に売らない（追加購入の検討はある）
2. 長期保有していて嫌いではない銘柄は売却を検討しうるが、タイミングの
   判断が難しい

`stock_preferences.csv`（`--preferences` で変更可能）に銘柄コードごとの
愛着度スコア（1〜100、100が最も愛着が強い＝手放したくない）を設定すると、
Claude API への分析プロンプトに反映されます。サンプルとして
`sample_preferences.csv` を同梱しています。

`name` 列は銘柄コードだけだと分かりにくいための任意カラムで、分析には
使用されません（あってもなくても読み込めます）。

```csv
code,name,affection_score
9983,ファーストリテイリング,90
7203,トヨタ自動車,85
```

| 愛着度 | Claudeの分析での扱い |
|---|---|
| 80〜100 | お気に入り。含み損益や割安度に関わらず売却は提案せず、追加購入の観点のみでコメント |
| 50〜79 | 保有期間が長い場合（目安1年以上）、売却タイミングの判断材料を具体的に提示 |
| 1〜49 | 愛着が薄い銘柄として、ポートフォリオ改善・入れ替え候補に積極的に含める |

このファイルが存在しない場合や、ポートフォリオ内の一部銘柄が未設定の場合も
エラーにはならず、該当銘柄はデフォルト値（50）として分析を続行します。

> **注意**: `stock_preferences.csv` に実際の銘柄コードを記載して運用する場合、
> 保有状況の推測材料になりうるため、公開リポジトリにコミットする際は
> `sample_preferences.csv` のような架空データに留めることを推奨します。

## 保有銘柄の最新ニュース

各銘柄について、Yahoo Finance（yfinance）経由で直近のニュース記事
（デフォルト最大3件/銘柄）を取得し、Claude APIへの分析プロンプトに
「参考情報」として含めます。決算発表・業績修正・不祥事など、指標だけ
では分からない直近の材料を分析に反映させることが目的です。

- 追加のAPIキーは不要です（既存の`yfinance`をそのまま利用します）
- 株価と同様にJSONキャッシュ（`news_cache.json`、`.env`の
  `NEWS_CACHE_PATH`で変更可）を使用し、デフォルト6時間以内に取得済みの
  ニュースは再取得しません（`.env`の`NEWS_FRESHNESS_HOURS`で変更可）
- Yahoo Financeへの問い合わせが失敗しても最大3回リトライしたのち、
  ニュース無しとして分析自体は継続します（`.env`の`NEWS_FETCH_RETRIES`で変更可）
- `--no-news` でニュース取得自体をスキップできます（実行時間短縮、または
  ニュースが不要な場合）

> **精度についての注意**: Yahoo Financeのニュースは英語の一般的な市況記事や、
> 銘柄と直接関係の薄い記事が混ざることがあります（特に小型株では
> ニュースが1件も見つからないこともあります）。Claudeへのプロンプトでは
> 「銘柄と明らかに無関係な記事は無視する」よう指示していますが、分析結果の
> ニュース関連コメントは参考情報として扱ってください。

## おすすめ新規投資候補（AIによる提案）

保有銘柄の分析とは別に、現在のポートフォリオの傾向（セクター偏重・割安度・
含み損益など）を踏まえ、**現在保有していない**新規投資候補をClaude API
（web検索ツール併用）が提案します。

- 保有銘柄の分析結果とは独立した、追加のAPI呼び出しとして実行されます
- web検索ツールにより、候補銘柄の直近のニュース・業績動向・株価水準を
  確認したうえで提案します（学習データのみに基づく古い情報での提案を避けるため）
- デフォルトで4銘柄を提案します（`.env`の`RECOMMEND_COUNT`で変更可）
- `--no-recommend` で提案自体をスキップできます（実行時間・コストを抑えたい
  場合、web検索が不要な場合など）
- `--cache-only` 指定時は自動的にスキップされます（web検索にはネットワーク
  接続が必要なため）
- 提案の生成に失敗した場合もエラーにはならず、警告ログを出したうえで
  保有銘柄の分析結果のみのレポートを保存します

> **注意**: あくまでAIによる参考情報であり、投資助言ではありません。
> 提案内容にも免責事項を含めるようプロンプトで指示していますが、
> 最終的な投資判断は自己責任で行ってください。

## 出力例

`report.md` に以下のようなMarkdownレポートが生成されます。

```markdown
## ポートフォリオ分析結果
### 全体評価
...
### 銘柄別分析
- ファーストリテイリング（9983）：含み損18%、割安度：★★★★☆、愛着度：90/100
...
### ポートフォリオ改善提案
...
### 入れ替え候補銘柄の推奨理由
...

---

## おすすめ新規投資候補
### 選定方針
...
### 候補銘柄
- **本田技研工業（7267）**
  - 直近の株価・業績動向: ...
  - 推奨理由: ...
  - 留意点・リスク: ...
...
### 免責事項
...
```

## キャッシュとリトライについて

- 株価取得結果は `price_cache.json`（`.env`の`PRICE_CACHE_PATH`で変更可）に
  保存され、12時間以内に取得済みの銘柄は再取得せずキャッシュを使用します。
- Yahoo Financeへの問い合わせが失敗した場合、最大3回（`.env`の
  `PRICE_FETCH_RETRIES`で変更可）まで指数バックオフでリトライします。
- 全てのリトライが失敗した銘柄は指標がN/Aとなりますが、他銘柄の処理・
  レポート生成は継続されます。

## レポートが途中で切れる場合

保有銘柄数が多い、またはニュース情報が多いなどでClaudeの出力が長くなると、
出力トークン上限（デフォルト8192トークン、`.env`の`CLAUDE_MAX_TOKENS`）に
達し、レポートが途中で打ち切られることがあります。この場合、レポート末尾に
「⚠️ 出力トークン上限に達したため...」という注意書きが自動的に追記される
ので、それが無ければ完全に生成されています。打ち切られていた場合は
`CLAUDE_MAX_TOKENS`をより大きな値（例: `16384`）に増やして再実行してください。

## 定期実行（例: cron）

`--cache-only` を使わずに定期実行することで、常に最新の株価で分析できます。

```cron
# 毎営業日 18:00 に実行
0 18 * * 1-5 cd /path/to/portfolio_analyzer && /path/to/.venv/bin/python main.py --portfolio sample_portfolio.csv --output report_$(date +\%Y\%m\%d).md >> cron.log 2>&1
```

`cron`はUnix系OS（macOS/Linux）向けの仕組みです。**Windowsではタスクスケジューラ**
を使って同様の定期実行が可能です。

```powershell
# 例: 毎営業日18:00に実行するタスクを登録（管理者権限のPowerShellで実行）
schtasks /create /tn "PortfolioAnalyzer" /tr "C:\path\to\portfolio_analyzer\.venv\Scripts\python.exe C:\path\to\portfolio_analyzer\main.py --portfolio sample_portfolio.csv --output report.md" /sc weekly /d MON,TUE,WED,THU,FRI /st 18:00
```

GUIから設定する場合は、「タスクスケジューラ」アプリで新しいタスクを作成し、
「操作」に上記の`.venv\Scripts\python.exe`と`main.py`のフルパスを指定してください。

## Web GUI（ブラウザからの操作）

CLIとは別に、ブラウザから操作できるWeb GUI（`webapp/`）を用意しています。
バックエンドはFastAPI、フロントエンドはReact + Viteで実装しており、
既存の分析ロジック（`analyzer.py`等）は無変更のままサービス層として
再利用しています。`main.py`（CLI）は変更されておらず、そのまま併存します。

### できること

- ポートフォリオCSVのアップロード・切替
- 愛着度設定（`stock_preferences.csv`、CLIと共有）のGUI編集・保存
- 実行オプション（`--cache-only`/`--no-news`/`--no-recommend`相当）の
  トグルと分析実行
- 分析はバックグラウンドジョブとして実行され、進捗（ステージ）をポーリング
  表示（Claude API呼び出しは数十秒〜数分かかるため）
- 生成レポートのMarkdown表示・過去レポート履歴の閲覧

想定利用環境は**ローカルのみ**（`127.0.0.1`にバインド、認証なし）です。
ネットワーク越しに公開する用途は想定していません。

### セットアップ（初回のみ）

```bash
cd portfolio_analyzer
source .venv/bin/activate        # Windowsの場合は .venv\Scripts\activate.bat 等（前述の「動作環境」参照）
pip install -r requirements.txt   # fastapi, uvicorn等が追加されます

cd webapp/frontend
npm install
```

### 起動方法

**開発時**（コード変更を都度反映したい場合、2ターミナル）:

```bash
# ターミナル1: バックエンド（http://127.0.0.1:8000）
cd portfolio_analyzer
python -m uvicorn webapp.app:app --reload --host 127.0.0.1 --port 8000

# ターミナル2: フロントエンド（http://localhost:5173、/api はバックエンドへ自動プロキシ）
cd portfolio_analyzer/webapp/frontend
npm run dev
```

**日常利用**（単一プロセスでAPI+GUIを一体提供、`http://127.0.0.1:8000`）:

```bash
cd portfolio_analyzer/webapp/frontend && npm run build   # 初回・フロント更新時のみ
cd portfolio_analyzer
python run.py
```

### データの保存先

- アップロードしたポートフォリオCSVは `webapp/data/portfolios/` に保存
- 生成レポートは `webapp/data/reports/` にMarkdown＋メタ情報として保存
  （CLIが生成する`report*.md`とは別管理です）
- 愛着度設定は既存の `stock_preferences.csv` をCLIと共有します

`webapp/data/` は個人の資産情報を含むため `.gitignore` で除外済みです。

### テスト

分析ジョブの制御ロジック（`webapp/jobs.py`）は、Claude API呼び出し
（`analyze_portfolio`/`recommend_stocks`）をmockしたpytestで検証できます
（実際のAPI課金は発生しません）。

```bash
cd portfolio_analyzer
pytest webapp/tests/
```

## 注意事項

- `yfinance` はYahoo Financeの非公式ライブラリです。仕様変更により
  データ取得が失敗する可能性があります。
- 本ツールの分析結果は投資助言ではありません。投資判断は自己責任で
  行ってください。
- `.env` にはAPIキーが含まれるため、`.gitignore` によりGit管理対象外と
  しています。誤ってコミットしないよう注意してください。

## ライセンス

[MIT License](LICENSE)

本ツールの分析結果・おすすめ銘柄提案は投資助言ではなく、参考情報として
提供されるものです。投資判断は自己責任で行ってください。作者は本ソフト
ウェアの利用によって生じたいかなる損害についても責任を負いません。
