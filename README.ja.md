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

コマンドは **27** 個で、`doctor` 以外はローカルの Web ページからも使えます。テストは Python が **1,323** 件、ページが **132** 件、行と分岐の網羅率は **100%**。同一性は **595** 枚のイメージ、空ディスクの値は一度も書き換えられていない **1,729** 面から測定しています。

---

ファミコン ディスクシステムのディスクカードを扱うためのコマンドラインツールです。読み取り、品質の測定、再構成、書き戻し、そしてそれらを行うドライブ自体の調整までを対象とします。

これは製品ではなく計測器です。ディスク情報ブロックが何かを理解しており、ドライブを開けて半固定抵抗を回すことを厭わず、判定だけでなく測定値そのものを見たい人を想定しています。報告を行うコマンドはすべて `--json` を受け付けます。異常がなければ終了コード 0、あれば 1 を返すため、シェルスクリプトに組み込めます。

## 目次

- [インストール](#インストール)
- [先に把握しておく概念](#先に把握しておく概念)
- [コマンドリファレンス](#コマンドリファレンス)
  - [検査](#検査)
  - [確認](#確認)
  - [修復](#修復)
  - [コンテナ](#コンテナ)
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

**FDSStick のキャプチャが持つのは時間情報ではなくパルスクラスです。** この機器はハードウェアの側で各パルスを 3 種類の公称長のいずれかへ丸め、`dump --raw` はそのクラスを `raw03` ファイルとして保存します。パルスは時間の長さを持ちませんが、長さのクラスは持ちます。そしてディスク上のバイトが、各パルスがどのクラスになるべきかを正確に決めます。そのため同じディスクのイメージと比べると、内容が求めるより 1 クラス短く読まれたパルスはドライブが速すぎること、1 クラス長く読まれたパルスは遅すぎることを意味します。これを数えるのが `calibrate speed` です。1、2 パーセントずれたドライブでもすべてのパルスは正しく分類されるので、調整の最後の詰めには実機側の速度テストかストロボが必要です。

**保存したキャプチャは、ドライブが見たとおりのディスクです。** `dump --raw <dir>` は各面のすべての読み取りを `side{S}.read{NN}.raw03` として書き出し、あわせて `manifest.json` に、各ファイルの面、読み取り番号、サイズ、SHA-256、元のイメージ、保存日時を記録します。Web ページは同じ一式を 1 つの zip として返します。`--captures` を受け付けるコマンドはどちらの形式も読み、ダイジェストが一致しなくなったファイルは拒否します。そのため一式は何年でも保管でき、ディスクなしで読み直せます。どのパルスにもクラスが付いているので、読み取りの誤りは 1 つのパルスのクラス違いであり、パルスが増えたり欠けたりすることはありません。それぞれ別の場所を読み違えた 3 回の読み取りは、投票によってディスク上のパルスへ戻せます。

**1 本のゲームは 1 枚のディスクです。** どのゲームも片面または両面の 1 枚のディスクを使い、2 枚目にまたがるゲームはありません。3 面以上を持つイメージは複数のディスクを 1 つにまとめたものであり、すべてのコマンドがこれを拒否します。

## コマンドリファレンス

記法: `<>` は値、`[]` は省略可、`...` は繰り返しです。

### 検査

#### `info`

```bash
fdstoolkit info <image> [--files] [--json]
```

面数、ゲームコード、製造日と書き換え日、ディスクライターのシリアル、宣言されたファイル数と実際のファイル数、隠しファイル、末尾の余剰データ。`--files` を付けると、全面のすべてのファイルも一覧にします。番号、ID、名前、ロードアドレス、種類、サイズ、そして宣言数を超えた位置にあるかどうかです。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/info-dark.png">
<img alt="ローカル Web ページの info コマンド" src="assets/screenshots/info-light.png">
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

#### `hash`

```bash
fdstoolkit hash <image> [--profile <name>] [-o <out>] [--force] [--json]
```

イメージ全体と各面の CRC32、MD5、SHA-1、SHA-256、加えて正規化ダイジェストと RetroAchievements の MD5。正規化ダイジェストは、書き換え日や書き換え回数のように自然に変わる部分を無視するので、同じゲームの 2 本は、どちらかが店頭で書き換えられていても一致します。`--profile` はどこまで無視するかを選びます。`-o` を付けると、それらのフィールドを固定値にしたディスク、つまり正規化したイメージも書き出します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/hash-dark.png">
<img alt="ローカル Web ページの hash コマンド" src="assets/screenshots/hash-light.png">
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

### 確認

チェックサムは 65,500 バイトの 1 面について 1 ビットしか答えません。以下はそれ以上を答えます。

#### `verify`

```bash
fdstoolkit verify <image> [--strict] [--json]
```

構造とチェックサムの検出結果を、それぞれコード付きで報告します。`--strict` は警告でも失敗とします。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/verify-dark.png">
<img alt="ローカル Web ページの verify コマンド" src="assets/screenshots/verify-light.png">
</picture>

#### `grade`

```bash
fdstoolkit grade <image> [--read <r>...] [--captures <bundle>] [--map] [--json]
```

根拠となる測定値を添えた評価。`--read` は繰り返し吸い出しを反映し、`--captures` は保存したキャプチャ一式が示す弱いブロックを数えます。`--map` はブロックごとの信頼度と、その根拠を表示します。弱いブロックが 1 つでもあれば評価は marginal に留まります。読み取りごとにパルスが揺れるブロックこそ、次に壊れるブロックだからです。

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

#### `reads`

```bash
fdstoolkit reads <images>... [--json]
fdstoolkit reads --captures <bundle> [--json]
```

同一の物理ディスクを繰り返し吸い出した結果をブロック単位で比較します。安定度、どのブロックが揺れるか、ビット反転の向きを報告します。磁気的な減衰は磁化の反転を失う方向に働くため、1 が 0 へ落ちます。本ツールはこれを `loss`、逆方向を `gain`、両方を `mixed` と呼びます。

`--captures` を付けると、同じ問いを 1 層下で問います。吸い出しどうしが食い違うのは、ブロックがすでにチェックサムで失敗したあとだけです。保存したキャプチャなら、すべてのブロックがまだ正しく読めているうちに、読み取りごとに揺れるパルスが見えます。弱いブロックごとに、揺れたパルスの数、無効なパルスの数、そのブロックをまったく見つけられなかった読み取りの数を示し、見つけられなかった読み取りのあるブロックを先に並べます。

```bash
fdstoolkit reads --captures captures/
```

```
saved reads   3
weak blocks   1
side 0 block 3 (file data): 1 pulse(s) differ across 3 read(s), 0 invalid
```

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

#### `diff`

```bash
fdstoolkit diff <a> <b> [--explain] [--json]
```

どのブロックが異なるか。`--explain` はブロック番号ではなくディスク情報のフィールド名とファイル名で示します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/diff-dark.png">
<img alt="ローカル Web ページの diff コマンド" src="assets/screenshots/diff-light.png">
</picture>

### 修復

#### `rebuild`

```bash
fdstoolkit rebuild <image> -o <out> [--keep-tail] [--reveal-hidden] [--drop-hidden] [--renumber] [--force]
```

解析済みのモデルから再出力します。チェックサムを再計算し、宣言サイズを訂正し、末尾の余剰データを落とします。隠しファイルは既定で保持されます。`--reveal-hidden` は宣言数を実数に合わせ、`--drop-hidden` は削除します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/rebuild-dark.png">
<img alt="ローカル Web ページの rebuild コマンド" src="assets/screenshots/rebuild-light.png">
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

#### `insert`

```bash
fdstoolkit insert <image> --file <f> --name <n> -o <out> [--address <hex>] [--kind program|character|nametable] [--side N] [--force]
```

ファイルを追加し、宣言ファイル数を増やします。`--address` の既定値は `6000` です。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/insert-dark.png">
<img alt="ローカル Web ページの insert コマンド" src="assets/screenshots/insert-light.png">
</picture>

#### `extract`

```bash
fdstoolkit extract <image> -d <dir> [--force]
```

宣言数を超えた位置にあるファイルも含め、すべてのファイルを書き出します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/extract-dark.png">
<img alt="ローカル Web ページの extract コマンド" src="assets/screenshots/extract-light.png">
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

#### `consensus`

```bash
fdstoolkit consensus <dumps>... -o <out> [--captures <bundle>] [--map] [--json] [--force]
fdstoolkit consensus --captures <bundle> -o <out> [--json] [--force]
```

1 枚のディスクの吸い出しを複数受け取り、ブロックごとの多数決で 1 つのイメージに統合し、吸い出しどうしが一致しなかったブロックをすべて報告します。`--map` はブロックごとの一致度を表示します。

`--captures` は、保存したキャプチャ一式からパルス投票でディスクを再構成します。どの読み取りも正しく読めなかったブロックについて、そこに届いた各読み取りのパルスを 1 つずつ比べ、多数派を残します。そのブロックの読み取りが 3 回必要で、すべての読み取りが同じ場所を読み違えたブロックは直りません。共通の誤りを投票で覆すことはできないからです。単独で使うと再構成したディスクが出力となり、直せなかったブロックをすべて列挙します。吸い出しと合わせると、再構成したディスクが投票者の 1 つとして加わります。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/consensus-dark.png">
<img alt="ローカル Web ページの consensus コマンド" src="assets/screenshots/consensus-light.png">
</picture>

#### `save`

```bash
fdstoolkit save find <dumps>... [--json]
fdstoolkit save apply <image> --save <s> -o <out> [--force]
fdstoolkit save extract <image> --played <p> -o <out> [--format ips|ups|image] [--force]
fdstoolkit save blank <image> --recipes <r> -o <out> [--force]
```

ゲームが進行状況を書き込むファイルに関することを、4 つの操作で扱います。

| 操作 | 内容 |
|---|---|
| `find` | 同じリリースの吸い出しを比べ、違いのあるファイル、つまりセーブを示します |
| `apply` | IPS、UPS、BPS、またはイメージ全体のセーブをイメージに書き戻します |
| `extract` | 未使用のディスクとプレイ済みのディスクの差分をセーブとして書き出します |
| `blank` | 宣言されたセーブ領域を埋め、プレイ済みの 2 本が一致して比較できるようにします。`--recipes` はどの領域がセーブかを宣言するファイルで、必須です。どのバイトをゲームが書き換えるかを本ツールが推測することはありません |

各操作は必要なものを確かめ、足りないものを伝えます。`apply` には `--save`、`extract` には `--played`、`blank` には `--recipes` が必要で、`find` 以外の 3 つはファイルを書き出すので `-o` も必要です。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/save-dark.png">
<img alt="ローカル Web ページの save コマンド" src="assets/screenshots/save-light.png">
</picture>

### コンテナ

#### `convert`

```bash
fdstoolkit convert <image> -o <out> [--header|--no-header] [--crc-mode preserve|compute|null] [--force]
```

`.fds` と `.qd` の相互変換。`--crc-mode` は `.qd` を書くときに CRC フィールドへ何を入れるかを決めます。元の値を保持するか、再計算するか、ゼロにするか。既定が `preserve` なのは、再計算を伴う往復変換が、調査対象かもしれない破損を黙って修復してしまうからです。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/convert-dark.png">
<img alt="ローカル Web ページの convert コマンド" src="assets/screenshots/convert-light.png">
</picture>

#### `export`

```bash
fdstoolkit export <image> --target <t> -d <dir> [--force]
```

機器やエミュレータが期待するディレクトリ構成で書き出します。対象は `nt-mini`、`mister`、`everdrive-n8-pro`、`mesen2`、`fceux`。いずれもヘッダなしの `.fds` を書き出します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/export-dark.png">
<img alt="ローカル Web ページの export コマンド" src="assets/screenshots/export-light.png">
</picture>

#### `blank`

```bash
fdstoolkit blank -o <out> [--sides 1|2] [--formatted] [--header] [--game-name ABC] [--force]
fdstoolkit blank --calibration -o <out> [--header] [--force]
```

空のイメージ。`--formatted` は、一度も書き換えられていない 1,729 面から実測した値でディスク情報ブロックを書きます。国コード `49`、シリアル `ffff`、書き換え回数 `00`、フィラー `ff`。

`--calibration` は代わりにキャリブレーション用ディスクを作ります。すべてのパルスがあらかじめ分かるように作った 2 面で、`calibrate` が自動で認識します。各面は長、中、混在、長、中、混在の順に 6 ファイルを収めるので、どのパターンも面の始まり近くと終わり近くの両方にあります。

| ファイル | バイト列 | ディスクに載るもの |
|---|---|---|
| `CAL-LNG` | `aa` の繰り返し | 99.8 パーセントが長いパルス |
| `CAL-MED` | `24 49 92` の繰り返し | 99.9 パーセントが中くらいのパルス |
| `CAL-MIX` | 長 48 バイト、中 48 バイト、`00` 16 バイトの繰り返し | 3 つのクラスすべてと、その間の切り替わり |

パターンは本ツールの分類境界から導いたものです。長いパルスは、ほかのどのクラスよりも下側の境界に近いので、速すぎるドライブはまず長いパルスが中として読まれる形で現れます。中くらいのパルスは上側の境界に最も近いので、遅すぎるドライブはまず中が長として読まれる形で現れます。スティック自身のハードウェアの境界は公開されていないため、この順序は本ツールのデコーダの性質であり、スティックを測定したものではありません。

各面のブロックは 53,854 バイトです。この大きさは形式から取った値ではなく実測に基づきます。`.fds` ファイルは 1 面に 65,500 バイトを確保しますが、工場で書き込まれた 345 面では中央値が 50,350 バイト、最大が 54,958 バイトで、95 パーセントが 53,910 バイト以下でした。その範囲に収めることで、最後のファイルがトラックの終わりを越えず、物理的な面に載ります。

```
wrote calibration.fds (131000 bytes)
write it only on a drive you trust, with write --calibration --trusted-drive, which lists every adjustment that drive needs first
```

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

### ハードウェア

#### `status`

```bash
fdstoolkit status [--json]
```

FDSStick が接続されているか、それが自身について何を報告するか、そして開けるかどうかを、`doctor` と同じ確認だけを使って示します。スティックが伝えられないこと、つまりディスク自体については何も分からないことも併せて示します。

```
hardware support  hidapi is installed
fdsstick          none connected at 16D0:0AAA. Connect the FDSStick over USB before dumping or writing [warning]
the stick reports nothing about the disk itself: not whether one is inserted, whether it is write protected, or whether the battery holds
```

すべての確認が通った場合にのみ終了コード 0 を返します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/status-dark.png">
<img alt="ローカル Web ページの status コマンド" src="assets/screenshots/status-light.png">
</picture>

#### `doctor`

```bash
fdstoolkit doctor [--json]
```

バージョン、Python、プラットフォーム、ハードウェア対応の導入状況、接続されているデバイスとそれを開けるか、そしてコーデックと同一性プロファイルが自己テストに通るか。挙動がおかしいときは最初にこれを実行してください。


#### `dump`

```bash
fdstoolkit dump -o <out> [--sides N] [--passes N] [--retries N] [--raw <dir>] [--yes] [--force]
```

ディスクを読み取り、出力のファイル拡張子に応じて `.fds` または `.qd` として保存します。`.qd` は各ブロックがディスク上で持っていたチェックサムを保つため、一度も正しく読めなかったブロックはその中でも不良のまま見分けられます。`--passes` は各面を複数回読み、`--retries` は不良ブロックのある面をあと何回まで読み直すかを決め、`--raw` はドライブが返したパルスキャプチャをすべて、ほかのコマンドが読み戻せる一式として保存します。吸い出しが失敗したときや中断したときも、この一式は保存されます。キャプチャが意味を持つのは、まさに読めなくなりつつあるディスクだからです。

すべての読み取りで失敗したブロックも、そこで諦めはしません。それらの読み取りのキャプチャを `consensus --captures` と同じパルス投票にかけ、投票で再構成できたブロックはイメージに書き込み、専用の行で示し、評価は clean ではなく marginal に留めます。1 回だけ読んだディスクは面ごとにキャプチャが 1 つしかないので、投票の材料がそろうのは `--retries` か `--passes` を使ったときです。

ドライブは 1 ブロックだけを読むことができないため、再試行は毎回その面全体の読み直しになります。予算がブロックごとではなく面ごとなのはそのためです。1 回の読み直しで、まだ失敗しているブロックすべてを解決します。不良ブロックが 10 個ある面でも、追加の読み取りは最大で `--retries` 回であり、その 10 倍にはなりません。読み直したブロックは位置ではなく種別とファイル番号で照合するため、損傷したブロックが読み直しで消えても、後続のブロックがずれることはありません。読み直しでようやく正しく読めたブロックは、ディスクが劣化している兆候として数えます。面が宣言するファイルに届く前に終わった読み取りも未完了とみなし、同じ予算の範囲で読み直します。宣言したファイルに最後まで届かなかった面は、届いた最後のブロックを示して失敗と判定します。ディスク情報が反対側の面を示している面も明示します。多くの場合、ディスクが逆のラベルを上にして入っていることを意味するからです。`write` も書き込む前に同じことを伝えます。拒否ではなく注意にとどめるのは、片面のゲームを 2 本書き直したディスクでは、両面が正当に A 面のディスク情報を持つからです。

ヘッドはディスクの下にあり、下を向いた面だけを読むので、ドライブは面を選択できません。どの問いかけも面をラベルで示し、そのラベルは上を向き、ヘッドはその面を下から読みます。そのため複数面を読む場合、読み取りの合間にディスクを裏返すよう求め、同じ面を二度読むくらいなら処理を中止します。`--yes` はその確認に自動で答えます。2 回目の読み取りが 1 回目と同じバイト列を返した場合、吸い出しは失敗し、何も書き出しません。裏返されなかったディスクは、両面を吸い出したように見えて実際はそうでないファイルを生むからです。

すべての読み取りと書き込みには期限があります。まだ何も測定していない段階では 1 面につき 20 秒、最初の面を読んだ後は、その面にかかった時間の 3 倍を上限とし、2 秒を下回ることはありません。期限を過ぎた面はコマンドを止め、デバイスを閉じ、再試行もしません。一度止まったドライブで続けても、ディスクを傷めるだけだからです。止まった吸い出しはファイルを書き出しません。止まった書き込みは、面が書きかけの可能性があると伝えます。何が書き込まれたかは、改めて吸い出さなければ分からないからです。アダプタが期待するレートなら 1 面は約 5.5 秒で読めます。これらの上限は実測したドライブではなくこの数値から決めたもので、実機で最初に見直すべき値です。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/dump-dark.png">
<img alt="ローカル Web ページの dump コマンド" src="assets/screenshots/dump-light.png">
</picture>

#### `write`

```bash
fdstoolkit write <image> [--backup <p>] [--retries N] [--long-side] [--yes]
fdstoolkit write --calibration --trusted-drive [--backup <p>] [--retries N] [--yes]
```

ディスクへ書き込み、読み戻して比較します。`--backup` は書き込む前に現在の内容を保存します。`--yes` がなければ確認を求めます。

測定した工場製 345 面のうち最長の 54,958 バイトを超えるブロックを持つ面は、最後のファイルがトラックの終端からはみ出す恐れがあるため、何も書かずに拒否します。`--long-side` を付けると書き込みます。読み戻しでは、イメージより後ろにディスク上の古いデータが残っていれば失敗とします。読み取り側はそこにある古いブロックを隠しファイルと受け取るからです。

`--calibration` は `blank` の項で説明したキャリブレーション用ディスクを両面に書き込み、ディスクを 1 回裏返します。完全に検証を通ったディスクで長く害を残しうる唯一の書き込みです。調整のずれたドライブは、自分では読めて他のドライブでは読めないディスクを書き、そのディスクは調整に使うすべてのドライブに同じずれを教えてしまいます。そのためコマンドは最初に、そのドライブが済ませているべきことを表示し、`--trusted-drive` で確認しない限り書き込みを拒否します。

1. 読み取りヘッドを清掃します。汚れは媒体の不良として現れます。
2. スピンドルハブを、1.5 mm の六角ねじで固定する工場出荷時の位置に戻します。ずれているとエラー 22 と 27 が出ます。
3. 読み取りヘッドを調整します。公開値は、ヘッドの遠い側の縁がスピンドル中心から 35.5 mm、許容差は約 0.05 mm です。工場出荷のディスクで `calibrate head --bracket` を使い、正しく読める範囲の中央に合わせます。
4. 工場出荷のディスクで `calibrate speed` を使い、正しく読めるまでモーターの速度を調整します。
5. 速度の仕上げは本体側で行います。Copy Master の速度テストは、ディスクを入れた状態で 5 を示すべきで、2 回実行します。代わりにディスクテーブル軸のストロボも使えます。
6. 工場出荷のディスク 3 枚で、すべての面を、複数パス確認します。
7. 書き込んだ後、新しいディスクを別のドライブで読んでから信頼します。

どの手順も `calibrate` の項に出典があります。本ツールはどれも確認できないため、確認するのはコマンドではなくあなたです。

FDSStick は、ディスクが書き込み禁止かどうかも、電池が保っているかどうかも、そもそもディスクが入っているかどうかも報告しないため、本ツールは書き込み前にそれらを確認できません。その代わりにディスクを守るのは書き込みの前後の手順です。書き込む前に面を 1 回だけ読み、その 1 回の読み取りが `--backup` で保存するバックアップであり、書き込み後の確認の基準にもなります。`--yes` を指定しない限り開始前に確認し、書き込み後にはすべてを読み戻して書き込むはずだった内容と比較します。読み戻した内容が書き込み前の読み取りとまったく同じなら、ディスクは書き込みを受け付けていません。その場合、コマンドは不一致のブロックを列挙するのではなく、その旨を伝えて中止します。

両面のイメージでは、ディスクを 1 回だけ裏返します。A 面を読み、書き、読み戻したあと、コマンドはディスクを裏返すよう求め、B 面に同じことを行います。B 面の最初の読み取りは、ディスクが本当に裏返されたかの確認も兼ねています。直前に A 面へ書いた内容が返ってきた場合、ヘッドはまだ A 面にあるので、コマンドはそこへ何も書かずに止まります。バックアップは各面を読むたびに保存し直すため、B 面で止まった書き込みでも、元の A 面はバックアップファイルに残ります。

```bash
fdstoolkit write game.fds --backup before.fds
```

```
overwrite the disk in the drive with 2 side(s) of new data, destroying whatever it holds now [y/N]: y
  reading side 0 before writing it
  writing side 0
  reading side 0 back
turn the disk over so the side B label faces up, then confirm. The head sits under the disk and reads side B from the face turned down, so this drive cannot select a side on its own [y/N]: y
  reading side 1 before writing it
  writing side 1
  reading side 1 back
verified True, grade clean
  verified on this drive only: a drive with misaligned heads writes disks that it reads back and other drives cannot, so read the disk on a second drive before trusting it
```

2 文字分字下げされた行は進行状況で、各手順の開始時に表示されます。そのため、時間のかかる面も終わってからではなく、実行中に見えます。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/write-dark.png">
<img alt="ローカル Web ページの write コマンド" src="assets/screenshots/write-light.png">
</picture>

#### `surface`

```bash
fdstoolkit surface [--sides N] [--passes N] [--quick] [--finish leave|blank|erase] [--backup <p>] [--yes]
```

ドライブが記録できるすべての長さのパルスを書いては読み戻し、不要ディスクの状態を評価します。あわせて、磁性面の劣化とドライブの調整ずれを見分けます。

ディスクが記録するのは磁束反転であり、データは反転の間隔に宿ります。アダプタはすべての間隔を 3 種類の長さに分類するため、バイトパターンが意味を持つのは、それが生む間隔を通してだけです。ドライブ自身のエンコーダで測ると、`0x00` と `0xFF` はどちらも短い間隔だけを書き、`0xAA` と `0x55` はどちらもほぼ長い間隔だけを書きます。この 4 バイトで組んだ巡回は 2 種類を 2 回ずつ書き、中間の間隔を一度も書きません。

1 巡で次の 4 パターンを順に書き、各パターンは次を書く前に読み戻して比較されます。

| パターン | 書くもの | 露出させるもの |
|---|---|---|
| unique data | 巡ごとに新しく生成する 16 バイトの鍵から SHAKE-256 で得たバイト列。ファイルごと、面ごとに異なります | 現実的な混合比での 3 種類すべての間隔と、古いブロックや位置のずれたブロック。この巡の前には存在しなかったデータとは一致しえません |
| short pulses | `00` の繰り返し。間隔の 100% が短い | 最も密な磁束。弱ったヘッドや摩耗した面が最初に分解できなくなる領域です |
| medium pulses | `24 49 92` の繰り返し。間隔の 99.9% 超が中間 | 上側の境界に最も近い種類。回転の遅いドライブで最初に失敗します |
| long pulses | `aa` の繰り返し。間隔の 99.9% 超が長い | 下側の境界に最も近い種類。回転の速いドライブで最初に失敗します |

面を満たすときは 8,949 バイトのファイルを 6 つ、ブロック合計 53,854 バイトを書きます。キャリブレーションディスクと同じ量で、理由も同じです。工場で書かれた 345 面のうち最大のものが 54,958 バイトであり、それを超えて書くと最後のファイルがトラックの終端からはみ出して、正常なディスクを損傷と判定しかねません。報告では、この最大の工場製の面に対する割合で充填量を示します。`--quick` は代わりに 4 KiB のファイルを 1 つだけ書きます。判定のためではなく、手早い確認のための指定です。

`--passes N` は 4 パターンの巡回全体を、毎回新しい鍵で繰り返します。死んだ箇所は毎回失敗し、境界にある箇所はそうならないため、両者を切り分ける手段がこの繰り返しです。

ある巡が失敗すると、コマンドはその面でドライブが実際に返したパルスを書いた間隔と比べ、読み違いがどちらへ偏っているかを示します。失敗したブロック全体で読み違いが一方へ偏っていれば、原因はドライブの回転速度です。回転の速いドライブは長い間隔を中間と読み、遅いドライブは中間を長いと読むからです。読み違いが両方向へ出ていれば、原因は磁性面です。閾値は `calibrate speed` と同じで、読み違いが 16 パルス以上あり、その 4 分の 3 が同じ方向へ偏っていることです。

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
| `leave` | 最後に書いたパターン、長いパルス。既定値です |
| `blank` | 工場出荷状態の面。ディスク情報ブロックとファイル数 0 のみで、店頭で購入した未書き込みディスクとバイト単位で同一です |
| `erase` | ブロックを一切残さないため、アダプタは何も読み取れません |

消去の後に有用なのは `blank` です。出力されるバイト列は `blank --formatted` と同一であり、ディスクは出荷時の状態で保管でき、書き込みソフトからは未使用の媒体として扱われます。

判定が決まった時点でテストは止まります。すでに劣化しているディスクに対して、それ以上のパスはディスクを傷めるだけだからです。

- 2 つのパターンで失敗したブロックが最初に出た時点で、損傷として止まります。
- ディスクが書き込みを受け付けなかった場合、書き込み不能として止まります。
- ドライブが止まった場合は、他のコマンドと同じく即座に止まります。

止まったテストは `--finish` を行いません。1 回だけ失敗したブロックでは止まりません。1 回の失敗はパスを重ねて切り分けるべき境界的なケースだからです。

`--sides 2` では、すべてのパスを A 面で行ったあと、ディスクを 1 回裏返すよう求め、すべてのパスを B 面で行います。終了処理は逆順に進みます。まだラベルが上を向いている B 面を先に処理し、もう 1 回裏返して A 面を処理するので、テスト全体で裏返すのは 2 回です。ディスクが本当に裏返されたかの確認は `write` と同じです。

```bash
fdstoolkit surface --sides 2 --passes 3 --backup before.fds --finish blank
```

```
a surface test destroys every byte on 2 side(s) of the disk in the drive. Use a scratch disk, never an original [y/N]: y
  side 0 pass 1 pattern unique data
  side 0 pass 1 pattern short pulses
  ...
  side 0 pass 3 pattern long pulses
turn the disk over so the side B label faces up, then confirm. The head sits under the disk and reads side B from the face turned down, so this drive cannot select a side on its own [y/N]: y
  side 1 pass 1 pattern unique data
  ...
  side 1 pass 3 pattern long pulses
  finishing side 1
turn the disk over so the side A label faces up, then confirm. The head sits under the disk and reads side A from the face turned down, so this drive cannot select a side on its own [y/N]: y
  finishing side 0
53854 data bytes per side, 98.0% of the most any measured factory side carries, 24 pattern pass(es) run
side 0 pass 1 pattern unique data: held
side 0 pass 1 pattern short pulses: held
...
side 1 pass 3 pattern long pulses: held
left the disk formatted as it leaves the kiosk, verified
grade clean
```

同じコマンドを、A 面の 1 か所が壊れたディスクで実行した場合です。判定がすでに決まっているため、裏返しを求める前、2 つ目のパターンで止まります。

```
  side 0 pass 1 pattern unique data
  side 0 pass 1 pattern short pulses
53854 data bytes per side, 98.0% of the most any measured factory side carries, 2 pattern pass(es) run
side 0 pass 1 pattern unique data: did not hold
side 0 pass 1 pattern short pulses: did not hold
in the blocks that failed, 23 read short and 19 read long: they go both ways, which is the surface rather than the drive's speed
1 block(s) failed on more than one pattern, which is the surface itself
stopped early: a block failed on two patterns, so the surface is damaged
grade failed
```

すべてのパターンが保持され、かつ終了処理が検証できた場合にのみ終了コード 0 を返します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/surface-dark.png">
<img alt="ローカル Web ページの surface コマンド" src="assets/screenshots/surface-light.png">
</picture>

#### `calibrate`

```bash
fdstoolkit calibrate speed|head [--reference <image>] [--side N] [--passes N] [--bracket] [--json]
fdstoolkit calibrate speed|head --captures <bundle> [--reference <image>] [--side N] [--json]
```

ドライブを調整している間、同じ面を繰り返し読み、読むたびに何が変わったかを示します。ドライバーをドライブに差したまま使うためのコマンドです。少し回し、次の行を見て、また回します。`--passes` は読む回数で、既定は 20、最大は 200 です。Ctrl-C、またはページの「中止」で、読み取り中の 1 回が終わったところで止まり、それまでの結果を報告します。

`--captures` は、ドライブを読む代わりに `dump --raw` が保存した読み取りを再生し、スティックをつながずに動きます。`--side` の保存済み読み取り 1 回ごとに 1 行を出すので、うまくいかなかった吸い出しを、あとからドライブの状態を知る材料として読み直せます。別のドライブから送られてきた一式も、そのドライブなしで判定できます。

ドライブに入れるディスクは、このドライブが書き込んだものであってはなりません。工場出荷のディスクか、信頼できるドライブで書き込んだディスクを使います。調整のずれたドライブは、自分では読めて他のドライブでは読めないディスクを書くため、自分の書いたディスクを読めても何の証明にもなりません。コマンドは最初の読み取りの前にそう表示します。

読み取りのたびに、ディスクの内容が求めるものとパルスごとに比べます。その内容は、手元にある最良の情報源から次の順に取ります。

| 情報源 | どこから来るか | 比べられるもの |
|---|---|---|
| `--reference` | 同じディスクのイメージ。信頼できるドライブで吸い出したもの、または既知の吸い出しと一致したもの | 最初の読み取りから、すべてのブロック |
| キャリブレーション用ディスク | ディスク情報とファイルヘッダから自動で認識し、ファイルは不要 | 最初の読み取りから、一度も正しく読めないブロックも含むすべてのブロック |
| 正しく読めたブロック | 実行中に学習する。ブロックがチェックサムを通れば、その内容が確定する | そのブロックを、以降のすべての読み取りで |

どれもない場合、最初の読み取りはチェックサムだけで判定するので、ブロックが読めたかどうかは分かっても、読めなかった理由は分かりません。わずかにずれているだけのドライブなら、ほとんどのブロックが一度は正しく読めるので学習がすぐにその穴を埋めます。一方、ブロックが一度も正しく読めないほどずれたドライブでは埋まらず、そこでリファレンスかキャリブレーション用ディスクが役に立ちます。`--side` はリファレンスのどの面がドライブに入っているかを示します。ラベルが上を向いている面で、下を向いた側から読まれます。

```
this is the fdstoolkit calibration disk, side 0: every pulse is compared with what the disk holds, including blocks that never read clean
```

ドライブには 3 つの調整箇所があり、このコマンドは FDSStick から見える範囲でそれぞれを扱います。

| 調整 | 場所 | `calibrate` が見るもの |
|---|---|---|
| モーターの速度 | モーター上の可変抵抗 | `speed`: リファレンスに対して短く、または長く読まれたパルス |
| スピンドルハブの位置。ベルト交換で失われる | 機構の上部にあるハブ。止めねじで固定 | `head`: 面のどのブロックが読めたか、失敗がどこにあるか |
| 読み取りヘッドの位置合わせ | ヘッドの調整ねじ | `head`: 同上 |

`speed` は読み取りごとに次の 5 つのいずれかを報告します。

| 判定 | 意味 |
|---|---|
| reads fast | 読み違えたパルスの大半が 1 クラス短い。モーターの速度を少し下げる |
| reads slow | 大半が 1 クラス長い。モーターの速度を少し上げる |
| errors with no speed bias | ブロックは失敗するが、どちらにも偏らない。速度の問題には見えない |
| nothing read | ブロックが 1 つも見つからない。速度が大きくずれているか、ヘッドかハブの位置がずれている |
| reads clean | すべてのブロックが読め、すべてのパルスが一致した |

読み違えたパルスが 16 個以上あり、その 4 分の 3 以上が同じ向きなら、その向きに偏っているとみなします。どちらの数値も、速度のずれと雑音を分けるものについての推論で決めたもので、実機で測ったものではありません。実機で最初に見直すべき値です。

```bash
fdstoolkit calibrate speed --reference smb.fds --passes 3
```

```
judge the drive only with a disk it did not write: a factory disk, or one written by a drive you trust. A drive out of adjustment reads back its own writes, so those prove nothing
  read 1: 2 of 10 blocks, 116 pulses short, 0 long, 0 invalid, console error 27, block failed CRC: reads fast, first read
  read 2: 2 of 10 blocks, 116 pulses short, 0 long, 0 invalid, console error 27, block failed CRC: reads fast, the same as the last read
  read 3: 10 of 10 blocks, 0 pulses short, 0 long, 0 invalid: reads clean, better than the last read
reads clean: inside the tolerance the stick can see. It cannot see the last percent, so finish with a console speed test or a strobe at the disk table
```

助言は速度を上げるか下げるかだけを示し、ねじをどちらへ回すかは示しません。反時計回りで速度が上がると書いた修理ガイドがありますが、頼る前に、小さく回して自分のドライブで確かめてください。

`speed` の reads clean は、RAM アダプタが受け付ける許容範囲に入っていることを意味し、正確な速度であることは意味しません。最後の詰めには実機側のテストを使います。Copy Master の速度テストは 1 から 9 を表示し、「too slow」「too fast」も示します。ToToTEK と Bung は、ディスクを入れた状態で 5 に合わせること、そして最初の 1 回はヘッドの位置が不定のまま始まるのでテストを 2 回続けて行うことを勧めています。ストロボのアプリも使えます。ディスクテーブルの軸は 400 RPM で回ります。

`head` は面のどのブロックが読めたかを報告します。

| 判定 | 意味 |
|---|---|
| the start of the side is not read | 最初のブロックが欠け、残りは読める。ヘッドの開始位置がずれている |
| the end of the side is not read | 面の終わり近くまで読める。ヘッドの移動範囲が足りない |
| errors across the side | 失敗が面全体に散らばる。位置ではなく、速度かディスクを疑う |
| nothing read | ブロックが見つからない。ヘッドかハブの位置が大きくずれているか、速度がずれている |
| reads clean | 面全体が読めた |

```bash
fdstoolkit calibrate head --reference smb.fds --passes 3
```

```
judge the drive only with a disk it did not write: a factory disk, or one written by a drive you trust. A drive out of adjustment reads back its own writes, so those prove nothing
  read 1: 6 of 10 blocks, blocks 0 to 3 not read, 0 pulses short, 0 long, 0 invalid, console error 22, block 1 expected: the start of the side is not read, first read
  read 2: 8 of 10 blocks, blocks 0 to 1 not read, 0 pulses short, 0 long, 0 invalid, console error 22, block 1 expected: the start of the side is not read, better than the last read
  read 3: 10 of 10 blocks, 0 pulses short, 0 long, 0 invalid: reads clean, better than the last read
reads clean: the whole side reads. Repeat with two more factory disks, since a head can be set to suit one disk and miss another
```

ヘッドの許容誤差はおよそ 0.05 mm なので、4 分の 1 回転ずつ調整して読み直します。正しく読めたら、さらに 2 枚の工場出荷のディスクで繰り返します。ヘッドは 1 枚のディスクに合っても別のディスクには合わないことがあるからです。どちらのモードも、どちらへ回すべきかは示せず、直前の調整がよくなったかどうかだけを示します。

失敗した読み取りには、本体ならどのエラーで止まるかも、本体自身のエラー表から示します。ブロック 1 から 4 が見つからなければ `22` から `25`、ブロックが見つかってもチェックサムが合わなければ `27` です。修理ガイドが話題にするのはこの番号なので、1 行がテレビに表示されるのと同じ形で読めます。これはスティックの読み取りを置き換えたもので、本体の読み取りそのものではありません。本体は自分のドライブ回路で読むので、1 ブロック早く、あるいは遅く止まることがあります。

`--bracket` は、修理ガイドがヘッドを合わせるのに使う方法を実行します。ディスクが読めなくなるまで動かし、反対側でも読めなくなるまで戻し、その中央に落ち着かせます。最初の読み取り以降、読み取りのたびに小さく 1 段、毎回同じ大きさだけ回すよう求めます。ヘッドのねじなら 8 分の 1 回転です。ディスクが読めなくなったところで向きを変えるよう伝え、反対側でも読めなくなったら、読めた範囲の幅と、その中央まで何段戻すかを示します。これは毎回同じ大きさで回した場合にだけ成り立つので、回した回数を数えてください。

```bash
fdstoolkit calibrate head --reference smb.fds --bracket --passes 60
```

ガイドは部品が収まるべき位置も公開しています。これは各自が自分のドライブを測った値で、任天堂の値ではなく、本ツールはどれも確かめられません。

| 部品 | 公開されている値 | 出典 |
|---|---|---|
| 読み取りヘッド | 遠い側の端がスピンドル中心から 35.5 mm、許容誤差 0.05 mm | [TinkerDifferent, drive calibration](https://tinkerdifferent.com/resources/famicom-fds-drive-calibration-wip.52/updates) |
| 読み取りヘッド | 間隔 10.72 mm、前後およそ 0.05 mm | [TinkerDifferent, calibration technique](https://tinkerdifferent.com/resources/famicom-disk-system-calibration-technique.39/) |
| ギア | フランジの穴が 8/9 または 9/10 番目の歯の位置 | [TinkerDifferent, calibration technique](https://tinkerdifferent.com/resources/famicom-disk-system-calibration-technique.39/) |
| スピンドルハブ | 工場出荷時の位置。1.5 mm の六角ねじで固定。ずれるとエラー 22 と 27 | [famicomdisksystem.com](https://www.famicomdisksystem.com/tutorials/fds-repair-mod/belt-replacement-adjustment/) |
| 速度 | あるガイドではディスクテーブル軸で 400 RPM、別のガイドではスピンドルで 820、モーターで 1170 | 上記の TinkerDifferent の 2 つのガイド |

2 つの速度の値はおよそ 2 倍異なり、どちらのガイドもその理由を示さず、値を RAM アダプタが確かめるビットレートにも結び付けていません。ストロボで合わせる際の出発点として扱い、このコマンドで確かめられる目標値とはみなさないでください。

最後の読み取りが正しく読めた場合に終了コード 0 を返します。

<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/calibrate-dark.png">
<img alt="ローカル Web ページの calibrate コマンド" src="assets/screenshots/calibrate-light.png">
</picture>

#### `web`

```bash
fdstoolkit web [--host <h>] [--port N] [--no-open]
```

ローカルのウェブインターフェースを開きます。`doctor` を除く上記のすべてのコマンドがそこから利用でき、各ルートはコマンドが呼ぶものとまったく同じ処理を呼び出します。`--no-open` はブラウザを開かずにサーバーだけを起動します。SSH 越しに使う場合はこちらです。既定では `127.0.0.1:8000` を待ち受けます。`doctor` はインストールを確認するコマンドなので、インストールを行った端末で使います。

## ウェブインターフェース

```bash
fdstoolkit web
```

`web` はブラウザでページを開きます。`fdstoolkit web --no-open` はブラウザを開かずにサーバーだけを起動します。SSH 越しに使う場合はこちらです。ヘッドレス専用のコマンドはありません。本ツールはこの端末に接続されたハードウェアを操作するものであり、公開サービスになることはないからです。

既定では `127.0.0.1:8000` を待ち受けます。これはサービスではありません。`--host` を指定しない限り公開インターフェースでは待ち受けず、ページは外部リソースを一切読み込まないため、データがこの端末から出ることはありません。

この設計が拠って立つ原則は、ウェブ層は何も判断しない、という一点です。各ルートはペイロードを解析し、コマンドが呼ぶのと同じ関数を呼び、返ってきたものを報告するだけです。ページ経由で求めた評価は、`grade` が表示するものと同じ信頼度と同じ根拠を持ちます。同じ呼び出しだからです。これは主張ではなく検証されています。テストは、同じ入力に対するルートの答えとコマンドの答えを突き合わせます。

保存したキャプチャも同じ経路を通ります。`keep captures` を付けた吸い出しは、イメージの横に 2 つ目のダウンロードとして一式を差し出し、`consensus`、`reads`、`grade`、`calibrate` はそれぞれ `captures` 欄でその zip を受け取ります。キャプチャを再生する調整はドライブを開かないので、スティックがなくても動きます。

| ルート | 対応するコマンド |
|---|---|
| `GET /api/catalogue` | プロファイル、形式、出力先の一覧 |
| `POST /api/info` | `info` |
| `POST /api/verify` | `verify` |
| `POST /api/hash` | `hash` |
| `POST /api/grade` | `grade` |
| `POST /api/reads` | `reads` |
| `GET /api/status` | `status` |
| `POST /api/blank` | `blank` |
| `POST /api/convert` | `convert` |
| `POST /api/jobs/dump` | `dump` |
| `POST /api/jobs/write` | `write` |
| `POST /api/jobs/surface` | `surface` |
| `POST /api/jobs/calibrate` | `calibrate` |
| `GET /api/jobs/current` | 実行中のディスク操作があれば、その操作 |
| `GET /api/jobs/{id}` | 1 つの操作の状態、進行状況の行、問いかけ、結果 |
| `POST /api/jobs/{id}/answer` | 操作の問いかけへの回答 |
| `POST /api/jobs/{id}/stop` | 読み取り中の 1 回が終わったところで調整を止める |

イメージとキャプチャは base64 で符号化してリクエストボディに載せます。`GET /docs` は生成された API リファレンスを提供するため、このページはエンドポイントの唯一の利用者ではなく、その 1 つにすぎません。

ページが提示する選択肢は `catalogue` から取得され、これは列挙型の上に構築されています。モデルにプロファイルを追加すれば、二度目の編集をせずともページに現れます。

`dump`、`write`、`surface` はこの端末に接続された FDSStick を操作します。1 面に数秒かかるため、1 回のリクエストではなく操作として実行されます。開始すると操作の ID がすぐに返り、ページはその操作を定期的に問い合わせて、コマンドが表示するのと同じ進行状況の行を 1 行ずつ表示します。ディスク操作は同時に 1 つだけ実行でき、2 つ目は 409 を返して、ドライブを使用中の操作を示します。FDSStick が接続されていない場合も 409 を返して原因を示します。

端末なら自然に得られるものを、ページが補います。

- `write` と `surface` は、開始前に何が消えるかを示すダイアログを開きます。フォーカスは「キャンセル」に置かれるため、反射的に Enter を押してもディスクは消えません。ダイアログを経ないリクエストは、消去を確認するまで拒否されます。
- 操作がディスクの裏返しを必要とすると、ページは「ディスクを裏返しました」と「中止」の 2 つのボタンとともに問いかけを表示します。10 分間回答がなければ「いいえ」とみなし、ドライブを解放します。
- 操作の実行中にタブを閉じたり再読み込みしたりすると、先に確認を求めます。タブを閉じてもドライブは止まらないからです。操作の実行中に開いたページは、2 つ目を始めるのではなく、その操作を引き継ぎます。
- `write` と `surface` は、結果にかかわらず、書き込み前の読み取りを `before.fds` として提供します。
- 書き込み中に止まった操作は、コマンドと同じく、その面が書きかけの可能性があると伝えます。

インターフェースは英語と日本語で提供されます。両方の辞書は同じキーを持ち、テストスイートがそれを信用ではなく検証します。マークアップまたはスクリプトが参照するキーは両方に存在しなければならず、日本語側に英語のまま残った文字列があってはなりません。

## 手順

### ディスクを保存する

1 回の吸い出しは、ドライブが 1 度何を読んだかを示すだけです。2 回でようやく、同じものを 2 度読めたかが分かります。

```bash
fdstoolkit dump -o pass1.fds --passes 3 --raw captures/
fdstoolkit dump -o pass2.fds
fdstoolkit reads pass1.fds pass2.fds
fdstoolkit reads --captures captures/
fdstoolkit grade pass1.fds --read pass2.fds --captures captures/
```

3 パスにすると、一式には各面の読み取りが 3 回そろいます。弱いブロックの一覧とパルス投票に必要なのはこれです。2 つの吸い出しが食い違う場合、`consensus` が多数決で統合し、決着しなかったブロックをすべて列挙します。`consensus pass1.fds pass2.fds --captures captures/` はパルス投票を投票者の 1 つとして加えます。一方の吸い出しで壊れているブロックが他方で正常なら、`splice` がそれを取り込みます。一式はイメージと一緒に保管してください。ディスクがどう読めたかを記録しているのはこれだけで、あとからディスクなしで投票し直せます。

### ドライブを調整する。粗調整から微調整へ

1. 何よりも先にヘッドを清掃してください。汚れは媒体の不良として現れます。
2. 工場出荷のディスク、または信頼できるドライブで書き込んだキャリブレーション用ディスクを用意します。このドライブが書き込んだディスクは決して使いません。工場出荷のディスクのイメージがあれば計数はより正確になり、なくても `calibrate` は正しく読めた読み取りから各ブロックを学習します。
3. ベルトを交換した後は `calibrate head` を実行し、スピンドルハブ、次にヘッドを 4 分の 1 回転ずつ調整して、すべての読み取りが正しくなるまで続けます。
4. `calibrate speed` を実行し、指示どおりにモーターの速度を上げ下げして、正しく読めるまで続けます。
5. スティックは最後の 1 パーセントを見られないので、速度の仕上げは実機側のテストかストロボで行います。
6. さらに 2 枚の工場出荷のディスクで `calibrate head` を繰り返します。そのうえで、読み取りが難しいと分かっているディスクで確認します。コミュニティでは 39 ファイルを含む特定の面が使われており、チェックサムエラーなしに 39 個すべて読めれば合格です。

### ドライブとディスクのどちらが原因かを判断する

1 枚のディスクではこの問いに答えられません。複数枚を読んで、どこで失敗したかを比べてください。どのディスクでも同じ場所で失敗するならドライブ、1 枚だけで起きるならそのディスク、ドライブが応答しなくなるならそのどちらでもありません。最後の場合の正しい対応は、別のディスクを入れて試すことではなく、中止することです。

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
| パック済みパルスクラス、`raw03` | 可変 | あり | 1 パルスにつき 2 ビット、FDSStick が量子化済み |

各変換で失われるもの。

| 変換元 | 変換先 | 失われるもの |
|---|---|---|
| `.fds` ヘッダ付き | `.fds` ヘッダなし | 宣言された面数 |
| `.qd` | `.fds` | 保存されていたチェックサムすべて |
| `.fds` | `.qd` | なし。ただしチェックサムは合成されます |
| 任意 | 正規化形式 | プロファイルが除外するものすべて |

ファイルヘッダのサイズは申告にすぎず、コピープロテクトの中にはこれを偽るものがあります。実際には 48 KiB あるファイル本体の前に、1 バイトと申告するヘッダを置く例です。パルスキャプチャや `.qd` のようにチェックサムがある場合は、ブロック自身のチェックサムが一致し、その直後に次のブロックかギャップが始まる位置までファイル本体を読み、`FDS016` でその差を示します。`.fds` にはその位置を見つけるチェックサムがないため、バイト列は保たれても境界は保たれません。

## 終了コードとスクリプト化

`0` は異常なし、`1` は異常ありを意味します。何を異常とみなすかはコマンドごとに異なり、上に記載してあります。`splice` なら修復できなかったブロック、`consensus` なら吸い出しどうしが一致しなかったブロック、`calibrate` なら正しく読めなかった最後の読み取りです。

報告を行うコマンドはすべて `--json` を受け付け、その JSON は人間向け出力と同じデータです。標準出力には結果だけが出ます。進行状況、注意書き、操作者への確認は標準エラー出力へ出るため、`jq` へのパイプには結果以外が混ざりません。ファイルを書き出すコマンドは `--force` なしに上書きしません。

```bash
fdstoolkit verify disk.fds --json | jq -r '.findings[] | "\(.code) \(.message)"'
fdstoolkit consensus a.fds b.fds c.fds -o merged.fds --json | jq '.disagreements'
fdstoolkit calibrate speed --reference smb.fds --passes 5 --json | jq -r '.headline'
```

## このツールにできないこと

**ディスクシステムのフラックスキャプチャは存在しません。** Quick Disk はインデックス穴も標準的なステッピングも持たない 1 本の連続した渦巻きであり、KryoFlux や Greaseweazle はこの媒体を読むことができません。本ツールが読み込むのは FDSStick が生成するものだけです。

**FDSStick ではドライブ速度の最後の 1 パーセントを測定できません。** この機器はハードウェアの側で各パルスを 3 種類の長さのいずれかへ丸め、時間情報ではなくクラスを送ってくるので、小さな速度のずれではクラスが変わりません。`calibrate speed` は許容範囲の外にあるドライブを見つけ、仕上げは実機側のテストかストロボで行います。

**ヘッドの精密な位置合わせはパルスクラスからは測定できません。** 信号振幅が必要です。`calibrate head` はブロックが読めたかどうかしか見ないので、位置が大きくずれたヘッドやハブは見つけられても、わずかに中心を外れただけのものは見つけられません。

**ベルトの不良とモーターの不良は切り分けられません。** プーリー比が必要ですが、信頼できる出典がその値を示していません。

## 貢献

開発環境の構築、テストスイート、リリース手順は [CONTRIBUTING.md](CONTRIBUTING.md) にあります。

## ライセンス

MIT です。[LICENSE](LICENSE) を参照してください。

---

<div align="center">

ファミコン ディスクシステム / ディスクカード の保存、吸い出し、ディスク品質の測定、
ドライブの調整、ベルト交換、モーター回転数の調整、FDSStick。

English documentation: <a href="README.md">README.md</a>

</div>
