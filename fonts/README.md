# fonts/

フォント本体はGitに含めません。`python scripts/setup_fonts.py` で取得してください。
取得元・固定コミット・SHA-256 は `scripts/fonts.json` に記録しています。取得時にはハッシュを確認し、
各フォントのライセンス文書（`*.OFL.txt` / `*.LICENSE.md`）も同じ場所に保存します。

| ファイル | 役割（`miq_fonts.FONT_FILES`） | ライセンス |
| --- | --- | --- |
| `ShipporiMinchoB1-ExtraBold.ttf` | `mincho` 明朝の本文・縦書き | SIL OFL 1.1 |
| `ZenKakuGothicNew-Bold.ttf` / `-Medium.ttf` | `gothic` / `gothic-medium` ゴシックの本文・署名 | SIL OFL 1.1 |
| `DelaGothicOne-Regular.ttf` | `display` poster の極太 | SIL OFL 1.1 |
| `YujiSyuku-Regular.ttf` | `brush` 筆文字（1〜2文字・短文の縦書き） | SIL OFL 1.1 |
| `MPLUS1Code.ttf` / `JetBrainsMono.ttf` | `mono-jp` / `mono` terminal・ASCIIアート | SIL OFL 1.1 |
| `Inter.ttf` | `sans` 欧文の見出し・ユーザー名 | SIL OFL 1.1 |
| `InstrumentSerif-Regular.ttf` / `-Italic.ttf` | `serif` / `serif-italic` 欧文セリフ | SIL OFL 1.1 |
| `CormorantGaramond-Italic.ttf` | `italic` noir の署名 | SIL OFL 1.1 |
| `Anton-Regular.ttf` | `condensed` cover の題字・引用符 | SIL OFL 1.1 |
| `UnifrakturMaguntia-Book.ttf` | `blackletter` newspaper の題字 | SIL OFL 1.1 |
| `Saitamaar-Regular.ttf` | `aa` 日本語AA（MS Pゴシック互換の文字幅） | パブリックドメイン |
| `NotoSansJP.ttf` | `fallback` 不足文字の補完 | SIL OFL 1.1 |
| `NotoColorEmoji.ttf` | 絵文字 | SIL OFL 1.1 |

`.cache/` には、フォントの文字表（どの文字を描けるか）のキャッシュが自動で作られます。削除しても問題ありません。
フォントを含むDockerイメージなどを配布する場合は、ライセンス文書も一緒に含めてください。
