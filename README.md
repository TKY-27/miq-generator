# MIQ-style Quote Generator

アイコン画像と引用文から、1920×1080 の「Make it a Quote」風 PNG 画像を生成する小さな Python ツールです。**画像生成AIや外部APIは不要**です。

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

改行や長文を正確に渡したい場合は UTF-8 テキストファイルを使えます。

```bash
python miq.py --avatar avatar.png --text-file quote.txt --name "投稿者名" --output quote.png
```

フォントが自動検出できない場合:

```bash
python miq.py --avatar avatar.png --text-file quote.txt --font "/path/to/NotoSansCJK-Regular.ttc"
```

`--font` / `--bold-font` のほか、環境変数 `MIQ_FONT` でも通常フォントを指定できます。名前とIDは省略可能です。長い文章では文字サイズと改行を自動調整し、入りきらない場合は省略せずエラーにします。

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
