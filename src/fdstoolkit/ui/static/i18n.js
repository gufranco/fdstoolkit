const DICTIONARIES = {
  en: {
    'page.parity': 'Every command the toolkit offers is here, and each one calls exactly what the command line calls.',
    'page.filter': 'Filter commands',
    'title': 'fdstoolkit',
    'tagline': 'An instrument for Famicom Disk System media.',
    'nav.inspect': 'Inspect',
    'nav.identity': 'Identity',
    'nav.quality': 'Quality',
    'nav.flux': 'Flux',
    'nav.drive': 'Drive',
    'nav.build': 'Build',
    'nav.doctor': 'Doctor',
    'drop.image': 'Choose a .fds or .qd image',
    'drop.capture': 'Choose a flux capture',
    'drop.hint': 'Nothing leaves this machine. The page talks to a server you started.',
    'button.run': 'Measure',
    'button.download': 'Download',
    'inspect.heading': 'What is on the disk',
    'inspect.blurb': 'Sides, blocks and every file, including any past the declared count.',
    'verify.heading': 'Findings',
    'verify.blurb': 'Structural and checksum findings, each with a code.',
    'verify.strict': 'Treat warnings as failures',
    'identity.heading': 'Hashes and identity',
    'identity.blurb': 'Two copies of one release never share a SHA-256, because the kiosk stamped each disk with its own serial and date. A profile decides which fields count before hashing.',
    'identity.profile': 'Profile',
    'quality.heading': 'Grade',
    'quality.blurb': 'A grade with the measurement behind it. A checksum answers one bit about a 65,500 byte side; this answers more.',
    'quality.margin': 'Flux margin, if you measured one',
    'reads.heading': 'Repeated reads',
    'reads.blurb': 'One dump says what the drive read once. Two say whether it read the same thing twice.',
    'reads.add': 'Add another dump of the same disk',
    'flux.heading': 'Flux capture',
    'flux.blurb': 'Fitted bit cell, cluster centres and jitter, separation margin, and which tracks carry no coherent data.',
    'flux.format': 'Format',
    'flux.auto': 'Detect from the file',
    'drive.heading': 'Drive adjustment',
    'drive.blurb': 'Everything here is measured against the bit rate, never a rotation speed. The RAM adapter expects 96.4 kbit/s and tolerates ten percent, and that is the only figure the hardware enforces.',
    'drive.cycles': 'Cycles between bytes, from a disk lister on the console',
    'drive.tune': 'Or measure a timing capture',
    'classes.heading': 'Pulse classes',
    'classes.blurb': 'For captures that carry classes rather than timing. An FDSStick rounds every pulse in hardware, so it cannot measure speed.',
    'build.heading': 'Build a blank',
    'build.blurb': 'A formatted blank carries the values measured from 1,729 never-rewritten sides.',
    'build.sides': 'Sides',
    'build.formatted': 'Write a disk information block',
    'build.headered': 'Add an fwNES header',
    'build.name': 'Game name, three characters',
    'convert.heading': 'Convert',
    'convert.blurb': 'Between .fds and .qd. A round trip through .qd synthesises checksums that were never there.',
    'convert.toqd': 'Write .qd instead of .fds',
    'doctor.heading': 'This installation',
    'doctor.blurb': 'Each check does the work rather than asking whether it could be done: a known disk is encoded and decoded again, a blank is hashed against the published reference, and a synthesised capture is measured back to the nominal rate.',
    'error.none': 'Choose a file first.',
    'error.failed': 'That did not work:',
    'result.empty': 'Nothing measured yet.',
    'footer.cli': 'Every measurement here is the one the command line reports. The page computes nothing of its own.',
  },
  ja: {
    'page.parity': '本ツールが提供するすべてのコマンドがここにあります。いずれもコマンドラインが呼ぶものとまったく同じ処理を呼び出します。',
    'page.filter': 'コマンドを絞り込む',
    'title': 'fdstoolkit',
    'tagline': 'ファミコン ディスクシステムのディスクカードのための計測器です。',
    'nav.inspect': '検査',
    'nav.identity': '同一性',
    'nav.quality': '品質',
    'nav.flux': 'フラックス',
    'nav.drive': 'ドライブ',
    'nav.build': '生成',
    'nav.doctor': '診断',
    'drop.image': '.fds または .qd イメージを選択',
    'drop.capture': 'フラックスキャプチャを選択',
    'drop.hint': 'データはこの端末から出ません。このページは、あなたが起動したサーバーとだけ通信します。',
    'button.run': '測定する',
    'button.download': 'ダウンロード',
    'inspect.heading': 'ディスクの内容',
    'inspect.blurb': '面、ブロック、そして宣言数を超えた位置にあるものも含むすべてのファイル。',
    'verify.heading': '検出結果',
    'verify.blurb': '構造とチェックサムの検出結果を、それぞれコード付きで表示します。',
    'verify.strict': '警告も失敗として扱う',
    'identity.heading': 'ハッシュと同一性',
    'identity.blurb': '同じタイトルの 2 本が SHA-256 を共有することはありません。ディスクライターが 1 枚ずつ固有のシリアルと日付を刻印するためです。プロファイルは、ハッシュを取る前にどのフィールドを数えるかを決めます。',
    'identity.profile': 'プロファイル',
    'quality.heading': '評価',
    'quality.blurb': '根拠となる測定値を添えた評価です。チェックサムは 65,500 バイトの 1 面について 1 ビットしか答えませんが、これはそれ以上を答えます。',
    'quality.margin': 'フラックスマージン、測定済みの場合',
    'reads.heading': '繰り返し読み取り',
    'reads.blurb': '1 回の吸い出しは、ドライブが 1 度何を読んだかを示すだけです。2 回でようやく、同じものを 2 度読めたかが分かります。',
    'reads.add': '同じディスクの別の吸い出しを追加',
    'flux.heading': 'フラックスキャプチャ',
    'flux.blurb': 'フィッティングされたビットセル長、クラスタの中心とジッタ、分離マージン、そして一貫したデータを持たないトラック。',
    'flux.format': '形式',
    'flux.auto': 'ファイルから自動判定',
    'drive.heading': 'ドライブ調整',
    'drive.blurb': 'ここでのすべての測定はビットレートを基準としており、回転数は使いません。RAM アダプタは 96.4 kbit/s を期待し、許容範囲は 10 パーセントです。ハードウェアが実際に要求しているのはこの数値だけです。',
    'drive.cycles': '実機のディスク一覧表示ツールが示すバイト間サイクル数',
    'drive.tune': 'または時間情報を持つキャプチャを測定',
    'classes.heading': 'パルスクラス',
    'classes.blurb': '時間情報ではなくクラスを持つキャプチャ向けです。FDSStick はハードウェア側で各パルスを丸めるため、速度を測定できません。',
    'build.heading': '空のイメージを作る',
    'build.blurb': 'フォーマット済みの空イメージは、一度も書き換えられていない 1,729 面から実測した値を持ちます。',
    'build.sides': '面数',
    'build.formatted': 'ディスク情報ブロックを書く',
    'build.headered': 'fwNES ヘッダを付ける',
    'build.name': 'ゲーム名、3 文字',
    'convert.heading': '変換',
    'convert.blurb': '.fds と .qd の相互変換。.qd を経由する往復変換は、元々存在しなかったチェックサムを合成します。',
    'convert.toqd': '.fds ではなく .qd を書く',
    'doctor.heading': 'このインストール',
    'doctor.blurb': '各項目は、できるかどうかを尋ねるのではなく実際に処理を行います。既知のディスクを符号化して復号し直し、空イメージを公開済みの参照値と照合し、合成したキャプチャを測定して公称レートに戻ることを確かめます。',
    'error.none': '先にファイルを選択してください。',
    'error.failed': '処理できませんでした:',
    'result.empty': 'まだ何も測定していません。',
    'footer.cli': 'ここに表示されるすべての測定値は、コマンドラインが報告するものと同一です。このページ自身は何も計算しません。',
  },
};

const FALLBACK = 'en';

function storedLanguage() {
  try {
    return window.localStorage.getItem('fdstoolkit.language');
  } catch (error) {
    return null;
  }
}

function rememberLanguage(code) {
  try {
    window.localStorage.setItem('fdstoolkit.language', code);
  } catch (error) {
    return;
  }
}

function initialLanguage() {
  const stored = storedLanguage();
  if (stored && DICTIONARIES[stored]) {
    return stored;
  }
  const browser = (navigator.language || FALLBACK).slice(0, 2);
  return DICTIONARIES[browser] ? browser : FALLBACK;
}

window.i18n = { DICTIONARIES, FALLBACK, initialLanguage, rememberLanguage };
