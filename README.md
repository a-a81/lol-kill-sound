# LoL キル確認音（ローカルツール）

リーグ・オブ・レジェンドで自分がキルを取ったとき、自分で用意したキル確認音を再生する **Windows 向けローカルツール**です。

- **ゲーム改造なし**（メモリ読み取り・注入・オーバーレイ改造なし）
- 検知は Riot **Live Client Data API** のみ（`https://127.0.0.1:2999/liveclientdata/...`）
- Python 標準ライブラリ中心（追加パッケージ不要）
- **MP3 / WAV** 対応（MP3 は Windows 標準の MediaPlayer／Media Foundation。追加インストール不要）

仕組みと設計の判断は [SPEC.md](SPEC.md) にまとめています。

---

## 必要なもの

- Windows
- **Python 3.10+**（下記のインストール手順）
- 起動中の LoL 対局（カスタム / プラクティスツール可）。API は **対局中のみ** `2999` で待ち受けます
- 自分で用意したキル確認音（MP3 / WAV）。音ファイルは同梱していません（下の「音ファイルの用意」）

> **著作権について:** このリポジトリには音声ファイルを含めていません。使う権利のある音を自分で用意してください。このツールでゲームファイルを抽出・スクレイピングしないでください。

---

## Python のインストール（Windows）

