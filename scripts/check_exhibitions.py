"""exhibitions.js（美術館の展覧会）の検査・整形・古い展覧会の削除を行う。

使い方:
  python scripts/check_exhibitions.py            # 検査のみ（問題があれば終了コード1）
  python scripts/check_exhibitions.py --fix      # 検査 + 終了後14日を過ぎた展覧会を削除 + 整形して保存
  python scripts/check_exhibitions.py --fix --updated 2026-10-26   # 更新日も書き換える
"""
import argparse, datetime as dt, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "exhibitions.js"
PREFIX = "window.EXHIBIT_DATA = "
PREFS = set("北海道 青森 岩手 宮城 秋田 山形 福島 茨城 栃木 群馬 埼玉 千葉 東京 神奈川 新潟 富山 石川 福井 山梨 長野 "
            "岐阜 静岡 愛知 三重 滋賀 京都 大阪 兵庫 奈良 和歌山 鳥取 島根 岡山 広島 山口 徳島 香川 愛媛 高知 "
            "福岡 佐賀 長崎 熊本 大分 宮崎 鹿児島 沖縄".split())
GENRES = {"古美術", "浮世絵", "近代絵画", "西洋美術", "現代美術", "写真", "デザイン", "工芸", "マンガ・絵本", "書", "歴史・考古", "芸術祭"}
SCALES = {"L", "M", "S"}
KEYS = ["title", "museum", "pref", "start", "end", "genre", "scale", "official", "source"]
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEEP_DAYS = 14
JST = dt.timezone(dt.timedelta(hours=9))


def load():
    text = PATH.read_text(encoding="utf-8").strip()
    if not text.startswith(PREFIX):
        sys.exit(f"exhibitions.js は '{PREFIX}' で始まる必要があります")
    return json.loads(text[len(PREFIX):].rstrip(";"))


def day(s):
    return dt.date.fromisoformat(s)


def norm(s):
    return re.sub(r"[\s　・、。「」『』（）()〜～\-――:：]", "", str(s))


def check(data):
    errors = []
    if not DATE.match(str(data.get("updated", ""))):
        errors.append("updated が YYYY-MM-DD ではありません")
    seen = {}
    for i, e in enumerate(data.get("items", [])):
        tag = f"#{i} {e.get('title', '?')}"
        if set(e) != set(KEYS):
            errors.append(f"{tag}: キーは {KEYS} のみにしてください（現在 {sorted(e)}）")
            continue
        for k in ("title", "museum"):
            if not isinstance(e[k], str) or not e[k].strip():
                errors.append(f"{tag}: {k} が空です")
        if e["pref"] not in PREFS:
            errors.append(f"{tag}: pref '{e['pref']}' は都道府県名（「県」「府」「都」なし）")
        if e["genre"] not in GENRES:
            errors.append(f"{tag}: genre は {sorted(GENRES)} のどれか")
        if e["scale"] not in SCALES:
            errors.append(f"{tag}: scale は L（話題の大型展）/ M / S（小さめの館・展示）のどれか")
        for k in ("start", "end"):
            if not DATE.match(str(e[k])):
                errors.append(f"{tag}: {k} '{e[k]}' が YYYY-MM-DD ではありません（展覧会は終了日が必須）")
        if DATE.match(str(e["start"])) and DATE.match(str(e["end"])) and day(e["end"]) < day(e["start"]):
            errors.append(f"{tag}: end が start より前です")
        if not str(e["source"]).startswith("https://"):
            errors.append(f"{tag}: source は https:// で始まるURL（会期を確認したページ）")
        if e["official"] is not None and not str(e["official"]).startswith("https://"):
            errors.append(f"{tag}: official は https:// で始まるURLか null")
        key = (norm(e["museum"]), norm(e["title"])[:12])
        if key in seen:
            errors.append(f"{tag}: #{seen[key]} と同じ美術館・同じ展覧会の重複の可能性があります。1件にまとめてください")
        seen[key] = i
    return errors


def dump(data):
    lines = [json.dumps({k: e[k] for k in KEYS}, ensure_ascii=False, separators=(",", ":")) for e in data["items"]]
    head = PREFIX + '{"updated":' + json.dumps(data["updated"]) + ',"items":[\n'
    return head + ",\n".join(lines) + "\n]};\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="古い展覧会を削除して整形保存する")
    ap.add_argument("--updated", help="updated に書き込む日付 (YYYY-MM-DD)")
    ap.add_argument("--today", help="判定に使う今日の日付（省略時は日本時間の今日）")
    a = ap.parse_args()
    today = day(a.today) if a.today else dt.datetime.now(JST).date()

    data = load()
    errors = check(data)
    if errors:
        print("問題が見つかりました:")
        for x in errors:
            print(" -", x)
        sys.exit(1)

    removed = []
    if a.fix:
        cutoff = today - dt.timedelta(days=KEEP_DAYS)
        keep = []
        for e in data["items"]:
            (removed if day(e["end"]) < cutoff else keep).append(e)
        data["items"] = sorted(keep, key=lambda e: (e["start"], e["pref"], e["museum"]))
        if a.updated:
            data["updated"] = a.updated
        PATH.write_text(dump(data), encoding="utf-8")

    items = data["items"]
    live = sum(1 for e in items if day(e["start"]) <= today <= day(e["end"]))
    plan = sum(1 for e in items if day(e["start"]) > today)
    offi = sum(1 for e in items if e["official"])
    prefs = len({e["pref"] for e in items})
    print(f"OK: {len(items)}件（開催中 {live} / 予定 {plan} / 終了 {len(items) - live - plan}）{prefs}都道府県・公式URLあり {offi}件 基準日 {today}")
    for e in removed:
        print(f"削除（終了から{KEEP_DAYS}日経過）: {e['title']}（{e['museum']}）")


if __name__ == "__main__":
    main()
