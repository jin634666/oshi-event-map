"""events.js の検査・整形・古いイベントの削除を行う。

使い方:
  python scripts/check_events.py            # 検査のみ（問題があれば終了コード1）
  python scripts/check_events.py --fix      # 検査 + 終了後30日を過ぎたイベントを削除 + 整形して保存
  python scripts/check_events.py --fix --updated 2026-10-26   # 更新日も書き換える
"""
import argparse, datetime as dt, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATH = ROOT / "events.js"
PREFIX = "window.EVENT_DATA = "
PREFS = set("北海道 青森 岩手 宮城 秋田 山形 福島 茨城 栃木 群馬 埼玉 千葉 東京 神奈川 新潟 富山 石川 福井 山梨 長野 "
            "岐阜 静岡 愛知 三重 滋賀 京都 大阪 兵庫 奈良 和歌山 鳥取 島根 岡山 広島 山口 徳島 香川 愛媛 高知 "
            "福岡 佐賀 長崎 熊本 大分 宮崎 鹿児島 沖縄 全国 オンライン".split())
TYPES = {"cafe", "popup", "exhibit", "event"}
KEYS = ["type", "title", "work", "venues", "note", "official", "source"]
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEEP_DAYS = 30
JST = dt.timezone(dt.timedelta(hours=9))


def load():
    text = PATH.read_text(encoding="utf-8").strip()
    if not text.startswith(PREFIX):
        sys.exit(f"events.js は '{PREFIX}' で始まる必要があります")
    return json.loads(text[len(PREFIX):].rstrip(";"))


def day(s):
    return dt.date.fromisoformat(s)


def check(data):
    errors = []
    if not DATE.match(str(data.get("updated", ""))):
        errors.append("updated が YYYY-MM-DD ではありません")
    seen = set()
    for i, e in enumerate(data.get("events", [])):
        tag = f"#{i} {e.get('title', '?')}"
        if set(e) != set(KEYS):
            errors.append(f"{tag}: キーは {KEYS} のみにしてください（現在 {sorted(e)}）")
        if e.get("type") not in TYPES:
            errors.append(f"{tag}: type は {sorted(TYPES)} のどれか")
        for k in ("title", "work"):
            if not isinstance(e.get(k), str) or not e.get(k).strip():
                errors.append(f"{tag}: {k} が空です")
        for k in ("official", "source"):
            v = e.get(k)
            if v is not None and not str(v).startswith("https://"):
                errors.append(f"{tag}: {k} は https:// で始まるURLか null")
        if not e.get("official") and not e.get("source"):
            errors.append(f"{tag}: official と source の両方が空です（情報元が必要）")
        venues = e.get("venues") or []
        if not venues:
            errors.append(f"{tag}: venues が空です")
        for v in venues:
            if set(v) != {"pref", "place", "start", "end"}:
                errors.append(f"{tag}: 会場のキーは pref/place/start/end")
                continue
            if v["pref"] not in PREFS:
                errors.append(f"{tag}: pref '{v['pref']}' は都道府県名（「県」「府」「都」なし）か 全国/オンライン")
            if not DATE.match(str(v["start"])):
                errors.append(f"{tag}: start '{v['start']}' が YYYY-MM-DD ではありません")
            elif v["end"] is not None:
                if not DATE.match(str(v["end"])):
                    errors.append(f"{tag}: end '{v['end']}' が YYYY-MM-DD か null ではありません")
                elif day(v["end"]) < day(v["start"]):
                    errors.append(f"{tag}: end が start より前です")
        key = (e.get("title"), e.get("work"))
        if key in seen:
            errors.append(f"{tag}: 同じ title/work のイベントが重複しています")
        seen.add(key)
    errors += find_duplicates(data.get("events", []))
    return errors


def find_duplicates(events):
    """名前の書き方が違っても、種類・作品・会場の会期が同じなら同一イベントとみなす。"""
    def sig(e):
        try:
            return (e["type"], tuple(sorted((v["pref"], v["start"], v["end"] or "") for v in e["venues"])))
        except (KeyError, TypeError):
            return None
    def same_work(a, b):
        a, b = a.replace(" ", ""), b.replace(" ", "")
        return a[:3] == b[:3] or a in b or b in a
    out = []
    for i, a in enumerate(events):
        for j in range(i + 1, len(events)):
            b = events[j]
            if sig(a) and sig(a) == sig(b) and same_work(str(a.get("work", "")), str(b.get("work", ""))):
                out.append(f"#{i}「{a.get('title')}」と #{j}「{b.get('title')}」は同じイベントの重複の可能性があります。1件にまとめてください")
    return out


def last_day(e):
    ends = [v["end"] for v in e["venues"]]
    if any(x is None for x in ends):
        return None
    return max(day(x) for x in ends)


def dump(data):
    lines = [json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in data["events"]]
    head = PREFIX + '{"updated":' + json.dumps(data["updated"]) + ',"events":[\n'
    return head + ",\n".join(lines) + "\n]};\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="古いイベントを削除して整形保存する")
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
        for e in data["events"]:
            ld = last_day(e)
            (removed if ld is not None and ld < cutoff else keep).append(e)
        data["events"] = keep
        if a.updated:
            data["updated"] = a.updated
        PATH.write_text(dump(data), encoding="utf-8")

    def status(e):
        s = [("live" if day(v["start"]) <= today and (v["end"] is None or day(v["end"]) >= today)
              else "plan" if day(v["start"]) > today else "end") for v in e["venues"]]
        return "live" if "live" in s else "plan" if "plan" in s else "end"
    counts = {"live": 0, "plan": 0, "end": 0}
    for e in data["events"]:
        counts[status(e)] += 1
    print(f"OK: {len(data['events'])}件（開催中 {counts['live']} / 予定 {counts['plan']} / 終了 {counts['end']}）基準日 {today}")
    for e in removed:
        print(f"削除（終了から{KEEP_DAYS}日経過）: {e['title']}")


if __name__ == "__main__":
    main()
