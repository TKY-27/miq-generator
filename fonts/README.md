フォント本体はGitに含めません。`python scripts/setup_fonts.py` で取得します。

全レイアウトで Noto Sans JP ExtraBold (800)、Playfair Display Bold (700)、
Noto Serif JP SemiBold (600) を使用します。
絵文字は Noto Color Emoji を使用します。

いずれも SIL Open Font License 1.1。配布元、固定リビジョン、SHA-256は
`scripts/fonts.json` に記録し、取得時に各フォントのライセンス・著作権表記も保存します。
フォントを含むDockerイメージ等を配布する場合は `.OFL.txt` も一緒に保持してください。
