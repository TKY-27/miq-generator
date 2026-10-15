# MIQ-style Quote Generator

アイコン画像と引用文から「Make it a Quote」風の PNG 画像を生成する小さな Python ツールです。
**画像生成AIや外部APIは不要**（Pillow と日本語フォントだけ）。

- 出力サイズは指定できる（**既定 640x360**。`--size 854x480` / `--size 1920x1080` など）
- **縦は伸ばさない**。長文でも同じ比率のまま、文字サイズと行間で収める
- 絵文字は色つき、欧文は斜体。Discord のサーバー絵文字（`<:name:id>`）も貼れる
- 本文はアイコンの右側へ寄せる（`--align center` で画面中央にもできる）

## 必要環境

- Python 3.10 以降
- Pillow（`requirements.txt` でインストール）
- 日本語を表示できるフォント（Noto Sans CJK、游ゴシック、ヒラギノ角ゴシックなど）

Linuxでは、必要に応じて `sudo apt install fonts-noto-cjk` などで日本語フォントを導入してください。フォントファイルはリポジトリに含めません。

## インストール

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 使い方

画像と本文だけで生成できます。

```bash
python miq.py --avatar avatar.png --text "AIが人類を超える日は近い。" --output quote.png
```

名前とユーザーIDも表示する場合:

```bash
python miq.py --avatar avatar.png --text "引用したい本文" --name "AM09:21" --handle "AM09_21" --output quote.png
```

サイズと本文の寄せ方を指定する場合:

```bash
python miq.py --avatar avatar.png --text-file quote.txt --size 854x480 --align right --output quote.png
```

改行や長文を正確に渡したい場合は UTF-8 テキストファイルを使えます。

```bash
python miq.py --avatar avatar.png --text-file quote.txt --name "投稿者名" --output quote.png
```

フォントが自動検出できない場合:

```bash
python miq.py --avatar avatar.png --text-file quote.txt --font "/path/to/NotoSansCJK-Regular.ttc"
```

### 主なオプション

| オプション | 説明 |
| --- | --- |
| `--size` | 出力サイズ（既定 `640x360`。`854x480` / `1280x720` / `1920x1080` など） |
| `--align` | 本文の寄せ方。`right`（既定。アイコンの右側へ寄せる）/ `center`（画面中央） |
| `--font` / `--bold-font` | 本文／名前のフォント（自動検出できないとき） |
| `--emoji-font` | 色つき絵文字フォント（省略時は自動検出） |
| `--italic-font` | 欧文の斜体フォント（省略時は自動検出） |

環境変数でも指定できます: `MIQ_SIZE` / `MIQ_TEXT_ALIGN` / `MIQ_FONT` /
`MIQ_EMOJI_FONT` / `MIQ_ITALIC_FONT`。名前とIDは省略可能です。

**長い文章でも失敗しません。** 縦は伸ばさず、入る最大の文字サイズを二分探索で探し、
最小サイズでも入らないときは本文を縦に縮めて収めます（文字が潰れるのは許容）。
省略（「…」）はしないので、本文は全部入ります。

### ライブラリとして使う

```python
from miq import render

render(Path("avatar.png"), "本文", Path("quote.png"), "表示名", "handle",
       size="640x360", align="right")
```

Discord のサーバー絵文字を貼りたいときは、`custom_emojis` に `{絵文字ID: 画像パス}` を渡します。

```python
render(avatar, "やった<:koshian:123>", output, custom_emojis={"123": "emoji.png"})
```

## GitHubに非公開で登録する

GitHub CLI (`gh`) 認証済みなら、このディレクトリで以下を実行します。

```bash
git init
git add miq.py requirements.txt README.md .gitignore
git commit -m "Initial private quote generator"
gh repo create miq-generator --private --source=. --remote=origin --push
```

`--private` 指定が必要です。第三者のアイコンや引用文は意図せずコミットしないようにしてください。

## 注意

このツールは「Make it a Quote」風のレイアウトを独自実装したもので、公式 Bot との連携や完全再現ではありません。
