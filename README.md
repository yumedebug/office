# AI Office Workspace

左側に ChatGPT / GLM / DeepSeek / Qwen の公式 Web サイトを、右側に Excel / Word / PowerPoint 風の
エディタを並べた Windows 向けデスクトップアプリです。AI の回答を取得し、そのまま
表計算・文書・スライドへ変換して編集できます。

- GUI: Python 3.10+ / PySide6（Qt WebEngine）
- エディタ: React + TypeScript + Vite
  - 表計算: FortuneSheet `1.0.4`
  - 文書: Tiptap `3.32.1`
  - スライド: Reveal.js `6.0.2`（編集 UI は独自実装）
- 連携: QWebChannel（`officeBridge`）+ `runJavaScript()`
- API キー不要。各 AI には利用者自身がログインします。

## 動作環境

| 項目 | 要件 |
|---|---|
| OS | Windows 10 / 11 |
| Python | 3.10 以上 |
| Node.js | 18 系 または 20 系以上（Vite 5 の要件） |
| 画面 | 1100 × 650 以上（初期 1500 × 900） |

## セットアップ

### 1. Python の依存関係

```powershell
py -m pip install -r requirements.txt
```

### 2. フロントエンドの依存関係とビルド

```powershell
cd frontend
npm install
npm run build
```

`npm run build` は `tsc --noEmit`（型チェック）の後に Vite でビルドし、
生成物を `../dist` に出力します。`dist` はリポジトリに含まれません。

### 3. 起動

```powershell
cd ..
py main.py
```

`main.py` は起動時に次を確認します。

1. `dist/index.html` が存在するか（無ければビルド手順をダイアログで案内して終了）
2. Qt が内蔵する `:/qtwebchannel/qwebchannel.js` を読み出し、
   `dist/qtwebchannel.js` と `frontend/public/qtwebchannel.js` へ書き出す
   （ダミーファイルは作りません。Qt が提供する実物をそのまま使います）

The Office エディタは通常 `dist/index.html` を `file://` で読み込みます。
Qt WebEngine のビルドによっては ES モジュールの `file://` 読み込みを拒否して
画面が空になることがあるため、その場合はアプリ自身が **127.0.0.1 の一時ポート**
で `dist` を配信する静的サーバーを起動し、自動的に読み込み直します
（ユーザーが別途サーバーを起動する必要はありません。外部通信もありません）。

### 4. フロントエンドだけをブラウザで確認する（任意）

```powershell
cd frontend
npm run dev
```

`http://localhost:5173` でエディタ単体が開きます。Qt の WebChannel が無いため
「Python 未接続」と表示されますが、編集・変換機能は動作します。
この場合も `frontend/public/qtwebchannel.js` が必要です（`py main.py` を一度実行すると生成されます）。

## 配布用の setup.exe を作る

エンドユーザーには `setup.exe` を渡すだけにできます。ビルドは Windows 上で行います。

`setup.exe` はセットアップウィザード（`packaging\setup.py`）を PyInstaller で固めたもので、
アプリ一式を中に同梱しています。Inno Setup などの外部ツールは要りません。

### 必要なもの

