# MIQ-style Quote Generator

アイコン画像と引用文から「Make it a Quote」風の PNG を作る小さな Python ツールです。
**Pillow と日本語フォントだけで動き、画像生成AIも外部APIも使いません。**

## 特徴

- **出力サイズを指定できる**（既定 `640x360`）。レイアウトはすべてサイズに比例して縮む
- **長文でも縦は伸ばさない**。入る最大の文字サイズを探し、それでも入らないときは
  本文を縦に縮めて収める（省略しないので、どれだけ長くても本文は全部入る）
- **本文の寄せ方を選べる**（アイコンの右側 / 画面中央）
- **絵文字は色つき**（Noto Color Emoji）、**欧文は斜体**で描く
- Discord の**サーバー絵文字**（`<:name:id>`）も画像として貼れる
- 禁則処理つき（句読点を行頭に置かない・開き括弧を行末に残さない）

## 必要環境

- Python 3.10 以降
- Pillow（`requirements.txt`）
- 日本語を表示できるフォント（Noto Sans CJK、游ゴシック、ヒラギノ角ゴシックなど）

Linux では `sudo apt install fonts-noto-cjk` などで導入してください。
色つき絵文字を使う場合は Noto Color Emoji、欧文の斜体を使う場合は
Noto Sans Italic なども入れておくと自動検出します。
フォントファイルはこのリポジトリに含めません。

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

表示名とユーザー名も入れる場合:

```bash
python miq.py --avatar avatar.png --text "引用したい本文" \
  --name "AM09:21" --handle "AM09_21" --output quote.png
```

改行や長文をそのまま渡したい場合は、UTF-8 のテキストファイルを使います。

```bash
python miq.py --avatar avatar.png --text-file quote.txt --name "投稿者名" --output quote.png
```

サイズと本文の寄せ方を指定する場合:

```bash
python miq.py --avatar avatar.png --text-file quote.txt \
  --size 854x480 --align center --output quote.png
```

フォントが自動検出できない場合:

```bash
python miq.py --avatar avatar.png --text-file quote.txt \
  --font "/path/to/NotoSansCJK-Regular.ttc" --bold-font "/path/to/NotoSansCJK-Bold.ttc"
```

## オプション

| オプション | 既定 | 説明 |
| --- | --- | --- |
| `--avatar`, `--image` | （必須） | 投稿者のアイコン（PNG / JPEG / WebP など） |
| `--text`, `--quote` | （必須） | 表示する本文 |
| `--text-file` | | 本文を UTF-8 ファイルから読む（`--text` とは排他） |
| `--name` | 空 | 表示名（省略可） |
| `--handle` | 空 | `@ユーザー名`（省略可。先頭の `@` は付けても付けなくてもよい） |
| `--output`, `-o` | `quote.png` | 出力先 |
| `--size` | `640x360` | 出力サイズ（`854x480` / `1280x720` / `1920x1080` など） |
| `--align` | `right` | 本文の寄せ方。`right`=アイコンの右側へ寄せる / `center`=画面中央 |
| `--font` | 自動検出 | 本文のフォント |
| `--bold-font` | 自動検出 | 表示名のフォント |
| `--emoji-font` | 自動検出 | 色つき絵文字フォント |
| `--italic-font` | 自動検出 | 欧文の斜体フォント |

## 環境変数

コマンドラインで指定しないときは、環境変数でも指定できます。

| 変数 | 対応するオプション |
| --- | --- |
| `MIQ_SIZE` | `--size` |
| `MIQ_TEXT_ALIGN` | `--align` |
| `MIQ_FONT` | `--font` |
| `MIQ_EMOJI_FONT` | `--emoji-font` |
| `MIQ_ITALIC_FONT` | `--italic-font` |

## ライブラリとして使う

```python
from pathlib import Path
from miq import render

render(Path("avatar.png"), "本文", Path("quote.png"), "表示名", "handle",
       size="640x360", align="right")
```

Discord のサーバー絵文字を貼るときは、`custom_emojis` に `{絵文字ID: 画像パス}` を渡します
（画像が無いときは `:name:` と文字で表示します）。

```python
render(avatar, "やった<:koshian:123>", output, custom_emojis={"123": "emoji.png"})
```

## レイアウトの決まり方

1. 出力サイズに対する本文の領域（アイコンの右側）を決める
2. その領域に収まる**最大の文字サイズを二分探索**で探す
3. 最小サイズでも縦に入らないときは、**本文を縦に縮めて収める**（文字は潰れる）
4. それでも横幅に収まらない行は、禁則処理を保ったまま1文字ずつ折り返す

本文は省略しません。画像の縦横比も変わりません。

## 注意

- このツールは「Make it a Quote」風のレイアウトを独自実装したもので、
  公式 Bot との連携や完全再現ではありません。
- 第三者のアイコンや引用文を、意図せずリポジトリへコミットしないでください
  （`.gitignore` で `quote.png` と `output/` は除外しています）。