1. [python.org](https://www.python.org/downloads/) から **Python 3.10+** のインストーラを入手する  
   （Microsoft Store 版でも可だが、PATH が通りやすい **公式インストーラを推奨**）
2. インストール時に **「Add python.exe to PATH」に必ずチェック**
3. インストール後、**新しい**コマンドプロンプトを開き、確認:

```bat
python --version
```

（`py -3 --version` でも可）

4. このフォルダに音ファイルを置き（下の「音ファイルの用意」）、フォルダ内で `run.bat` を実行

ウィンドウがすぐ閉じる場合は、コマンドプロンプトで `cmd /k run.bat` を使ってください（エラー文言が残ります）。  
Python を入れた直後は **PATH が反映されるよう、いったん端末を閉じて開き直してから** `run.bat` を再実行してください。

追加の `pip install` は不要です。

---

## インストール（配置）

1. このフォルダ `lol-kill-sound` を任意の場所に置く
2. 上の手順で `python --version` が通ることを確認する

---

## 音ファイルの用意

音ファイルは同梱していないので、最初に一度だけ置いてください。置かないまま起動すると、置き場所を案内するエラーで止まります。

| パス | 意味 |
|------|------|
| `sounds/kill-confirm.mp3` | **既定の音**（`config.json` の `sound_path`） |

任意で別の MP3／WAV を置き、`config.json` の `sound_path`（または `--sound`）を合わせても使えます。

手順:

1. 使う権利のあるキル確認音を用意する
2. `sounds/kill-confirm.mp3` として保存（または任意名にして `sound_path` を合わせる）

テスト再生:

```bat
run.bat --test-sound
```

---

## 実行方法

1. LoL クライアントを起動し、対局（またはプラクティス）に入る
2. このフォルダで:

```bat
run.bat
```

または:

```bat
python lol_kill_sound.py
```

3. コンソールに `In game as ... Watching…` と出たら待機中です
4. キルが増えるたびに音が鳴ります（増加分だけ再生、短いデバウンス付き）
5. 終了は `Ctrl+C`

便利オプション:

```bat
run.bat --once-check
run.bat --test-sound
run.bat --poll 0.5
run.bat --sound sounds\my-kill.mp3
```

手動の `run.bat` はそのまま使えます（自動起動と併用も可。二重起動はヘルパー側で避けます）。

---

## LoL起動時に自動で動かす

毎回 `run.bat` を押さなくてもよいように、**LoL のプロセスを監視してキル音ウォッチャーを一度だけ起動するヘルパー**があります。

1. このフォルダで **一度** 次を実行する（このヘルパー自体が動いている必要があります）:

```bat
watch-lol-and-start.bat
```

2. ヘルパーが `LeagueClient.exe` / `League of Legends.exe` を見つけると、まだ動いていなければ `lol_kill_sound.py` を **新しいコンソール** で起動します（`Watching…` が見えます）
3. LoL を終了してもウォッチャーは閉じません（API 待ちでアイドル）。LoL をまた起動したとき、ウォッチャーが落ちていれば再起動します
4. 二重起動はしません

ログイン時から待つ場合（任意）:

```bat
install-startup-shortcut.bat
```

Startup フォルダに `watch-lol-and-start.bat` へのショートカットを作ります。無効にするときは `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup` からそのショートカットを削除してください。

---

## 仕組み（要約）

1. `https://127.0.0.1:2999` に HTTPS でポーリング（自己署名証明書はローカル用途のため検証スキップ）
2. `activeplayer` / `activeplayername` で自分の Riot ID を取得
3. `playerscores`（または `playerlist`）の **kills** を監視
4. キル数が増えたら選定した音を再生（MP3 は PowerShell `MediaPlayer`、WAV は `winsound`／追加インストール不要）
5. 任意で `eventdata` の `Multikill` をログ表示（二重再生はしない）

---

## トラブルシューティング

### 対局が検知されない / `Live Client reachable: False`

- **実際にマップに入っているか**確認（ロビー・チャンピオンセレクト中は API が出ません）
- プラクティスツールやカスタムでも可。対局プロセスが `2999` を開いている必要があります
- `--once-check` で確認:

```bat
run.bat --once-check
```

- ファイアウォールが `python.exe` のローカル通信を遮断していないか確認
- VPN / セキュリティソフトが `127.0.0.1:2999` を妨げていないか確認

### 証明書（SSL）エラー

- 本ツールは Live Client の自己署名証明書向けに **localhost の証明書検証を無効化**しています
- それでも失敗する場合は、別の Python / プロキシが HTTPS を改変していないか確認してください
- ブラウザで `https://127.0.0.1:2999/liveclientdata/gamestats` を開くと警告が出るのは正常です（ゲーム側の自己署名のため）

### 音が鳴らない

- まず `run.bat --test-sound`
- `config.json` の `sound_path`（既定: `sounds/kill-confirm.mp3`）が実在するか
- Windows の音量ミキサーでミュートされていないか（MP3 は **Windows PowerShell**、WAV は **python.exe** として表示されます）
- ステレオミキサー / 既定再生デバイスを確認
- MP3 が鳴らない場合は別プレイヤーで開けるか確認（壊れた MP3／特殊コーデック）

### キルなのに鳴らない / 二重に鳴る

- ポーリング間隔を変える: `--poll 0.25` など
- デバウンス: `--debounce 0.2`
- キル数の増加分だけ再生します。一気に +2 なら 2 回（間隔付き）鳴ります

### `Python が見つかりません` / ウィンドウがすぐ閉じる

- 上記「Python のインストール」をやり直し、**Add python.exe to PATH** にチェックを入れる
- 入れた直後は **新しい**コマンドプロンプトで `python --version`（または `py -3 --version`）を確認
- ダブルクリックで一瞬で閉じる場合: `cmd /k run.bat` で起動し、エラー内容を確認
- `run.bat` は `py -3` → `python` → `%LocalAppData%\Programs\Python\Python3*\python.exe` の順で探します
- または `py -3 lol_kill_sound.py` を直接使う

---

## 設定 (`config.json`)

```json
{
  "poll_interval_s": 0.35,
  "debounce_s": 0.15,
  "sound_path": "sounds/kill-confirm.mp3"
}
```

---

## やらないこと

- ゲームメモリの読み取り・書き込み
- DLL 注入、パケット改ざん、チート的オーバーレイ
- 著作権のあるゲーム音声の再配布・自動抽出

安全な範囲は **公式 Live Client Data API の読み取り + ローカル音声再生** のみです。