| 項目 | 用途 |
|---|---|
| Node.js 18 系 / 20 系以上 | フロントエンドのビルド |
| Python 3.10 以上 | PyInstaller での EXE 化と `setup.exe` の作成 |
| [Inno Setup 6.3 以上](https://jrsoftware.org/isdl.php) | `--inno` を付けたときだけ（任意） |

### ビルド

コマンドプロンプト（cmd）で実行します。PowerShell の実行ポリシーに影響されず、
`build.bat` をダブルクリックしても実行できます。

```bat
packaging\build.bat
```

`setup.exe` まで作らずアプリ本体（EXE）だけを確認したい場合：

```bat
packaging\build.bat --skip-installer
```

内部で次の順に実行します。

1. `frontend` で `npm install` → `npm run build`（出力は `dist\`）
2. `packaging\prepare_qwebchannel.py` で Qt の `qwebchannel.js` を `dist\` へ同梱
3. `pip install -r requirements.txt` とビルド用依存（PyInstaller / Pillow）の導入
4. `packaging\make_icon.py` で `packaging\app.ico` を生成
5. PyInstaller で EXE 化 → `packaging\output\AIOfficeWorkspace\`
6. PyInstaller で `packaging\output\AI-Office-Workspace-Setup.exe` を作成
   （アプリ一式を `payload.zip` として同梱したセットアップウィザード）
7. `setup.exe` を `site\AI-Office-Workspace-Setup.zip` にまとめる（`index.html` のダウンロード先）

| オプション | 動作 |
|---|---|
| `--skip-npm-install` | 既存の `node_modules` を再利用する（`npm install` を省く） |
| `--skip-installer` | PyInstaller までで止め、EXE フォルダだけ作る |
| `--inno` | `setup.exe` を Inno Setup（`packaging\installer.iss`）で作る |

### 配布（サイトのダウンロードボタン = zip）

アプリの案内ページは `site\index.html`（HTML 1 ファイル完結、外部 CSS/JS なし）です。
このページのダウンロードボタンは `./AI-Office-Workspace-Setup.zip` を指しており、
その zip の中に `AI-Office-Workspace-Setup.exe` が 1 つ入っています。

```text
site\
├── index.html                        # 案内ページ（ボタンは下の zip を指す）
└── AI-Office-Workspace-Setup.zip     # ← ビルドで生成（.gitignore 済み）
```

- **配布するのは zip 1 ファイル**です。利用者は zip を展開して setup.exe を実行します。
  ブラウザやホスティングサービスが `.exe` の直接ダウンロードを嫌がる場合も、zip なら通ります。
- `site\` フォルダごとアップロードすれば、そのまま Web サイトとして公開できます
  （外部 CSS / JS / フォントを読み込まないので、そのまま置くだけで表示されます）。
- setup.exe を作り直さずに zip だけ作り直す場合は次の 1 コマンドです。

  ```bat
  python packaging\make_site_zip.py
  ```

- `setup.exe` は zip 内では非圧縮で格納します（実行ファイルは既に圧縮されているため、
  圧縮してもサイズはほとんど変わりません）。zip のサイズはほぼ `setup.exe` と同じです。
- ページのボタン先と zip の名前が食い違っていると、スクリプトが警告を出します。

### セットアップ画面

`setup.exe` をダブルクリックすると、次のウィザードが開きます。

1. **ようこそ** — 説明のみ。
2. **インストール先フォルダ** — フォルダを選べる（直接入力も可）。既定は
   `%LOCALAPPDATA%\Programs\AI Office Workspace`。必要容量と空き容量を表示します。
3. **ショートカット** — 「デスクトップにショートカットを作成」「スタートメニューに
   ショートカットを作成」「インストール後にアプリを起動する」を選べます（既定はすべて ON）。
4. **インストール中** — コピーとショートカット作成の進捗を表示。
5. **完了** — インストール先を表示し、「完了」で閉じます（起動する設定なら同時に起動）。

- 管理者権限は要りません（現在のユーザーにのみインストールします）。
- 既に同じフォルダに入っている場合は置き換えます。設定・ログイン情報は
  `%APPDATA%\AI Office Workspace` に残ります。
- アンインストール情報を `HKCU` に登録するので、
  「設定 → アプリ → インストールされているアプリ」から削除できます。
- `setup.exe` はアプリ本体を同梱しているため、この 1 ファイルだけでインストールできます
  （配布するときは `site\AI-Office-Workspace-Setup.zip` に包んで渡します）。

Python は `py` ランチャーを優先し、無ければ `python` を使います。明示する場合は
実行前に `set PYTHON=python` のように環境変数で指定してください。

PowerShell を使いたい場合は `packaging\build.ps1` も残しています（実行ポリシーの都合で
`powershell -ExecutionPolicy Bypass -File packaging\build.ps1` と指定してください）。

### インストール後の姿

| 種類 | 場所 |
|---|---|
| プログラム本体 | `%LOCALAPPDATA%\Programs\AI Office Workspace\`（管理者権限不要） |
| ショートカット | デスクトップとスタートメニュー（セットアップ画面で選択、既定は両方） |
| アンインストール | 「設定 → アプリ → インストールされているアプリ」から削除 |
| 設定・自動保存・ログイン情報 | `%APPDATA%\AI Office Workspace\`（`config.json` / `autosave.json` / `ui_state.json` / `profiles\`） |
| ダウンロードしたファイル | `ドキュメント\AI Office Workspace\downloads\` |

- インストール先は読み取り専用のため、**設定とプロファイルはユーザーデータ側**に置きます。
  `config.json` は初回起動時に同梱版から自動コピーされ、以後は自由に編集できます。
- アンインストールしてもユーザーデータ（設定・ログイン・ダウンロード）は残ります。
  完全に消す場合は `%APPDATA%\AI Office Workspace` を削除してください。

### 注意点

1. **コード署名をしていないため、初回起動時に SmartScreen の警告が出ます。**
   「詳細情報」→「実行」で起動できます。配布物を署名する場合は、ビルド後に
   `signtool sign /fd SHA256 /tr <タイムスタンプURL> /td SHA256 <setup.exe>` を実行してください。
2. アイコンは `packaging\make_icon.py` がビルド時に生成する `packaging\app.ico` を使います
   （EXE・ショートカット・アンインストーラ・ウィンドウ／タスクバーに適用）。
   自前のアイコンにする場合は、生成された `packaging\app.ico` を置き換えるか、
   `make_icon.py` のデザインを変更して再ビルドしてください。
3. Qt WebEngine は `_internal\PySide6\resources`（`*.pak`）と
   `_internal\PySide6\translations\qtwebengine_locales` がないと画面が真っ白になります。
   PyInstaller の PySide6 フックが自動で同梱しますが、エディタが白い場合はこの 2 つを確認してください。

## ファイル構成

```text
AI-Office-Workspace/
├── main.py                     # PySide6 本体（ウィンドウ / AI ブラウザ / 抽出 / 保存）
├── config.json                 # AI サイト URL・ウィンドウサイズ等
├── requirements.txt
├── README.md
├── packaging/                  # setup.exe のビルド（PyInstaller）
│   ├── build.bat               # これ 1 本でビルド（推奨）
│   ├── build.ps1               # 同じ処理の PowerShell 版
│   ├── app.spec                # アプリ本体の PyInstaller 定義
│   ├── setup.py                # セットアップウィザード（画面・コピー・ショートカット）
│   ├── setup.spec              # setup.exe の PyInstaller 定義（アプリを同梱）
│   ├── installer.iss           # 任意: Inno Setup 版インストーラの定義（--inno）
│   ├── make_site_zip.py        # site\index.html + setup.exe を 1 つの zip にまとめる
│   ├── prepare_qwebchannel.py  # qwebchannel.js を dist へ同梱
│   ├── make_icon.py            # app.ico（アイコン）の生成
│   └── requirements-build.txt
├── site/
│   └── index.html              # 配布サイトの案内ページ（1 ファイル完結）
├── dist/                       # npm run build の出力（qtwebchannel.js もここに生成）
├── profiles/                   # 起動後に生成される WebEngine プロファイル
│   ├── chatgpt/  glm/  deepseek/  qwen/  office/
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── index.html
    ├── public/                 # qtwebchannel.js が main.py により生成される
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── styles.css
        ├── types.ts
        ├── components/
        │   ├── SpreadsheetEditor.tsx
        │   ├── DocumentEditor.tsx
        │   └── PresentationEditor.tsx
        ├── bridge/officeBridge.ts
        ├── adapters/
        │   ├── spreadsheetAdapter.ts
        │   ├── documentAdapter.ts
        │   └── presentationAdapter.ts
        └── utils/
            ├── markdownParser.ts
            ├── fileImport.ts       # .xlsx / .csv / .docx / .pptx の取り込み
            └── converters.ts
```

## 設定ファイル（config.json）

```json
{
  "app_name": "AI Office Workspace",
  "window_width": 1500,
  "window_height": 900,
  "theme": "dark",
  "ai_sites": {
    "ChatGPT": "https://chatgpt.com/",
    "GLM": "https://chat.z.ai/",
    "DeepSeek": "https://chat.deepseek.com/",
    "Qwen": "https://chat.qwen.ai/"
  }
}
```

- URL はコードに固定していません。`config.json` の `ai_sites` を読みます。
- ファイルが無い／壊れている／型が違う場合は既定値で起動し、警告を表示します。
- `ai_sites` のうち ChatGPT / GLM / DeepSeek / Qwen 以外のキーは無視します。
- 認証情報は保存しません（Cookie は各プロファイル配下にのみ保存されます）。

## 使い方

### AI タブ

上部の `[ ChatGPT ] [ GLM ] [ DeepSeek ] [ Qwen ]` で切り替えます。
各タブは独立した `QWebEngineProfile`（`profiles/<サービス名>/`）を使うため、
Cookie・キャッシュ・ログインセッションはサービスごとに分離されます。
タブを切り替えてもページは再読み込みされません。

ナビゲーションバーの `◀ ▶ ⟳` で戻る／進む／再読み込み、`↗` で現在のページを
既定のブラウザで開きます。読み込みに失敗した場合は上部にエラーバナーが出て、
「再読み込み」「ブラウザで開く」を選べます。
ログイン用ポップアップは元の AI と同じプロファイルで開きます。
AI が生成したファイルのダウンロードもアプリ内で完結します（`ドキュメント\AI Office Workspace\downloads`
へ保存）。保存が終わると「開いて取り込む」／「保存だけ」を確認し、「開いて取り込む」で
対応するエディタ（Excel / Word / Slide）の末尾へ追加して、そのシート／スライドへ自動で移動します。

### AI 回答の取得と挿入

1. AI に質問し、回答が表示されるまで待ちます。
2. 右側ツールバーの **AI回答を挿入**（`Ctrl+Shift+I`）を押します。
3. 最新の回答が取得できたら、挿入方法を選ぶダイアログが開きます。

| 選択肢 | 動作 |
|---|---|
| Insert as Text | 現在のモードへテキストとして挿入 |
| Convert to Table | Markdown 表 / TSV / CSV を解析し Excel のセルへ展開 |
| Convert to Document | 見出し・箇条書き等を解析し Word へ挿入 |
| Convert to Slides | 見出し構造からスライドを生成して末尾へ追加 |
| Cancel | 何もしない |

- 表の挿入で既存セルを上書きする場合は、実行前に確認ダイアログが出ます。
- スライド変換では生成枚数を提示して確認します。既存スライドは削除しません。
- 文書・表・スライドの変換はすべてローカルの JavaScript で行い、外部 AI API は呼びません。
- AI 画面で文字列を選択しておけば **選択テキストを挿入** でその範囲だけを取得できます。

### ファイルの取り込み（Excel / Word / Slide）

AI が作ったファイルをそのまま編集したい場合は、次のどちらかで取り込めます。

1. **ドラッグ＆ドロップ** — エクスプローラーからファイルをアプリのエディタ領域へドロップ
2. **ダウンロード後の確認ダイアログ** — AI 画面でダウンロードすると確認が出るので「開いて取り込む」を選ぶ（取り込んだシートへ自動で移動）

| 拡張子 | 取り込み先 | 動作 |
|---|---|---|
| `.xlsx` / `.xls` / `.csv` / `.tsv` | Excel | ブックのシートを**新しいシートとして追加**（既存シートは残る。重複名は `(2)` を付与） |
| `.docx` | Word | 見出し・段落・箇条書きを解析して文書の末尾へ追加 |
| `.pptx` | Slide | スライド順・タイトル・本文・背景色を読み取り末尾へ追加 |

- 変換はすべてローカルの JavaScript（SheetJS / JSZip）で行い、外部サービスは呼びません。
- 対応していない拡張子をドロップした場合は、ステータスバーにエラーを表示するだけで既存の内容は変わりません。
- 20 MB を超えるファイルは取り込みません（`runJavaScript()` 経由の受け渡しが重くなるため）。

### 取得に失敗したとき

DOM から回答を取得できなかった場合はアプリは落ちません。次の代替手段を提示します。

1. **選択テキストを使用** — AI 画面で選択中の文字列を使う
2. **手動で貼り付け** — コピーした回答をダイアログに貼り付ける

いずれの方法でも、その後の変換メニューは同じように使えます。

### エディタ

| モード | 主な機能 |
|---|---|
| Excel（FortuneSheet） | セル編集、行・列の追加/削除、コピー&ペースト、セル結合、数式、書式設定、複数シート、シート名変更、シート切り替え |
| Word（Tiptap） | 見出し、太字、斜体、下線、取り消し線、箇条書き、番号付きリスト、引用、リンク、文字色、背景色、配置、Undo/Redo。A4 相当の白い用紙 |
| Slide（Reveal.js） | 追加・削除・複製・並び替え、タイトル/本文編集、背景色、レイアウト、前後移動、16:9 プレビュー、プレゼンテーション表示 |

3 モードは同時にマウントされたまま（非表示レイヤー）なので、切り替えても
編集中の内容・選択・Undo 履歴は失われません。

### 保存・読み込み・復元

- **保存** (`Ctrl+S`): 初回は保存先を選択、以降は上書き。`QSaveFile` で安全に書き込みます。
- **開く** (`Ctrl+O`): JSON を検証してから読み込みます。壊れたファイルはエラー表示。
- **新規作成** (`Ctrl+N`): 未保存の変更があれば確認します。
- 編集が止まって 3 秒後にユーザーデータ領域へ自動保存します（アプリ終了時にも保存）。
- 次回起動時は、自動保存データ・最後のモード・スプリッター位置・最後の AI タブを復元します。
- 未保存のまま終了しようとすると、保存／破棄／キャンセルを確認します。

自動保存の場所（Windows）:

```text
%APPDATA%\AI Office Workspace\autosave.json
%APPDATA%\AI Office Workspace\ui_state.json
```

### ショートカット

| キー | 動作 |
|---|---|
| `Ctrl+S` | 保存 |
| `Ctrl+O` | 開く |
| `Ctrl+N` | 新規作成 |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | Excel / Word / Slide |
| `Ctrl+Shift+I` | AI 回答を挿入 |

## 保存フォーマット

```json
{
  "format": "ai-office-workspace",
  "version": 1,
  "activeMode": "document",
  "spreadsheet": {
    "sheets": [
      {
        "name": "Sheet1",
        "id": "sheet-id",
        "order": 0,
        "celldata": [{ "r": 0, "c": 0, "v": { "v": "A1", "m": "A1" } }],
        "config": { "merge": {}, "rowlen": {}, "columnlen": {} }
      }
    ]
  },
  "document": { "type": "doc", "content": [{ "type": "paragraph" }] },
  "slides": [
    {
      "id": "slide-001",
      "title": "Introduction",
      "body": "Presentation content",
      "background": "#FFFFFF",
      "layout": "title-content"
    }
  ],
  "metadata": { "title": "Untitled", "updatedAt": "2026-01-01T00:00:00+00:00" }
}
```

- FortuneSheet のランタイムはセルを `data`（2 次元配列）で保持するため、
  保存時に `dataToCelldata()` で `celldata` へ変換して書き出します。
- 文書は Tiptap の JSON をそのまま保存します。
- 読み込み時は Python 側（`normalize_project`）と React 側（`ensureProject`）の
  両方で形式・型・スライド ID の重複を検証します。

## 設計メモ

### プロファイル分離

| 用途 | プロファイル名 | 保存先 |
|---|---|---|
| ChatGPT | `chatgpt` | `profiles/chatgpt/` |
| GLM | `glm` | `profiles/glm/` |
| DeepSeek | `deepseek` | `profiles/deepseek/` |
| Qwen | `qwen` | `profiles/qwen/` |
| Office エディタ | `office` | `profiles/office/` |

配布版（setup.exe）ではインストール先が書き込み不可のため、プロファイルは
`%APPDATA%\AI Office Workspace\profiles\<サービス名>\` に保存されます（ソース実行時は上表のとおり）。

`QWebEngineProfile` はアプリケーションオブジェクトを親として保持し、
ページより長く生存させています。永続 Cookie を有効化し、キャッシュは各プロファイル配下です。

### QWebChannel

- `officeBridge` という名前で **Office エディタのページにのみ** 登録します。
  AI サイトのページには WebChannel を設定しないため、Bridge は公開されません。
- Python → JavaScript は `runJavaScript()`、JavaScript → Python は
  `editorReady` / `contentChanged` / `showStatus` / `reportError` / `requestSave` / `modeChanged`。
- `window.officeEditor` は `installOfficeApi()` が一度だけ設置し、各呼び出しは
  最新の React 実装へ委譲するため、再レンダリングで参照が古くなりません。
- 初期化完了は固定時間の待機ではなく、`isReady()` の問い合わせ（短い再試行つき）と
  `editorReady` 通知の両方で判定します。

### JavaScript API

```javascript
window.officeEditor = {
  insertText(text),          // JSON 文字列 {ok, message|error}
  getContent(),              // 現在のモードのデータ（JSON 文字列）
  getAllContent(),           // プロジェクト全体（JSON 文字列）
  setContent(data),          // 復元
  setMode(mode),             // 'spreadsheet' | 'document' | 'slides'
  getMode(),
  isReady(),
  planAiResponse(text, action),      // 変換前の確認内容
  applyAiResponse(text, action, confirmed)
};
```

### エディタの読み込み

1. 既定では `dist/index.html` を `file://` で読み込みます。
2. ページ読み込み後に `window.officeEditor.isReady()` を問い合わせ、
   短時間で API が現れない場合は 127.0.0.1 の一時ポートで `dist` を配信して
   読み込み直します（フォールバック）。
3. 2 回目も失敗した場合はステータスバーにエラーを表示します。

`file://` で動作する環境ではソケットを一切開きません。

### セキュリティ

- AI の回答は常に文字列として扱い、HTML として挿入しません。
  Tiptap へは JSON ノード、表計算へはセル値として渡します。
- Markdown のリンクは `http` / `https` / `mailto` のみ許可します。
- Office エディタのページはローカルファイル以外への遷移を拒否し、
  `http(s)` リンクは既定のブラウザで開きます。
- AI サイトの Cookie・トークン・パスワード欄を読み取る処理はありません。
- 回答の取得はボタンを押したときだけ実行し、自動送信・一括リクエストは行いません。

## AI 回答抽出について（重要）

| AI | 抽出方法 | 状態 |
|---|---|---|
| ChatGPT | `[data-message-author-role="assistant"]` の最後の要素 | 既知のセレクタ |
| Qwen | `.markdown-body` の最後の要素 | 既知のセレクタ |
| GLM | 候補セレクタ（`[class*="markdown"]` 等）+ 汎用ヒューリスティック | **未確認**。DOM 変更で失敗する可能性あり |
| DeepSeek | 候補セレクタ（`.ds-markdown` 等）+ 汎用ヒューリスティック | **未確認**。同上 |

GLM と DeepSeek については、実サイトの DOM を確認できていないため
特定のクラス名を断定していません。候補セレクタで見つからない場合は、
「Markdown らしい要素のうち、入れ子でなく、最後に現れ、十分な長さのあるもの」を
選ぶ汎用ロジックで抽出します。それでも失敗した場合は選択テキスト／手動貼り付けに
切り替えてください。抽出処理は DOM を書き換えません（読み取りのみ）。

## 既知の制限

1. **AI サイト側の制限**（アプリ本体の不具合ではありません）
   - ログイン、ボット判定、地域制限、Qt WebEngine 非対応の API などにより、
     ページが表示できない・回答が取れない場合があります。
   - その場合はエラーバナーから「ブラウザで開く」で既定のブラウザへ切り替えられます。
   - User-Agent の偽装やログイン制限の回避は実装していません。
2. GLM / DeepSeek の抽出セレクタは未確認です（上記参照）。
3. `window.confirm` 等のブラウザダイアログには依存しません。確認はすべて Qt の
   ダイアログで行います。
4. FortuneSheet のツールバー・グリッドはライブラリ標準の明色デザインです。
   アプリの外枠（タブ・ツールバー・ステータスバー）はダークテーマで統一しています。
5. 文書モードの表は Tiptap StarterKit に表拡張が無いため、1 行 1 段落の
   テキスト（セルを `|` で区切ったもの）として挿入されます。
   表として扱いたい場合は「Convert to Table」で Excel へ展開してください。
6. プレゼンテーション表示中の編集はできません（閉じてから編集します）。
7. 自動保存は 1 プロジェクト分のみ（`autosave.json`）です。
8. 取り込みは「内容を追加する」機能です。セルの罫線・条件付き書式・数式の一部、
   Word の表・画像、PowerPoint の図形・表・画像は引き継ぎません（文字情報のみ）。

## 動作確認状況

**この開発環境にはシェル（Git Bash）が無く、`python` も `npm` も実行できませんでした。**
そのため、次の項目は「未実行」です。コードは各ライブラリの公開 API
（FortuneSheet 1.0.4 / Tiptap 3.32.1 / Reveal.js 6.0.2 / Qt WebChannel）を
実際の型定義・ソースで確認したうえで実装していますが、
ビルド・起動・実機操作の確認は行っていません。

ファイル取り込み（`frontend/src/utils/fileImport.ts` と Python 側のダウンロード捕捉）も
同じ環境で追加したため、未実行です。取り込みを使うには追加依存（`xlsx` / `jszip`）の
`npm install` と `npm run build` が必要です。

`setup.exe` のビルド（`packaging\build.bat`）も同じ理由で未実行です。PyInstaller と
Inno Setup の設定は各ツールの公開仕様に沿って作成していますが、生成物の起動確認は
行っていません。

未実行の項目:

- `py -m pip install -r requirements.txt`
- `npm install` / `npm run build`（`tsc --noEmit` を含む）
- `py main.py` の起動、AI サイトの表示、ログイン
- AI 回答の抽出、3 モードへの変換、保存・復元の実機確認

以下を上から順に実行すると、この文書に書いた動作を確認できます。

```powershell
py -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
py main.py
```

確認手順:

1. 4 つの AI タブを切り替え、それぞれ別のログイン状態になること。
2. 右側の Excel / Word / Slide を切り替え、入力内容が保持されること。
3. Excel で `=SUM(A1:A3)` を入力し、計算されること。
4. Word で太字・見出し・リスト・色・配置が反映されること。
5. Slide で追加・複製・削除・並び替え、Present で全画面表示できること。
6. AI に「Markdown の表で回答して」と依頼し、**Convert to Table** でセルに入ること。
7. `Ctrl+S` で保存 → `Ctrl+N` で新規 → `Ctrl+O` で復元できること。
8. アプリを終了して再起動し、前回の内容・モード・スプリッター位置・AI タブが戻ること。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| 起動時に「フロントエンドのビルドが見つかりません」 | `cd frontend` → `npm install` → `npm run build` |
| 「エディタ API が初期化されていません」 | `dist/index.html` と `dist/assets/*.js` の生成を確認。`更新` ボタンで再読み込み |
| AI ページが真っ白／読み込めない | エラーバナーから「ブラウザで開く」。プロキシ・社内ネットワーク制限も確認 |
| エディタが真っ白 | ステータスバーの表示を確認。`file://` 非対応の Qt では自動でローカルサーバー経由に切り替わります |
| AI 回答が取得できない | AI 画面で回答を選択 →「選択テキストを挿入」、または「手動で貼り付け」 |
| ファイルをドロップしても取り込めない | 対応形式（`.xlsx` / `.xls` / `.csv` / `.tsv` / `.docx` / `.pptx`）と 20 MB 制限を確認。`npm install` 後に `npm run build` したかも確認 |
| AI 画面でダウンロードできない | `profiles/<サービス名>/` と `ドキュメント\AI Office Workspace\downloads` への書き込み権限を確認 |
| ログイン状態が毎回消える | `profiles/<サービス名>/` への書き込み権限を確認（OneDrive 同期フォルダは非推奨） |
| `setup.exe` を実行すると、その場でアプリが起動してしまう | `AIOfficeWorkspace.exe`（**アプリ本体**）を開いています。インストーラは `packaging\output\AI-Office-Workspace-Setup.exe` です。無ければ `packaging\build.bat` を実行してください |
| `setup.exe` の作成で失敗する | `packaging\build.bat` のメッセージを確認。`--inno` を付けた場合だけ Inno Setup 6.3 以上が必要です（付けなければ不要） |
| インストール版でエディタが真っ白 | `_internal\PySide6\resources`（`*.pak`）と `_internal\PySide6\translations\qtwebengine_locales` があるか、`%APPDATA%\AI Office Workspace` に書けるかを確認 |
| `npm run build` で型エラー | エラー箇所の型を確認（`tsc --noEmit` の結果がそのまま表示されます） |
