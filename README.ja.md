<div align="center">

# fdstoolkit

<strong>ディスクカードを読み取り、読み取れたものを評価し、任天堂が書いた内容を復元し、そしてもう一度書き込む。</strong>

[![ci](https://github.com/gufranco/fdstoolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/gufranco/fdstoolkit/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](#貢献)
[![python](https://img.shields.io/badge/python-3.13-blue)](pyproject.toml)

<p align="center">
  <a href="#インストール">インストール</a> &nbsp;|&nbsp;
  <a href="#先に把握しておく概念">概念</a> &nbsp;|&nbsp;
  <a href="#コマンドリファレンス">コマンド</a> &nbsp;|&nbsp;
  <a href="#ウェブインターフェース">ウェブインターフェース</a> &nbsp;|&nbsp;
  <a href="#手順">手順</a> &nbsp;|&nbsp;
  <a href="#フォーマット">フォーマット</a>
</p>

[English](README.md) | **日本語**

</div>

コマンドは **56** 個、そのすべてがローカルの Web ページからも使えます。テストは **1,754** 件、行と分岐の網羅率は **100%**。同一性は **595** 枚のイメージ、パルスクラスは実機の **120** 面、空ディスクの値は一度も書き換えられていない **1,729** 面から測定しています。

---

ファミコン ディスクシステムのディスクカードを扱うためのコマンドラインツールです。読み取り、品質の測定、再構成、書き戻し、そしてそれらを行うドライブ自体の調整までを対象とします。

これは製品ではなく計測器です。ディスク情報ブロックが何かを理解しており、ドライブを開けて半固定抵抗を回すことを厭わず、判定だけでなく測定値そのものを見たい人を想定しています。報告を行うコマンドはすべて `--json` を受け付けます。異常がなければ終了コード 0、あれば 1 を返すため、シェルスクリプトに組み込めます。

## 目次

- [インストール](#インストール)
- [先に把握しておく概念](#先に把握しておく概念)
- [コマンドリファレンス](#コマンドリファレンス)
  - [検査](#検査)
  - [変換と生成](#変換と生成)
  - [編集と修復](#編集と修復)
  - [セーブデータ](#セーブデータ)
  - [識別](#識別)
  - [品質測定](#品質測定)
  - [ドライブ調整](#ドライブ調整)
  - [マスターと参照セット](#マスターと参照セット)
  - [ハードウェア](#ハードウェア)
- [ウェブインターフェース](#ウェブインターフェース)
- [手順](#手順)
- [フォーマット](#フォーマット)
- [終了コードとスクリプト化](#終了コードとスクリプト化)
- [このツールにできないこと](#このツールにできないこと)

## インストール

```bash
brew tap gufranco/fdstoolkit https://github.com/gufranco/fdstoolkit
brew install gufranco/fdstoolkit/fdstoolkit
```

`brew install --HEAD gufranco/fdstoolkit/fdstoolkit` は `main` ブランチを追跡します。

Homebrew がサポート対象のインストール経路であり、フォーミュラはすべてを含みます。ドライブが必要とする hidapi ライブラリも、ウェブインターフェースもです。追加で入れるものはなく、新規インストール直後に `doctor` がそれを検証します。

インストール状態と、到達できるハードウェアを確認します。

```bash
fdstoolkit doctor
```

```
fdstoolkit        0.6.0
python            3.13.15
platform          Darwin arm64
hardware support  hidapi is installed
fdsstick          1 device(s) connected, loopy FDSStick, serial 0001, firmware 1.04
fdsstick access   the device opens for reading and writing
dat cache         ~/.cache/fdstoolkit/dat, 0 catalogue(s)
```

`doctor` はソフトウェアだけでなく接続経路全体を確認します。hidapi が入っているか、FDSStick が `16D0:0AAA` に接続されているか、デバイスが自己申告するメーカー名・製品名・シリアル・ファームウェアは何か、そして実際にオープンできるかを報告します。最後の項目は Linux で特に重要です。列挙はできるのに udev ルールがないためオープンできない、という状態が起こり得るからです。その場合 `doctor` はこの項目を失敗として扱い、書き込むべきルールを表示します。

## 先に把握しておく概念

**1 面はブロックの並びです。** タイプ 1 は 56 バイトのディスク情報ブロック、タイプ 2 は 2 バイトのファイル数、タイプ 3 は 16 バイトのファイルヘッダ、タイプ 4 はファイル本体です。セクタもトラックも存在せず、媒体は 1 本の連続した渦巻きです。このツールがシーク動作に一切言及しないのはそのためです。

**同一性プロファイル。** 同じゲームでも吸い出したバイト列は一致しません。ディスクライターが書き換えのたびに独自のシリアル、日付、書き換え回数を刻印するためです。プロファイルは、ハッシュを取る前にどのフィールドを同一性の判定に含めるかを選びます。

| プロファイル | 除外する情報 | 用途 |
|---|---|---|
| `raw` | なし | コンテナを含む完全なバイト一致 |
| `content` | 書き換え履歴のフィールド | 同一の物理ディスクの 2 回の吸い出し |
| `release` | 書き換え履歴とディスクライターが刻印した領域 | 同一タイトルの別個体 |
| `data` | ブロックコード以外のディスク情報すべて | ファイル内容のみ |

ダイジェストは `fdstoolkit:v1:<プロファイル>/v1:<sha256>` の形式で出力されます。595 イメージのコーパスでは、`release` で 144 グループ中 142 が、`content` で 125 が一致します。

**FDSStick のキャプチャが持つのは時間情報ではなくパルスクラスです。** この機器はハードウェアの側で各パルスを 3 種類の公称長のいずれかへ丸め、`dump --raw` はそのクラスを `raw03` ファイルとして保存します。これはドライブが 3 種類の長さをどれだけ均等に分けて読めているかを示し、`classes` がそれを測定します。速度は示せないため、速度は実機側から `reading` で得ます。

**1 本のゲームは 1 枚のディスクです。** どのゲームも片面または両面の 1 枚のディスクを使い、2 枚目にまたがるゲームはありません。3 面以上を持つイメージは複数のディスクを 1 つにまとめたものであり、すべてのコマンドがこれを拒否します。

## コマンドリファレンス

記法: `<>` は値、`[]` は省略可、`...` は繰り返しです。

### 検査

#### `doctor`

```bash
fdstoolkit doctor [--json]
```

バージョン、Python、プラットフォーム、ハードウェア対応の導入状況、接続されているデバイスとそれを開けるか、DAT キャッシュの状態。挙動がおかしいときは最初にこれを実行してください。ここで表示されるデバイス情報は、吸い出しの提出時に求められる「ハードウェア、ファームウェア、ソフトウェアのバージョン」に相当します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/doctor-dark.png">
<img alt="ローカル Web ページの doctor コマンド" src="assets/screenshots/doctor-light.png">
</picture>

#### `info`

```bash
fdstoolkit info <image> [--json]
```

面数、ゲームコード、製造日と書き換え日、ディスクライターのシリアル、宣言されたファイル数と実際のファイル数、隠しファイル、末尾の余剰データ。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/info-dark.png">
<img alt="ローカル Web ページの info コマンド" src="assets/screenshots/info-light.png">
</picture>

#### `ls`

```bash
fdstoolkit ls <image> [--json]
```

全面のすべてのファイル。番号、ID、名前、ロードアドレス、種別、サイズ、宣言数を超えた位置にあるかどうか。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/ls-dark.png">
<img alt="ローカル Web ページの ls コマンド" src="assets/screenshots/ls-light.png">
</picture>

#### `verify`

```bash
fdstoolkit verify <image> [--strict] [--json]
```

構造とチェックサムの検出結果を、それぞれコード付きで報告します。`--strict` は警告でも失敗とします。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/verify-dark.png">
<img alt="ローカル Web ページの verify コマンド" src="assets/screenshots/verify-light.png">
</picture>

#### `hash`

```bash
fdstoolkit hash <image> [--profile <name>] [--json]
```

イメージ全体と各面の CRC32、MD5、SHA-1、SHA-256、加えて正規化ダイジェストと RetroAchievements の MD5。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/hash-dark.png">
<img alt="ローカル Web ページの hash コマンド" src="assets/screenshots/hash-light.png">
</picture>

#### `diff`

```bash
fdstoolkit diff <a> <b> [--explain] [--json]
```

どのブロックが異なるか。`--explain` はブロック番号ではなくディスク情報のフィールド名とファイル名で示します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/diff-dark.png">
<img alt="ローカル Web ページの diff コマンド" src="assets/screenshots/diff-light.png">
</picture>

#### `boot`

```bash
fdstoolkit boot <image> [--json]
```

各面を BIOS がどう扱うか。どのファイルを読み込むか、承認データがあるか、表示されるエラー番号は何か。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/boot-dark.png">
<img alt="ローカル Web ページの boot コマンド" src="assets/screenshots/boot-light.png">
</picture>

#### `layout`

```bash
fdstoolkit layout <image> [--json]
```

渦巻き上での各ファイルのバイトオフセットと、公称ビットレートでドライブがそこへ到達するまでの時間。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/layout-dark.png">
<img alt="ローカル Web ページの layout コマンド" src="assets/screenshots/layout-light.png">
</picture>

#### `provenance`

```bash
fdstoolkit provenance <image> [--json]
```

面ごとに工場出荷、ディスクライターでの書き換え、判別不能のいずれかを、日付・シリアル・書き換え回数という根拠とともに報告します。工場出荷のディスクはシリアル `ffff`、書き換え回数 `00` を持ちます。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/provenance-dark.png">
<img alt="ローカル Web ページの provenance コマンド" src="assets/screenshots/provenance-light.png">
</picture>

### 変換と生成

#### `convert`

```bash
fdstoolkit convert <image> -o <out> [--header|--no-header] [--crc-mode preserve|compute|null] [--force]
```

`.fds` と `.qd` の相互変換。`--crc-mode` は `.qd` を書くときに CRC フィールドへ何を入れるかを決めます。元の値を保持するか、再計算するか、ゼロにするか。既定が `preserve` なのは、再計算を伴う往復変換が、調査対象かもしれない破損を黙って修復してしまうからです。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/convert-dark.png">
<img alt="ローカル Web ページの convert コマンド" src="assets/screenshots/convert-light.png">
</picture>

#### `canon`

```bash
fdstoolkit canon <image> --profile <name> [-o <out>] [--force]
```

正規化ダイジェストを表示し、`-o` を付けると正規化イメージを書き出します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/canon-dark.png">
<img alt="ローカル Web ページの canon コマンド" src="assets/screenshots/canon-light.png">
</picture>

#### `blank`

```bash
fdstoolkit blank -o <out> [--sides 1|2] [--formatted] [--header] [--game-name ABC] [--force]
```

空のイメージ。`--formatted` は、一度も書き換えられていない 1,729 面から実測した値でディスク情報ブロックを書きます。国コード `49`、シリアル `ffff`、書き換え回数 `00`、フィラー `ff`。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/blank-dark.png">
<img alt="ローカル Web ページの blank コマンド" src="assets/screenshots/blank-light.png">
</picture>

#### `build`

```bash
fdstoolkit build <manifest> -o <out> [--force]
```

ディスクのフィールドと配置するファイルを記述した JSON マニフェストからディスクを組み立てます。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/build-dark.png">
<img alt="ローカル Web ページの build コマンド" src="assets/screenshots/build-light.png">
</picture>

#### `card`

```bash
fdstoolkit card -o <out> [--sides 1|2] [--firmware <variant>] [--force]
```

FDSKey が受け付ける空のイメージ。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/card-dark.png">
<img alt="ローカル Web ページの card コマンド" src="assets/screenshots/card-light.png">
</picture>

#### `split` and `join`

```bash
fdstoolkit split <image> -d <dir> [--stem <s>] [--force]
fdstoolkit join <files>... -o <out> [--force]
```

コピア形式の 1 面 1 ファイルへの分割と、その逆。`--stem` は面ファイルの基本名で、既定は `fc1234` です。`join` はファイルの順序を問いません。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/split-dark.png">
<img alt="ローカル Web ページの split コマンド" src="assets/screenshots/split-light.png">
</picture>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/join-dark.png">
<img alt="ローカル Web ページの join コマンド" src="assets/screenshots/join-light.png">
</picture>

#### `export`

```bash
fdstoolkit export <image> --target <t> -d <dir> [--bios <file>] [--force]
```

機器やエミュレータが期待するディレクトリ構成で書き出します。対象は `nt-mini`、`mister`、`everdrive-n8-pro`、`mesen2`、`fceux`、`ares`。`--bios` を付けると BIOS もその対象が探す場所へ配置します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/export-dark.png">
<img alt="ローカル Web ページの export コマンド" src="assets/screenshots/export-light.png">
</picture>

#### `import-ares`

```bash
fdstoolkit import-ares <files>... -o <out> [--force]
```

ares の面別ファイルから、そこに含まれるセーブデータごとイメージを再構成します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/import-ares-dark.png">
<img alt="ローカル Web ページの import-ares コマンド" src="assets/screenshots/import-ares-light.png">
</picture>

### 編集と修復

#### `extract`

```bash
fdstoolkit extract <image> -d <dir> [--force]
```

宣言数を超えた位置にあるファイルも含め、すべてのファイルを書き出します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/extract-dark.png">
<img alt="ローカル Web ページの extract コマンド" src="assets/screenshots/extract-light.png">
</picture>

#### `insert`

```bash
fdstoolkit insert <image> --file <f> --name <n> -o <out> [--address <hex>] [--kind program|character|nametable] [--side N] [--force]
```

ファイルを追加し、宣言ファイル数を増やします。`--address` の既定値は `6000` です。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/insert-dark.png">
<img alt="ローカル Web ページの insert コマンド" src="assets/screenshots/insert-light.png">
</picture>

#### `set`

```bash
fdstoolkit set <image> --set field=value... -o <out> [--side N] [--force]
```

ディスク情報のフィールドを変更します。複数指定できます。フィールド名は `info --json` が出力するものです。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/set-dark.png">
<img alt="ローカル Web ページの set コマンド" src="assets/screenshots/set-light.png">
</picture>

#### `clean`

```bash
fdstoolkit clean <image> -o <out> [--force]
```

最終ブロック以降に残った非ゼロバイトを除去します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/clean-dark.png">
<img alt="ローカル Web ページの clean コマンド" src="assets/screenshots/clean-light.png">
</picture>

#### `rebuild`

```bash
fdstoolkit rebuild <image> -o <out> [--keep-tail] [--reveal-hidden] [--drop-hidden] [--renumber] [--force]
```

解析済みのモデルから再出力します。チェックサムを再計算し、宣言サイズを訂正し、末尾の余剰データを落とします。隠しファイルは既定で保持されます。`--reveal-hidden` は宣言数を実数に合わせ、`--drop-hidden` は削除します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/rebuild-dark.png">
<img alt="ローカル Web ページの rebuild コマンド" src="assets/screenshots/rebuild-light.png">
</picture>

#### `patch`

```bash
fdstoolkit patch <image> --patch <p> -o <out> [--force]
```

IPS、UPS、BPS を適用します。ヘッダ付きとヘッダなしのどちらに対して作られたパッチでも構いません。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/patch-dark.png">
<img alt="ローカル Web ページの patch コマンド" src="assets/screenshots/patch-light.png">
</picture>

#### `splice`

```bash
fdstoolkit splice <image> --donor <d>... -o <out> [--force]
```

CRC に失敗したブロックを、同じブロックが正常な別の吸い出しから移植します。置換した箇所と、どのドナーからも供給できなかったブロックをすべて報告します。修復できないものが残れば終了コード 1 を返します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/splice-dark.png">
<img alt="ローカル Web ページの splice コマンド" src="assets/screenshots/splice-light.png">
</picture>

### セーブデータ

#### `saves`

```bash
fdstoolkit saves <images>... [--json]
```

同一タイトルの複数の吸い出しを比較し、どのファイルがセーブデータかを報告します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/saves-dark.png">
<img alt="ローカル Web ページの saves コマンド" src="assets/screenshots/saves-light.png">
</picture>

#### `save-apply`

```bash
fdstoolkit save-apply <image> --save <s> -o <out> [--force]
```

IPS、UPS、BPS、またはイメージ全体のセーブを書き戻します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/save-apply-dark.png">
<img alt="ローカル Web ページの save-apply コマンド" src="assets/screenshots/save-apply-light.png">
</picture>

#### `save-extract`

```bash
fdstoolkit save-extract <image> --played <p> -o <out> [--format ips|ups|image] [--force]
```

未プレイのディスクとプレイ済みのディスクの差分を書き出します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/save-extract-dark.png">
<img alt="ローカル Web ページの save-extract コマンド" src="assets/screenshots/save-extract-light.png">
</picture>

#### `normalise-saves`

```bash
fdstoolkit normalise-saves <image> --recipes <r> -o <out> [--force]
```

宣言されたセーブ領域を消去し、プレイ済みの 2 本が一致して比較できるようにします。`--recipes` はどの領域がセーブかを宣言するファイルで、必須です。どのバイトをゲームが書き換えるかを本ツールが推測することはありません。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/normalise-saves-dark.png">
<img alt="ローカル Web ページの normalise-saves コマンド" src="assets/screenshots/normalise-saves-light.png">
</picture>

### 識別

#### `identify`

```bash
fdstoolkit identify <image> --dat <file> [--reference <dir>] [--no-cache] [--json]
```

一致した DAT のエントリと、どのダイジェストで一致したか。`--reference` を付けると、一致しなかった場合にそのディレクトリ内で最も近いイメージと、異なるバイト範囲を報告します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/identify-dark.png">
<img alt="ローカル Web ページの identify コマンド" src="assets/screenshots/identify-light.png">
</picture>

#### `dat-cache`

```bash
fdstoolkit dat-cache [--clear]
```

解析済み DAT のキャッシュを表示または削除します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/dat-cache-dark.png">
<img alt="ローカル Web ページの dat-cache コマンド" src="assets/screenshots/dat-cache-light.png">
</picture>

#### `bios`

```bash
fdstoolkit bios <file> [--extract <out>] [--force]
```

BIOS のリビジョンと、そのファイルを受け付けるエミュレータ。`--extract` はより大きなダンプから 8 KB のイメージを取り出します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/bios-dark.png">
<img alt="ローカル Web ページの bios コマンド" src="assets/screenshots/bios-light.png">
</picture>

#### `lint`

```bash
fdstoolkit lint <image> [--json]
```

そのイメージを FDSKey が読み込めるかどうかを、カードに書き込む前に判定します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/lint-dark.png">
<img alt="ローカル Web ページの lint コマンド" src="assets/screenshots/lint-light.png">
</picture>

### 品質測定

チェックサムは 65,500 バイトの 1 面について 1 ビットしか答えません。以下はそれ以上を答えます。

#### `reads`

```bash
fdstoolkit reads <images>... [--json]
```

同一の物理ディスクを繰り返し吸い出した結果をブロック単位で比較します。安定度、どのブロックが揺れるか、ビット反転の向きを報告します。磁気的な減衰は磁化の反転を失う方向に働くため、1 が 0 へ落ちます。本ツールはこれを `loss`、逆方向を `gain`、両方を `mixed` と呼びます。

```bash
fdstoolkit reads pass1.fds pass2.fds pass3.fds
```

```
passes        3
stability     99.88%
decay         loss
bits lost     14
bits gained   0
```

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/reads-dark.png">
<img alt="ローカル Web ページの reads コマンド" src="assets/screenshots/reads-light.png">
</picture>

#### `calibrate`

```bash
fdstoolkit calibrate <reference> --read <r>... [--json]
```

信頼できるディスクを基準としてドライブ自身のエラー率を測ります。ディスクのせいをドライブに、あるいはその逆に押し付けないためです。判定は `good`、`marginal`、`faulty` のいずれかです。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/calibrate-dark.png">
<img alt="ローカル Web ページの calibrate コマンド" src="assets/screenshots/calibrate-light.png">
</picture>

#### `grade`

```bash
fdstoolkit grade <image> [--read <r>...] [--map] [--json]
```

根拠となる測定値を添えた評価。`--read` は繰り返し吸い出しを反映します。`--map` はブロックごとの信頼度と、その根拠を表示します。

```bash
fdstoolkit grade disk.fds --read pass2.fds
```

```
clean, confidence 0.97
  ok   errors 0 within 0
  ok   confidence 0.97 within 0.6
  ok   read stability 1 within 1
```

信頼度はチェックサムの状態を出発点とし、読み取りの一致度で補正されます。チェックサムを保存しないコンテナは「疑わしい」ではなく「未証明」として扱われます。ヘッダなし `.fds` が不安定と評価されないのはそのためです。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/grade-dark.png">
<img alt="ローカル Web ページの grade コマンド" src="assets/screenshots/grade-light.png">
</picture>

#### `integrity`

```bash
fdstoolkit integrity <image> [--original-crcs] [--json]
```

すべてのチェックサムを通過しながら内容が誤っているイメージを見つけます。ほぼ全体が未定義オペコードのファイル本体、ヘッダと長さが食い違う本体、そして `--original-crcs` を付けた場合は、本来そうならないはずなのに保存済みチェックサムがすべて正確に再計算できてしまう吸い出し。

オペコードの閾値は実在する 10,105 本のプログラムファイルを基準に較正してあります。これらの中央値は未定義オペコード 36% です。グラフィックやテーブルを日常的に含むためです。したがって、ほぼコードでないファイルだけが報告されます。`SAVEDATA` や `JMP-TBL.` のような名前がここに現れるのは正しい動作です。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/integrity-dark.png">
<img alt="ローカル Web ページの integrity コマンド" src="assets/screenshots/integrity-light.png">
</picture>

### ドライブ調整

ここでのすべての測定はビットレートを基準としており、回転数は使いません。RAM アダプタは 96.4 kbit/s を期待し、許容範囲は 10 パーセントです。ハードウェアが実際に要求しているのはこの数値だけです。この機構の回転数として公表されている値は 2 倍の開きがあり、許容範囲も示されていません。

#### `classes`

```bash
fdstoolkit classes <capture> [--json]
```

`dump --raw` が保存した `raw03` キャプチャを読み込みます。3 種類の長さへの分布と、そのいずれにも入らなかったパルスの数を報告します。

測定の前にギャップの連続を除外します。ギャップとは短いパルスの長い連続であり、含めたままでは分布が「ドライブがどう読んでいるか」ではなく「ディスクがどれだけ埋まっているか」の指標になってしまうためです。残りの部分について、実在する 120 面の中央値は 63.1、27.9、9.0 パーセントで、これを基準値としています。正常なドライブではこの 120 面が -5.4 から +3.0 パーセントに分布するため、閾値は 6 パーセントに置いてあり、どの面もこれに触れません。

知っておくべき制限が 2 つあります。ギャップを除いたパルスが 512 個未満のキャプチャは、判定せず「サンプル不足」として報告します。また、ここで唯一ディスクの内容に依存しない数値は無効パルス数なので、数値どうしが食い違う場合はそちらを信頼してください。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/classes-dark.png">
<img alt="ローカル Web ページの classes コマンド" src="assets/screenshots/classes-light.png">
</picture>

#### `reading`

```bash
fdstoolkit reading <cycles> [--json]
```

ディスク一覧表示ツールが実機の画面に表示する、バイト間の平均 CPU サイクル数を解釈します。FDSStick は時間情報ではなくパルスクラスを送るため、本ツールが行える速度測定はこれだけです。

```bash
fdstoolkit reading 152
```

```
94.20 kbit/s, -2.28% of nominal, in spec
the drive reads slow: raise the motor speed a little, then measure again
```

換算は厳密です。2A03 は 1.7897725 MHz で動作し 1 バイトは 8 ビットなので、サイクル数はそのままレートへ写像されます。バイト間のサイクル数が多いほどディスクは遅く回っています。

助言はモーターの速度を上げるか下げるかだけを示し、半固定抵抗をどちらへ回すかは示しません。本ツールが信頼できる出典に、その向きを示すものがないからです。少しだけ回して測り直し、数値が逆へ動いたら反対に回してください。

| 表示値 | レート | 誤差 |
|---|---|---|
| 146 | 98.07 kbit/s | +1.73% |
| 148 | 96.74 kbit/s | +0.36% |
| 149 | 96.10 kbit/s | -0.32% |
| 152 | 94.20 kbit/s | -2.28% |

厳密な公称値は 148.53 サイクルなので、整数表示は 1 カウントあたり約 0.68% の刻みになります。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/reading-dark.png">
<img alt="ローカル Web ページの reading コマンド" src="assets/screenshots/reading-light.png">
</picture>

### マスターと参照セット

任天堂のマスターイメージは存在しません。ディスクは空の状態で販売され、店頭のディスクライターで書き込まれ、その際に 1 枚ずつ刻印されたからです。したがって同じゲームの 2 本はバイト列が一致しません。マスターに最も近いものは、その刻印を除いたうえで現存するすべての吸い出しが一致する内容です。

#### `masters`

```bash
fdstoolkit masters <corpus> [--profile <name>] [--json]
```

ディレクトリ内のすべての吸い出しの合議により、ゲームごとに 1 つのマスターを作ります。少数意見は隠さず報告します。

```bash
fdstoolkit masters ~/dumps
```

```
profile       release
dumps         595
games         242
unanimous     210 of 242
```

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/masters-dark.png">
<img alt="ローカル Web ページの masters コマンド" src="assets/screenshots/masters-light.png">
</picture>

#### `reference-build`

```bash
fdstoolkit reference-build <corpus> -o <set> --set-version <v> [--profile <name>] [--force]
```

その結果を、何もインストールせずに照合できるダイジェストの集合として公開します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/reference-build-dark.png">
<img alt="ローカル Web ページの reference-build コマンド" src="assets/screenshots/reference-build-light.png">
</picture>

#### `reference-verify`

```bash
fdstoolkit reference-verify <image> --set <set> [--json]
```

`match`、期待されるダイジェストを添えた `mismatch`、または `unknown`。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/reference-verify-dark.png">
<img alt="ローカル Web ページの reference-verify コマンド" src="assets/screenshots/reference-verify-light.png">
</picture>

#### `dat-build`

```bash
fdstoolkit dat-build <corpus> -o <out> --name <n> --set-version <v> [--author <a>] [--force]
```

Logiqx 形式の DAT を出力し、コミュニティが既に使っているツールへ結果を届けます。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/dat-build-dark.png">
<img alt="ローカル Web ページの dat-build コマンド" src="assets/screenshots/dat-build-light.png">
</picture>

#### `consensus`

```bash
fdstoolkit consensus <images>... -o <out> [--map] [--force]
```

同一ディスクの複数の吸い出しを、ブロック単位の多数決で統合し、一致しなかった箇所をすべて報告します。`--map` はブロックごとの一致度を表示します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/consensus-dark.png">
<img alt="ローカル Web ページの consensus コマンド" src="assets/screenshots/consensus-light.png">
</picture>

### ハードウェア

#### `dump`

```bash
fdstoolkit dump -o <out> [--sides N] [--passes N] [--retries N] [--raw <dir>] [--yes] [--force]
```

ディスクを読み取ります。`--passes` は各面を複数回読み、`--retries` はブロックごとの再試行回数を決め、`--raw` はドライブが返したパルスキャプチャをすべて保存します。

一度に片面しか読めないドライブは、面を選択できません。そうしたバックエンドで複数面を読む場合、読み取りの合間にディスクを裏返すよう求め、同じ面を二度読むくらいなら処理を中止します。`--yes` はその確認に自動で答えます。2 回目の読み取りが 1 回目と同じバイト列を返した場合、吸い出しは失敗し、何も書き出しません。裏返されなかったディスクは、両面を吸い出したように見えて実際はそうでないファイルを生むからです。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/dump-dark.png">
<img alt="ローカル Web ページの dump コマンド" src="assets/screenshots/dump-light.png">
</picture>

#### `write`

```bash
fdstoolkit write <image> [--backup <p>] [--retries N] [--yes]
```

ディスクへ書き込み、読み戻して比較します。`--backup` は書き込む前に現在の内容を保存します。`--yes` がなければ確認を求めます。

FDSStick は、ディスクが書き込み禁止かどうかも、電池が保っているかどうかも、そもそもディスクが入っているかどうかも報告しないため、本ツールは書き込み前にそれらを確認できません。その代わりにディスクを守るのは書き込みの前後の手順です。`--backup` を指定すれば先に現在の内容を保存し、`--yes` を指定しない限り開始前に確認し、書き込み後にはすべてを読み戻して書き込むはずだった内容と比較します。書き込みを受け付けなかったディスクは、そこで不一致として現れます。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/write-dark.png">
<img alt="ローカル Web ページの write コマンド" src="assets/screenshots/write-light.png">
</picture>

#### `surface`

```bash
fdstoolkit surface [--sides N] [--passes N] [--quick] [--finish leave|blank|erase] [--backup <p>] [--yes]
```

互いに補完的なパターンを書いては読み戻し、不要ディスクの状態を評価します。多重書き込みによるディスク消去の磁気版にあたり、すべてのビットセルを両方向へ強制的に反転させたうえで、戻ってきた内容を検証します。

1 巡で `0x00`、`0xFF`、`0xAA`、`0x55` の 4 パターンを順に書きます。前の 2 つはすべてのセルをそれぞれの飽和状態へ追い込み、片方の極性しか保持できない弱ったセルを露出させます。後の 2 つはビット単位で交互に切り替わるため、一様なパターンでは到達できない隣接セル間の干渉を露出させます。各パターンは次を書く前に読み戻して比較されます。

既定では面をトラックの物理的な限界まで埋めます。66,560 バイトのギャップ込みバッファに対して 32 ブロック、データ 59,145 バイトです。残りはブロック間ギャップであり、いずれにせよ各パスでドライブが書き直すため、表面全体が走査されます。`--quick` は代わりに 4 KiB のファイルを 1 つだけ書き、トラックの 12% を対象とします。判定のためではなく、手早い確認のための指定です。

`--passes N` は 4 パターンの巡回全体を繰り返します。死んだセルは毎回失敗し、境界にあるセルはそうならないため、両者を切り分ける手段がこの繰り返しです。

失敗したブロックは、失敗した回数によって分類されます。

| 分類 | 意味 |
|---|---|
| hard | 複数のパターンで失敗。その位置の磁性面そのものが失われています |
| transient | 1 回だけ失敗。死んではおらず、境界にあります |
| recovered | 初期のパスで失敗し、以降のすべてのパスで正常に読めた。書き直しによって磁化が整え直されました |

recovered の数が、修復にあたる部分です。閾値へ近づいていたセルを書き直すとマージンが回復するため、失敗から始まって最後には正常になったディスクは、測定されただけでなくリフレッシュされたことになります。ただし吸い出しの代わりにはなりません。各パスは既存の内容を破壊するので、先に `--backup` でディスクを保存してください。

`--finish` は、テスト終了時にディスクへ何を残すかを決めます。

| 値 | 残すもの |
|---|---|
| `leave` | 最後に書いたパターン `0x55`。既定値です |
| `blank` | 工場出荷状態の面。ディスク情報ブロックとファイル数 0 のみで、店頭で購入した未書き込みディスクとバイト単位で同一です |
| `erase` | ブロックを一切残さないため、アダプタは何も読み取れません |

消去の後に有用なのは `blank` です。出力されるバイト列は `blank --formatted` と同一であり、ディスクは出荷時の状態で保管でき、書き込みソフトからは未使用の媒体として扱われます。

```bash
fdstoolkit surface --sides 2 --passes 3 \
    --backup before.fds --finish blank --yes
```

```
59145 data bytes per side, 100.0% of the physical track, 3 pass(es) of 4 patterns
pass 1 pattern 0x00: held
...
2 block(s) failed once, marginal rather than dead
2 block(s) failed early and read clean after, so rewriting refreshed them
left the disk formatted as it leaves the kiosk, verified
grade clean
```

すべてのパターンが保持され、かつ終了処理が検証できた場合にのみ終了コード 0 を返します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/surface-dark.png">
<img alt="ローカル Web ページの surface コマンド" src="assets/screenshots/surface-light.png">
</picture>

#### `web`

```bash
fdstoolkit web [--host <h>] [--port N] [--no-open]
```

ローカルのウェブインターフェースを開きます。上記のすべてのコマンドがそこから利用でき、各ルートはコマンドが呼ぶものとまったく同じ処理を呼び出します。`--no-open` はブラウザを開かずにサーバーだけを起動します。SSH 越しに使う場合はこちらです。既定では `127.0.0.1:8000` を待ち受けます。

## ウェブインターフェース

```bash
fdstoolkit web
```

`web` はブラウザでページを開きます。`fdstoolkit web --no-open` はブラウザを開かずにサーバーだけを起動します。SSH 越しに使う場合はこちらです。ヘッドレス専用のコマンドはありません。本ツールはこの端末に接続されたハードウェアを操作するものであり、公開サービスになることはないからです。

既定では `127.0.0.1:8000` を待ち受けます。これはサービスではありません。`--host` を指定しない限り公開インターフェースでは待ち受けず、ページは外部リソースを一切読み込まないため、データがこの端末から出ることはありません。

この設計が拠って立つ原則は、ウェブ層は何も判断しない、という一点です。各ルートはペイロードを解析し、コマンドが呼ぶのと同じ関数を呼び、返ってきたものを報告するだけです。ページ経由で求めた評価は、`grade` が表示するものと同じ信頼度と同じ根拠を持ちます。同じ呼び出しだからです。これは主張ではなく検証されています。テストは、同じ入力に対するルートの答えとコマンドの答えを突き合わせます。

| ルート | 対応するコマンド |
|---|---|
| `GET /api/catalogue` | プロファイル、形式、出力先の一覧 |
| `GET /api/doctor` | `doctor` |
| `POST /api/info` | `info` と `ls` |
| `POST /api/verify` | `verify` |
| `POST /api/hash` | `hash` |
| `POST /api/grade` | `grade` |
| `POST /api/reads` | `reads` |
| `POST /api/reading` | `reading` |
| `POST /api/classes` | `classes` |
| `POST /api/blank` | `blank` |
| `POST /api/canon` | `canon` |
| `POST /api/convert` | `convert` |

イメージとキャプチャは base64 で符号化してリクエストボディに載せます。`GET /docs` は生成された API リファレンスを提供するため、このページはエンドポイントの唯一の利用者ではなく、その 1 つにすぎません。

ページが提示する選択肢は `catalogue` から取得され、これは列挙型の上に構築されています。モデルにプロファイルを追加すれば、二度目の編集をせずともページに現れます。

`dump`、`write`、`surface` はこの端末に接続された FDSStick を操作します。接続されていない場合は 409 を返して原因を示し、`write` と `surface` はリクエストが消去を確認するまで開始しません。

インターフェースは英語と日本語で提供されます。両方の辞書は同じキーを持ち、テストスイートがそれを信用ではなく検証します。マークアップまたはスクリプトが参照するキーは両方に存在しなければならず、日本語側に英語のまま残った文字列があってはなりません。

## 手順

### ディスクを保存する

1 回の吸い出しは、ドライブが 1 度何を読んだかを示すだけです。2 回でようやく、同じものを 2 度読めたかが分かります。

```bash
fdstoolkit dump -o pass1.fds --raw captures/
fdstoolkit dump -o pass2.fds
fdstoolkit reads pass1.fds pass2.fds
fdstoolkit grade pass1.fds --read pass2.fds
```

2 つが食い違う場合、`consensus` が多数決で統合し、決着しなかったブロックをすべて列挙します。一方の吸い出しで壊れているブロックが他方で正常なら、`splice` がそれを取り込みます。

### ドライブを調整する。粗調整から微調整へ

1. 何よりも先にヘッドを清掃してください。汚れは媒体の不良として現れます。
2. 実機でディスク一覧表示ツールを動かし、サイクル数を読み取って `reading` に渡します。指示どおりにモーターの速度を少しずつ上げ下げし、そのままでよいと言われるまで繰り返します。
3. 正常と分かっているディスクを `--raw` 付きで吸い出し、保存したキャプチャに `classes` をかけます。分布が glitching や shifted なら、ドライブはまだ 3 種類のパルス長をうまく分けて読めていません。
4. 読み取りが難しいと分かっているディスクで確認します。コミュニティでは 39 ファイルを含む特定の面が使われており、チェックサムエラーなしに 39 個すべて読めれば合格です。

### ドライブとディスクのどちらが原因かを判断する

1 枚のディスクではこの問いに答えられません。複数枚を読んで、どこで失敗したかを比べてください。どのディスクでも同じ場所で失敗するならドライブ、1 枚だけで起きるならそのディスク、ドライブが応答しなくなるならそのどちらでもありません。最後の場合の正しい対応は、別のディスクを入れて試すことではなく、中止することです。

### 参照セットを作る

```bash
fdstoolkit masters ~/dumps
fdstoolkit reference-build ~/dumps -o fds-reference.json --set-version 2026-09-22
fdstoolkit reference-verify mine.fds --set fds-reference.json
```

## フォーマット

1 面はブロックの並びです。

| ブロック | コード | 長さ | 内容 |
|---|---|---|---|
| ディスク情報 | `0x01` | 56 | 検証文字列、ゲームコード、日付、ディスクライターの刻印 |
| ファイル数 | `0x02` | 2 | 宣言されたファイル数 |
| ファイルヘッダ | `0x03` | 16 | 番号、ID、名前、ロードアドレス、サイズ、種別 |
| ファイル本体 | `0x04` | 1 + サイズ | ファイルそのもの |

| コンテナ | 1 面のサイズ | チェックサム | 備考 |
|---|---|---|---|
| `.fds` ヘッダなし | 65500 | なし | No-Intro がハッシュを取る対象 |
| `.fds` fwNES ヘッダ付き | 16 + 面ごとに 65500 | なし | ヘッダが面数を保持します |
| `.qd` | 65536 | あり | バーチャルコンソールの吸い出しと Quick Disk のダンプ |
| FDSKey カードファイル | 65500 | なし | ファームウェアの制約内でヘッダなし |
| コピアの面別ファイル | 面ごとに 1 つ | 場合による | 面が公称長を超えることがあります |
| ares の面別ファイル | 73728 | あり | ギャップと同期マークを含みます |
| パック済みパルスクラス、`raw03` | 可変 | あり | 1 パルスにつき 2 ビット、FDSStick が量子化済み |

各変換で失われるもの。

| 変換元 | 変換先 | 失われるもの |
|---|---|---|
| `.fds` ヘッダ付き | `.fds` ヘッダなし | 宣言された面数 |
| `.qd` | `.fds` | 保存されていたチェックサムすべて |
| `.fds` | `.qd` | なし。ただしチェックサムは合成されます |
| 任意 | 正規化形式 | プロファイルが除外するものすべて |

## 終了コードとスクリプト化

`0` は異常なし、`1` は異常ありを意味します。何を異常とみなすかはコマンドごとに異なり、上に記載してあります。`splice` なら修復できなかったブロック、`masters` なら合議が割れたゲーム、`reading` なら微調整の範囲外にあるドライブ、`reference-verify` なら不一致です。

報告を行うコマンドはすべて `--json` を受け付け、その JSON は人間向け出力と同じデータです。ファイルを書き出すコマンドは `--force` なしに上書きしません。

```bash
fdstoolkit verify disk.fds --json | jq -r '.findings[] | "\(.code) \(.message)"'
fdstoolkit masters ~/dumps --json | jq '.contested[].game'
fdstoolkit reading 152 --json | jq -r '.advice'
```

## このツールにできないこと

**ディスクシステムのフラックスキャプチャは存在しません。** Quick Disk はインデックス穴も標準的なステッピングも持たない 1 本の連続した渦巻きであり、KryoFlux や Greaseweazle はこの媒体を読むことができません。本ツールが読み込むのは FDSStick が生成するものだけです。

**FDSStick ではドライブの速度を測定できません。** この機器はハードウェアの側で各パルスを 3 種類の長さのいずれかへ丸め、時間情報ではなくクラスを送ってきます。速度は `reading` による実機側の読み取りから得る必要があります。

**ヘッドの位置合わせはパルスクラスからは測定できません。** 信号振幅か、複数のディスクにまたがるエラー密度の比較が必要です。

**ベルトの不良とモーターの不良は切り分けられません。** プーリー比が必要ですが、信頼できる出典がその値を示していません。

## 貢献

開発環境の構築、テストスイート、リリース手順は [CONTRIBUTING.md](CONTRIBUTING.md) にあります。

## ライセンス

MIT です。[LICENSE](LICENSE) を参照してください。

---

<div align="center">

ファミコン ディスクシステム / ディスクカード の保存、吸い出し、ディスク品質の測定、
ドライブの調整、ベルト交換、モーター回転数の調整、FDSStick、FDSKey、No-Intro への提出。

English documentation: <a href="README.md">README.md</a>

</div>
