フォント本体はGitに含めません。`python scripts/setup_fonts.py` で取得します。

1枚の画像の中は1つの書体で統一し、構図ごとの候補から書体を抽選します
（Noto Sans JP、Noto Serif JP、Zen Maru Gothic、Shippori Mincho B1、Dela Gothic One、
DotGothic16、M PLUS 1 Code、Klee One、RocknRoll One）。
絵文字は Noto Color Emoji を使用します。

いずれも SIL Open Font License 1.1。配布元、固定リビジョン、SHA-256は
`scripts/fonts.json` に記録し、取得時に各フォントのライセンス・著作権表記も保存します。
フォントを含むDockerイメージ等を配布する場合は `.OFL.txt` も一緒に保持してください。
